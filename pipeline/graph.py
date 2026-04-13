# pipeline/graph.py
"""
LangGraph 기반 수불 분석 챗봇 플로우.

수업에서 배운 기법 적용:
  - LangGraph add_messages : 대화 상태 관리
  - LangGraph LLM 조건부 분기 : 라우터가 쿼리 유형 판단
  - LangGraph Router (조건부 엣지) : RAG / 데이터분석 경로 분기
  - CSV 에이전트 (데이터분석 노드) : LLM이 pandas 코드 생성 후 실행
  - 하이브리드 서치 리랭커 : BM25 + TF-IDF → RRF 결합
"""
from __future__ import annotations

import re
import traceback
from typing import Annotated, Literal, TypedDict

import pandas as pd
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


# ── 상태 정의 (add_messages 적용) ────────────────────────────

class ChatState(TypedDict):
    messages: Annotated[list, add_messages]   # LangGraph add_messages
    route: str                                 # "rag" | "analysis"
    context: list[str]                         # RAG 검색 결과
    answer: str                                # 최종 답변


# ── 시스템 프롬프트 ───────────────────────────────────────────

ROUTER_PROMPT = """\
사용자 질문을 아래 두 유형 중 하나로 분류하세요.

[rag] - 단순 데이터 조회: 특정 수치, 현황, 목록 조회
  예) "포항소 재고는?", "가장 많이 납품한 공급사는?", "ADS01 입고량"

[analysis] - 데이터 분석·계산·비교·통계: 집계, 비율, 추이, 상관관계
  예) "사용량이 가장 많은 달은?", "계획 대비 실적 달성률", "품목별 재고 비율"

질문: {query}

반드시 [rag] 또는 [analysis] 중 하나만 답하세요."""

RAG_SYSTEM = """\
당신은 철강 제조 공장 수불(입고·사용·재고) 전문 AI입니다.
포항소·광양소의 수불 데이터를 바탕으로 정확하고 간결하게 답변하세요.

규칙:
- 제공된 [컨텍스트] 수치만 사용하세요.
- 컨텍스트에 없으면 구체적으로 질문을 하세요. "데이터 없음"이라 답하세요.
   예) "원하시는 데이터의 기간은 언제부터 언제까지인가요?", "원하시는 데이터의 사소는 어디인가요?", "원하시는 데이터의 품목은 무엇인가요?", "원하시는 데이터의 공급사는 무엇인가요?", "원하시는 데이터의 등급은 무엇인가요?"
- 수치는 천 단위 콤마 포함 (예: 1,234).
- 실적과 계획을 혼동하지 마세요.
- 기간의 기준은 당일 07:00 ~ 익일 06:59가 하루 데이터입니다.
- 한국어로 답변하세요."""

ANALYSIS_SYSTEM = """\
당신은 데이터 분석 전문가입니다. pandas DataFrame을 사용해 사용자 질문에 답하는 Python 코드를 작성하세요.

사용 가능한 변수:
- daily: 수불 일별 데이터 (컬럼: 사소구분, 구매item, date, recv_qty, use_qty, inv, is_actual)
- supplier_df: 공급사 집계 (컬럼: 공급사명, 구분, 사소구분, ITEM, recv_qty)
- gubun_summary: 구분별 당월/전월 입고량 요약 DataFrame
  (컬럼: 구분그룹, 당기입고량, 전기입고량, 증감률)

규칙:
- 결과를 반드시 result 변수에 저장하세요 (문자열 또는 DataFrame).
- 수치는 소수점 없이 천 단위 콤마로 포맷하세요.
- 기간의 기준은 당일 07:00 ~ 익일 06:59가 하루 데이터입니다.
- import는 pandas, numpy만 허용합니다.
- 한국어로 답변하는 코드를 작성하세요.

예시:
```python
actual = daily[daily["is_actual"]]
top = actual.groupby("구매item")["use_qty"].sum().sort_values(ascending=False)
result = "사용량 상위 품목:\\n" + "\\n".join(f"{i+1}. {k}: {v:,.0f}" for i,(k,v) in enumerate(top.items()))
```"""


# ── 안전한 pandas 코드 실행 ────────────────────────────────────

_ALLOWED_IMPORTS = {"pandas", "numpy", "pd", "np"}
_FORBIDDEN = ["import os", "import sys", "open(", "exec(", "eval(", "__"]


def _safe_exec(code: str, daily: pd.DataFrame, supplier_df: pd.DataFrame, gubun_summary: pd.DataFrame | None = None) -> str:
    """LLM이 생성한 pandas 코드를 제한된 환경에서 실행."""
    # 위험 패턴 차단
    for pat in _FORBIDDEN:
        if pat in code:
            return f"허용되지 않는 코드 패턴이 감지됐습니다: {pat}"

    # 코드 블록 추출 (```python ... ``` 형식 처리)
    match = re.search(r"```(?:python)?\n?(.*?)```", code, re.DOTALL)
    clean_code = match.group(1).strip() if match else code.strip()

    local_vars: dict = {
        "pd": pd, "pandas": pd,
        "daily": daily.copy(),
        "supplier_df": supplier_df.copy(),
        "gubun_summary": gubun_summary.copy() if gubun_summary is not None else pd.DataFrame(),
        "result": "결과 없음",
    }
    try:
        exec(clean_code, {"__builtins__": {}}, local_vars)  # noqa: S102
        result = local_vars.get("result", "result 변수가 정의되지 않았습니다.")
        if isinstance(result, pd.DataFrame):
            return result.to_string(index=False)
        return str(result)
    except Exception:
        return f"코드 실행 오류:\n{traceback.format_exc(limit=3)}"


# ── 헬퍼 ─────────────────────────────────────────────────────

def _get_last_human_message(state: ChatState) -> str:
    """state["messages"]에서 마지막 HumanMessage 내용을 반환."""
    return next(
        (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        "",
    )


# ── 그래프 빌더 ───────────────────────────────────────────────

def build_graph(daily: pd.DataFrame, supplier_df: pd.DataFrame, retriever, api_key: str, gubun_summary: pd.DataFrame | None = None):
    """LangGraph StateGraph 생성 및 컴파일."""
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1, api_key=api_key)

    # ── 노드 1: 라우터 (LLM 조건부 분기) ────────────────────────
    def router_node(state: ChatState) -> ChatState:
        last_human = _get_last_human_message(state)
        prompt = ROUTER_PROMPT.format(query=last_human)
        resp = llm.invoke([SystemMessage(content=prompt)])
        route = "analysis" if "analysis" in resp.content.lower() else "rag"
        return {**state, "route": route}

    # ── 노드 2: RAG 노드 ─────────────────────────────────────────
    def rag_node(state: ChatState) -> ChatState:
        last_human = _get_last_human_message(state)
        context = retriever.retrieve(last_human)

        ctx_text = "\n".join(f"- {c}" for c in context) if context else "관련 데이터 없음"
        messages = [
            SystemMessage(content=RAG_SYSTEM),
            *[m for m in state["messages"][:-1]],   # 이전 대화 이력
            HumanMessage(content=f"[컨텍스트]\n{ctx_text}\n\n[질문]\n{last_human}"),
        ]
        resp = llm.invoke(messages)
        return {
            **state,
            "context": context,
            "answer": resp.content,
            "messages": [AIMessage(content=resp.content)],
        }

    # ── 노드 3: 데이터 분석 노드 (CSV 에이전트 방식) ─────────────
    def analysis_node(state: ChatState) -> ChatState:
        last_human = _get_last_human_message(state)
        # LLM이 pandas 코드 생성
        code_prompt = [
            SystemMessage(content=ANALYSIS_SYSTEM),
            HumanMessage(content=f"질문: {last_human}\n\n분석 코드를 작성하세요."),
        ]
        code_resp = llm.invoke(code_prompt)
        generated_code = code_resp.content

        # 코드 실행
        exec_result = _safe_exec(generated_code, daily, supplier_df, gubun_summary)

        # 결과를 자연어로 정리
        summary_prompt = [
            SystemMessage(content="분석 결과를 한국어로 간결하게 정리하세요. 수치는 천 단위 콤마 포함."),
            HumanMessage(content=f"원래 질문: {last_human}\n\n분석 결과:\n{exec_result}"),
        ]
        summary = llm.invoke(summary_prompt)

        answer = summary.content
        detail = f"\n\n<분석 상세>\n{exec_result}"

        return {
            **state,
            "context": [f"[생성 코드]\n{generated_code}", f"[실행 결과]\n{exec_result}"],
            "answer": answer + detail,
            "messages": [AIMessage(content=answer)],
        }

    # ── 라우팅 함수 (조건부 엣지) ────────────────────────────────
    def route_decision(state: ChatState) -> Literal["rag_node", "analysis_node"]:
        return "analysis_node" if state.get("route") == "analysis" else "rag_node"

    # ── 그래프 조립 ───────────────────────────────────────────────
    builder = StateGraph(ChatState)
    builder.add_node("router_node", router_node)
    builder.add_node("rag_node", rag_node)
    builder.add_node("analysis_node", analysis_node)

    builder.set_entry_point("router_node")
    builder.add_conditional_edges("router_node", route_decision)
    builder.add_edge("rag_node", END)
    builder.add_edge("analysis_node", END)

    return builder.compile()
