# 섹션 요약 보고서 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 월간 추이·입고 상세 섹션 헤더 아래 `st.info()` 요약 박스와 선택적 AI 자연어 요약을 추가한다.

**Architecture:** `dashboard/app.py` 단독 수정. 헬퍼 함수 3개(`_monthly_summary`, `_receipt_summary`, `_ai_summary`)를 `render()` 함수 바깥에 정의하고, 각 섹션 헤더 직후에 호출한다. AI 요약은 API 키가 있을 때만 체크박스로 노출한다.

**Tech Stack:** Streamlit, pandas, openai (기존 의존성)

---

## 파일 변경 목록

| 파일 | 변경 유형 | 내용 |
|------|-----------|------|
| `dashboard/app.py` | 수정 | 헬퍼 함수 3개 추가, 두 섹션에 요약 박스 삽입 |

---

### Task 1: `_monthly_summary` 함수 구현

**Files:**
- Modify: `dashboard/app.py` — `render()` 함수 바로 위에 추가

- [ ] **Step 1: `_monthly_summary` 함수 작성**

`render()` 함수 정의 바로 위(line 33 앞)에 아래 함수를 삽입한다.

```python
def _monthly_summary(daily_chart: pd.DataFrame) -> str:
    """월간 추이 섹션용 요약 텍스트 생성."""
    if daily_chart.empty:
        return "데이터 없음"

    actual = daily_chart[daily_chart["is_actual"]]
    plan   = daily_chart[~daily_chart["is_actual"]]

    if actual.empty:
        return "실적 데이터 없음"

    recv_sum = actual["recv_qty"].sum()
    use_sum  = actual["use_qty"].sum()

    # 현재 재고: 사소×품목별 마지막 날짜 inv 합산
    current_inv = (
        actual.sort_values("date")
        .groupby(["사소구분", "구매item"])["inv"]
        .last()
        .sum()
    )

    parts = [
        f"실적 입고: {recv_sum:,.0f}톤",
        f"실적 사용: {use_sum:,.0f}톤",
        f"현재 재고: {current_inv:,.0f}톤",
    ]

    # 전월 대비 입고 증감
    actual2 = actual.copy()
    actual2["month"] = pd.to_datetime(actual2["date"]).dt.to_period("M")
    monthly = actual2.groupby("month")["recv_qty"].sum().sort_index()
    if len(monthly) >= 2:
        last_m, prev_m = monthly.iloc[-1], monthly.iloc[-2]
        if prev_m > 0:
            pct = (last_m - prev_m) / prev_m * 100
            sign = "+" if pct >= 0 else ""
            parts[0] = f"실적 입고: {recv_sum:,.0f}톤 (전월 대비 {sign}{pct:.1f}%)"

    # 달성률 (계획 데이터 있을 때만)
    if not plan.empty:
        plan_recv = plan["recv_qty"].sum()
        plan_use  = plan["use_qty"].sum()
        if plan_recv > 0:
            parts.append(f"입고 달성률: {recv_sum / plan_recv * 100:.1f}%")
        if plan_use > 0:
            parts.append(f"사용 달성률: {use_sum / plan_use * 100:.1f}%")

    return " · ".join(parts)
```

- [ ] **Step 2: 월간 추이 섹션에 요약 박스 삽입**

`app.py`에서 `daily_chart`가 정의된 직후(필터 UI 이후), `split_site = st.toggle(...)` 라인 바로 위에 아래 코드를 추가한다.  
(`daily_chart`는 필터 UI 이후에 정의되므로 `st.header` 직후가 아닌 이 위치에 삽입해야 한다.)

```python
    # ── 월간 추이 요약 ────────────────────────────────────────
    _m_summary = _monthly_summary(daily_chart)
    st.info(_m_summary)
    if api_key:
        if st.checkbox("AI 요약 (월간 추이)", key="ai_monthly"):
            with st.spinner("AI 요약 생성 중..."):
                st.caption(_ai_summary(_m_summary, api_key))
```

- [ ] **Step 3: 앱 실행 후 수동 확인**

```bash
streamlit run run.py
```

- 월간 추이 헤더 아래 파란 박스가 표시되는지 확인
- 실적 입고·사용·재고 수치가 콤마 포함 정수로 나오는지 확인
- 계획 데이터 있을 때 달성률 항목이 추가되는지 확인

- [ ] **Step 4: 커밋**

```bash
git add dashboard/app.py
git commit -m "feat: 월간 추이 섹션 요약 박스 추가"
```

---

### Task 2: `_receipt_summary` 함수 구현

**Files:**
- Modify: `dashboard/app.py` — `_monthly_summary` 함수 바로 아래에 추가

- [ ] **Step 1: `_receipt_summary` 함수 작성**

`_monthly_summary` 함수 바로 아래에 삽입한다.

```python
def _receipt_summary(filtered: pd.DataFrame, start_date, end_date) -> str:
    """입고 상세 섹션용 요약 텍스트 생성."""
    if filtered.empty:
        return ""

    total  = filtered["입하량(net)"].sum()
    count  = len(filtered)
    days   = max((end_date - start_date).days + 1, 1)
    avg    = total / days

    lines = [f"총 입고: {total:,.0f}톤 · 입고 건수: {count:,}건 · 일 평균: {avg:,.0f}톤"]

    # 구분별 합계 (MOU · 회수 · 유통)
    if "구분" in filtered.columns:
        gubun_qty = (
            filtered.groupby("구분")["입하량(net)"].sum()
            .reindex(["MOU", "회수", "유통"])
            .dropna()
        )
        if not gubun_qty.empty:
            gubun_parts = " · ".join(
                f"{g} {v:,.0f}톤" for g, v in gubun_qty.items()
            )
            lines.append(f"구분: {gubun_parts}")

    # 등급별 순위
    grade_qty = (
        filtered.groupby("등급")["입하량(net)"].sum()
        .sort_values(ascending=False)
    )
    grade_qty = grade_qty[grade_qty.index.notna()]   # NaN 등급 제외

    for rank, (grade, g_total) in enumerate(grade_qty.head(2).items(), start=1):
        # 해당 등급 내 공급사 순위
        sup_qty = (
            filtered[filtered["등급"] == grade]
            .groupby("공급사")["입하량(net)"].sum()
            .sort_values(ascending=False)
            .head(2)
        )
        sup_parts = " · ".join(
            f"{i+1}위 {name}({qty:,.0f}톤)"
            for i, (name, qty) in enumerate(sup_qty.items())
        )
        lines.append(
            f"등급 {rank}위: {grade}({g_total:,.0f}톤) — 공급사 {sup_parts}"
        )

    return "\n".join(lines)
```

- [ ] **Step 2: 입고 상세 섹션에 요약 박스 삽입**

`app.py` line 121 (`st.header("입고 상세")`) 직후, 필터 위젯 코드 이전에 아래 코드를 추가한다.  
단, `filtered`는 필터 적용 후 변수이므로 요약 박스는 **필터 위젯과 테이블 사이**에 삽입한다.  
기존 `if not filtered.empty:` 블록 바로 위에 삽입한다.

```python
    # ── 입고 상세 요약 ────────────────────────────────────────
    _r_summary = _receipt_summary(filtered, start_date, end_date)
    if _r_summary:
        st.info(_r_summary)
        if api_key:
            if st.checkbox("AI 요약 (입고 상세)", key="ai_receipt"):
                with st.spinner("AI 요약 생성 중..."):
                    st.caption(_ai_summary(_r_summary, api_key))
```

- [ ] **Step 3: 앱 실행 후 수동 확인**

```bash
streamlit run run.py
```

- 입고 상세 필터 적용 후 요약 박스가 갱신되는지 확인
- 등급 2개 이상일 때 두 줄 표시, 1개일 때 한 줄 표시 확인
- 공급사 1개뿐인 등급에서 1위만 나오는지 확인
- `filtered` 비어있을 때 요약 박스가 미표시되는지 확인

- [ ] **Step 4: 커밋**

```bash
git add dashboard/app.py
git commit -m "feat: 입고 상세 섹션 요약 박스 추가"
```

---

### Task 3: `_ai_summary` 함수 구현

**Files:**
- Modify: `dashboard/app.py` — `_receipt_summary` 바로 아래에 추가

- [ ] **Step 1: `_ai_summary` 함수 작성**

`_receipt_summary` 함수 바로 아래에 삽입한다.

```python
@st.cache_data(ttl=300)
def _ai_summary(summary_text: str, api_key: str) -> str:
    """요약 수치를 GPT에 전달해 2문장 자연어 요약 생성 (5분 캐시)."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    prompt = (
        "당신은 철강 공장 수불 현황을 요약하는 전문가입니다.\n"
        "아래 현황 수치를 바탕으로 2문장 이내 한국어로 핵심을 요약하세요.\n"
        "수치는 그대로 사용하고, 추측하지 마세요.\n\n"
        f"[현황]\n{summary_text}"
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=150,
        temperature=0.1,
        timeout=15,
    )
    if not resp.choices:
        return "AI 요약 생성 실패"
    return resp.choices[0].message.content
```

- [ ] **Step 2: AI 요약 동작 확인**

```bash
streamlit run run.py
```

- API 키 미입력 시 "AI 요약" 체크박스가 표시되지 않는지 확인
- API 키 입력 후 체크박스 ON → `st.caption()`으로 2문장 요약이 나오는지 확인
- 같은 데이터에 체크박스를 껐다 켜도 즉시 응답하는지 확인 (캐시 동작)

- [ ] **Step 3: 오류 방어 처리**

`_ai_summary` 호출부를 try-except로 감싼다. Task 1 Step 2와 Task 2 Step 2의 `st.caption(...)` 라인을 아래로 교체한다.

```python
                try:
                    st.caption(_ai_summary(_m_summary, api_key))
                except Exception as e:
                    st.caption(f"AI 요약 오류: {e}")
```

```python
                try:
                    st.caption(_ai_summary(_r_summary, api_key))
                except Exception as e:
                    st.caption(f"AI 요약 오류: {e}")
```

- [ ] **Step 4: 최종 커밋 및 푸시**

```bash
git add dashboard/app.py
git commit -m "feat: AI 요약 토글 추가 (gpt-4o-mini, 5분 캐시)"
git push origin master
```
