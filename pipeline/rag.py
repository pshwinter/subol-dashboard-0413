# pipeline/rag.py
"""
RAG 파이프라인: 수불 데이터 → 텍스트 청크 → 하이브리드 서치 → 생성

수업에서 배운 기법 적용:
  - 하이브리드 서치 : BM25 (sparse) + TF-IDF (dense) 앙상블
  - 리랭커 : Reciprocal Rank Fusion (RRF) 으로 두 순위 통합
  - RAG 챗봇 : 검색된 컨텍스트를 GPT에 주입
"""
from __future__ import annotations

import re
import numpy as np
import pandas as pd
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def _fmt(v: float) -> str:
    return f"{v:,.0f}"


# ── 청크 생성 ────────────────────────────────────────────────

def _last_inv(grp: pd.DataFrame) -> float:
    """사소×품목 그룹에서 마지막 날짜의 재고 합산 (올바른 재고 계산)."""
    return grp.sort_values("date").groupby(["사소구분", "구매item"])["inv"].last().sum()


def build_chunks(daily: pd.DataFrame, supplier_df: pd.DataFrame) -> list[str]:
    """수불 데이터를 검색 가능한 자연어 청크 리스트로 변환."""
    chunks: list[str] = []
    actual = daily[daily["is_actual"]]
    plan   = daily[~daily["is_actual"]]

    # ── 0. 데이터 메타 정보 ───────────────────────────────────
    if daily.empty or actual.empty:
        return ["데이터가 없습니다. 파일을 확인해 주세요."]

    all_dates  = sorted(daily["date"].unique())
    act_dates  = sorted(actual["date"].unique())
    sites      = sorted(daily["사소구분"].unique())
    items      = sorted(daily["구매item"].dropna().unique())

    chunks.append(
        f"데이터 기간: {all_dates[0]} ~ {all_dates[-1]}, "
        f"실적 기간: {act_dates[0]} ~ {act_dates[-1]}, "
        f"사업장: {', '.join(sites)}, 품목: {', '.join(items)}"
    )

    # ── 1. 전체 요약 ─────────────────────────────────────────
    total_inv = _last_inv(actual)
    chunks.append(
        f"전체 실적 요약: 입고량 합계 {_fmt(actual['recv_qty'].sum())}, "
        f"사용량 합계 {_fmt(actual['use_qty'].sum())}, "
        f"현재 재고 합계 {_fmt(total_inv)}"
    )
    if not plan.empty:
        chunks.append(
            f"전체 계획 요약: 예상 입고 {_fmt(plan['recv_qty'].sum())}, "
            f"예상 사용 {_fmt(plan['use_qty'].sum())}"
        )

    # ── 2. 실적 vs 계획 비교 ─────────────────────────────────
    if not plan.empty:
        recv_diff = actual["recv_qty"].sum() - plan["recv_qty"].sum()
        use_diff  = actual["use_qty"].sum()  - plan["use_qty"].sum()
        chunks.append(
            f"실적 vs 계획 비교: 입고 실적이 계획 대비 {_fmt(abs(recv_diff))} "
            f"{'초과' if recv_diff > 0 else '미달'}, "
            f"사용 실적이 계획 대비 {_fmt(abs(use_diff))} "
            f"{'초과' if use_diff > 0 else '미달'}"
        )
        # 사소별 실적 vs 계획
        for site in sites:
            a = actual[actual["사소구분"] == site]
            p = plan[plan["사소구분"] == site]
            if a.empty or p.empty:
                continue
            rd = a["recv_qty"].sum() - p["recv_qty"].sum()
            chunks.append(
                f"{site} 실적 vs 계획: 입고 {_fmt(abs(rd))} "
                f"{'초과' if rd > 0 else '미달'}"
            )

    # ── 3. 사소별 요약 ────────────────────────────────────────
    for site, grp in actual.groupby("사소구분"):
        inv = _last_inv(grp)
        chunks.append(
            f"{site} 실적: 입고 {_fmt(grp['recv_qty'].sum())}, "
            f"사용 {_fmt(grp['use_qty'].sum())}, 현재 재고 {_fmt(inv)}"
        )

    # ── 4. 품목별 요약 ────────────────────────────────────────
    for item, grp in actual.groupby("구매item"):
        inv = _last_inv(grp)
        chunks.append(
            f"품목 {item} 실적: 입고 {_fmt(grp['recv_qty'].sum())}, "
            f"사용 {_fmt(grp['use_qty'].sum())}, 현재 재고 {_fmt(inv)}"
        )

    # ── 5. 사소×품목 교차 ────────────────────────────────────
    for (site, item), grp in actual.groupby(["사소구분", "구매item"]):
        inv = grp.sort_values("date")["inv"].iloc[-1] if not grp.empty else 0
        chunks.append(
            f"{site} {item} 실적: 입고 {_fmt(grp['recv_qty'].sum())}, "
            f"사용 {_fmt(grp['use_qty'].sum())}, 현재 재고 {_fmt(inv)}"
        )
        # 계획도 추가
        p_grp = plan[(plan["사소구분"] == site) & (plan["구매item"] == item)]
        if not p_grp.empty:
            chunks.append(
                f"{site} {item} 계획: 예상 입고 {_fmt(p_grp['recv_qty'].sum())}, "
                f"예상 사용 {_fmt(p_grp['use_qty'].sum())}"
            )

    # ── 6. 월별 요약 ─────────────────────────────────────────
    actual2 = actual.copy()
    actual2["month"] = pd.to_datetime(actual2["date"]).dt.to_period("M")
    for month, grp in actual2.groupby("month"):
        inv = _last_inv(grp)
        chunks.append(
            f"{month} 실적: 입고 {_fmt(grp['recv_qty'].sum())}, "
            f"사용 {_fmt(grp['use_qty'].sum())}, 월말 재고 {_fmt(inv)}"
        )

    # ── 7. 일자별 실적 ────────────────────────────────────────
    # inv는 사소×품목별 마지막 값 합산으로 정확히 계산
    for date, grp in actual.groupby("date"):
        inv = _last_inv(grp)
        chunks.append(
            f"{date} 실적: 입고 {_fmt(grp['recv_qty'].sum())}, "
            f"사용 {_fmt(grp['use_qty'].sum())}, 재고 {_fmt(inv)}"
        )

    # ── 8. 공급사별 요약 ─────────────────────────────────────
    for (company, gubun), grp in supplier_df.groupby(["공급사명", "구분"]):
        sites_s = ", ".join(grp["사소구분"].unique())
        items_s = ", ".join(grp["ITEM"].unique())
        chunks.append(
            f"공급사 {company} (구분: {gubun}): "
            f"입고량 {_fmt(grp['recv_qty'].sum())}, "
            f"납품 사업장: {sites_s}, 취급 품목: {items_s}"
        )

    # ── 9. 공급사 순위 ────────────────────────────────────────
    top5 = (
        supplier_df.groupby("공급사명")["recv_qty"].sum()
        .sort_values(ascending=False).head(5)
    )
    rank_text = ", ".join(
        f"{i+1}위 {n}({_fmt(v)})"
        for i, (n, v) in enumerate(top5.items())
    )
    chunks.append(f"입고량 상위 공급사: {rank_text}")

    # ── 10. 재고 품목별 순위 ──────────────────────────────────
    item_inv = (
        actual.sort_values("date")
        .groupby(["사소구분", "구매item"])["inv"].last()
        .reset_index()
        .sort_values("inv", ascending=False)
    )
    for _, row in item_inv.iterrows():
        chunks.append(
            f"{row['사소구분']} {row['구매item']} 현재 재고: {_fmt(row['inv'])}"
        )

    return chunks


# ── 검색 엔진 ────────────────────────────────────────────────

# 수불 도메인 동의어 사전 (질의 확장용)
_SYNONYMS: dict[str, list[str]] = {
    "재고":   ["재고량", "남은 양", "잔량", "보유량", "현재 재고"],
    "입고":   ["입고량", "납품", "수령", "받은 양", "들어온 양"],
    "사용":   ["사용량", "소비", "출고", "쓴 양"],
    "계획":   ["예상", "예측", "목표"],
    "실적":   ["실제", "확정", "발생"],
    "포항소": ["포항"],
    "광양소": ["광양"],
}

def _expand_query(query: str) -> str:
    """동의어 확장으로 검색 커버리지 향상."""
    extra: list[str] = []
    for canonical, synonyms in _SYNONYMS.items():
        if any(s in query for s in synonyms) or canonical in query:
            extra.append(canonical)
            extra.extend(synonyms)
    return query + " " + " ".join(extra)


class RAGRetriever:
    """
    하이브리드 서치 리랭커.

    BM25 (sparse, 키워드 기반) + TF-IDF char n-gram (dense, 형태 기반)
    두 검색 결과를 Reciprocal Rank Fusion (RRF) 으로 통합 리랭킹.
    """

    _RRF_K = 60   # RRF 상수 (표준값)

    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks

        # ── BM25 (sparse) ──────────────────────────────────────
        tokenized = [c.split() for c in chunks]
        self.bm25 = BM25Okapi(tokenized)

        # ── TF-IDF char n-gram (dense-like) ────────────────────
        self.vectorizer = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(2, 4),
            min_df=1, sublinear_tf=True,
        )
        self.tfidf_matrix = self.vectorizer.fit_transform(chunks)

    def retrieve(self, query: str, top_k: int = 8) -> list[str]:
        """BM25 + TF-IDF → RRF 리랭킹 → 중복 제거 후 top_k 반환."""
        expanded = _expand_query(query)

        # BM25 순위
        bm25_scores = self.bm25.get_scores(expanded.split())
        bm25_order  = np.argsort(bm25_scores)[::-1]

        # TF-IDF 순위
        q_vec       = self.vectorizer.transform([expanded])
        tfidf_scores = cosine_similarity(q_vec, self.tfidf_matrix)[0]
        tfidf_order  = np.argsort(tfidf_scores)[::-1]

        # RRF 점수 계산 (두 순위 앙상블)
        rrf: dict[int, float] = {}
        for rank, idx in enumerate(bm25_order[: top_k * 3]):
            rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (self._RRF_K + rank + 1)
        for rank, idx in enumerate(tfidf_order[: top_k * 3]):
            rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (self._RRF_K + rank + 1)

        sorted_idx = sorted(rrf, key=rrf.__getitem__, reverse=True)

        # 중복 수치 청크 제거
        seen_nums: set[str] = set()
        results: list[str] = []
        for i in sorted_idx:
            if rrf[i] < 0.005:
                break
            chunk = self.chunks[i]
            nums  = frozenset(re.findall(r"[\d,]+", chunk))
            if i == 0 or not nums.issubset(seen_nums):
                results.append(chunk)
                seen_nums.update(nums)
            if len(results) >= top_k:
                break

        return results


# ── 생성 ─────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
당신은 철강 제조 공장의 수불(입고·사용·재고) 현황을 분석하는 전문 AI 어시스턴트입니다.

[도메인 용어 설명]
- 수불: 자재의 입고(들어옴)·사용(소비)·재고(남은 양)를 통합해 부르는 말
- 사소(사업소): 포항소(포항 제철소), 광양소(광양 제철소)
- 영업일 기준: 당일 07:00 ~ 익일 06:59가 하루 데이터
- 재고 = 기초재고 + 누적입고 - 누적사용 (품목별 누적 계산)
- 실적: 실제 발생한 데이터 / 계획: 예상·예측 데이터

[답변 원칙]
- 제공된 [데이터 컨텍스트]에 있는 수치만 사용하세요.
- 컨텍스트에 없는 내용은 "해당 데이터가 없습니다"라고 답하세요.
- 수치는 반드시 천 단위 콤마로 표시하세요 (예: 1,234,567).
- 실적과 계획을 혼동하지 마세요.
- 여러 사소가 있을 경우 사소별로 구분해 답변하세요.
- 한국어로 간결하게 답변하세요.
"""
