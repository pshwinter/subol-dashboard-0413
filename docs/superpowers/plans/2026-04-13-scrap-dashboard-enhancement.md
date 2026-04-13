# 철스크랩 대시보드 개선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 월별 현황 탭 분리, 입고 상세 기간 비교, 구분별 가격정책 신호 섹션을 기존 Streamlit 대시보드에 추가한다.

**Architecture:** 기존 `dashboard/app.py` + `pipeline/` 구조를 유지하며 기능을 추가한다. 순수 데이터 로직은 새 모듈 `pipeline/gubun_signal.py`에, 차트 함수는 `dashboard/charts.py`에, UI 연결은 `dashboard/app.py`에 추가한다.

**Tech Stack:** Python 3.11+, Streamlit, Plotly, pandas, pytest

---

## 파일 맵

| 파일 | 변경 유형 | 책임 |
|------|-----------|------|
| `pipeline/gubun_signal.py` | 신규 | 구분별 입고량 변화율·신호 계산 |
| `tests/test_gubun_signal.py` | 신규 | gubun_signal 단위 테스트 |
| `dashboard/charts.py` | 수정 | `make_multi_month_bar`, `make_comparison_bar`, `make_gubun_signal_bar` 추가 |
| `dashboard/app.py` | 수정 | 월별 현황 탭화, 입고 상세 비교 모드, 가격정책 신호 섹션, AI 챗봇 연동 |
| `CLAUDE.md` | 수정 | 섹션 구성 및 파일 목록 업데이트 |

---

## Task 1: `pipeline/gubun_signal.py` — 구분별 신호 계산 모듈

**Files:**
- Create: `pipeline/gubun_signal.py`
- Test: `tests/test_gubun_signal.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_gubun_signal.py`:

```python
import datetime
import pandas as pd
import pytest
from pipeline.gubun_signal import map_gubun_group, build_gubun_signal


# ── map_gubun_group 테스트 ────────────────────────────────────

def test_map_gubun_group_mou():
    assert map_gubun_group("생철MOU") == "MOU"
    assert map_gubun_group("경압MOU") == "MOU"

def test_map_gubun_group_dedicated():
    assert map_gubun_group("생압전용야드") == "전용야드"
    assert map_gubun_group("경압전용야드") == "전용야드"

def test_map_gubun_group_distribution():
    assert map_gubun_group("유통") == "유통"

def test_map_gubun_group_recovery():
    assert map_gubun_group("회수") == "회수"

def test_map_gubun_group_import():
    assert map_gubun_group("수입") == "수입"

def test_map_gubun_group_unknown():
    assert map_gubun_group("알수없음") == "알수없음"


# ── build_gubun_signal 테스트 ─────────────────────────────────

@pytest.fixture
def sample_receipt():
    """3월(current), 2월(prev) 2개월 데이터."""
    rows = []
    # 유통: 3월 1000t, 2월 800t  → +25%
    for d in pd.date_range("2026-03-01", "2026-03-10", freq="D"):
        rows.append({"날짜": d.date(), "구분": "유통", "구매item": "생철", "등급대분류": "경량", "입하량(net)": 100.0})
    for d in pd.date_range("2026-02-01", "2026-02-10", freq="D"):
        rows.append({"날짜": d.date(), "구분": "유통", "구매item": "생철", "등급대분류": "경량", "입하량(net)": 80.0})
    # 생철MOU: 3월 500t, 2월 600t → -16.7%
    for d in pd.date_range("2026-03-01", "2026-03-05", freq="D"):
        rows.append({"날짜": d.date(), "구분": "생철MOU", "구매item": "생철", "등급대분류": "경량", "입하량(net)": 100.0})
    for d in pd.date_range("2026-02-01", "2026-02-06", freq="D"):
        rows.append({"날짜": d.date(), "구분": "생철MOU", "구매item": "생철", "등급대분류": "경량", "입하량(net)": 100.0})
    return pd.DataFrame(rows)


def test_build_gubun_signal_groups(sample_receipt):
    result = build_gubun_signal(sample_receipt, compare="month", ref_date=datetime.date(2026, 3, 15))
    assert "유통" in result["by_group"]
    assert "MOU" in result["by_group"]


def test_build_gubun_signal_pct(sample_receipt):
    result = build_gubun_signal(sample_receipt, compare="month", ref_date=datetime.date(2026, 3, 15))
    유통 = result["by_group"]["유통"]
    assert 유통["current"] == pytest.approx(1000.0)
    assert 유통["prev"] == pytest.approx(800.0)
    assert 유통["pct"] == pytest.approx(25.0, abs=1.0)


def test_build_gubun_signal_mou_decrease(sample_receipt):
    result = build_gubun_signal(sample_receipt, compare="month", ref_date=datetime.date(2026, 3, 15))
    mou = result["by_group"]["MOU"]
    assert mou["pct"] < 0


def test_build_gubun_signal_red_signal():
    """유통·MOU·전용야드 모두 임계값 이상 감소 → red."""
    rows = []
    for gubun in ["유통", "생철MOU", "생압전용야드"]:
        for d in pd.date_range("2026-03-01", "2026-03-10", freq="D"):
            rows.append({"날짜": d.date(), "구분": gubun, "구매item": "A", "등급대분류": "X", "입하량(net)": 80.0})
        for d in pd.date_range("2026-02-01", "2026-02-10", freq="D"):
            rows.append({"날짜": d.date(), "구분": gubun, "구매item": "A", "등급대분류": "X", "입하량(net)": 100.0})
    df = pd.DataFrame(rows)
    result = build_gubun_signal(df, compare="month", ref_date=datetime.date(2026, 3, 15), threshold=5.0)
    assert result["signal"]["level"] == "red"


def test_build_gubun_signal_yellow_incentive():
    """유통 유지, MOU 감소 → yellow (인센티브 조정)."""
    rows = []
    # 유통 유지 (변화 없음)
    for d in pd.date_range("2026-03-01", "2026-03-10", freq="D"):
        rows.append({"날짜": d.date(), "구분": "유통", "구매item": "A", "등급대분류": "X", "입하량(net)": 100.0})
    for d in pd.date_range("2026-02-01", "2026-02-10", freq="D"):
        rows.append({"날짜": d.date(), "구분": "유통", "구매item": "A", "등급대분류": "X", "입하량(net)": 100.0})
    # MOU 감소
    for d in pd.date_range("2026-03-01", "2026-03-10", freq="D"):
        rows.append({"날짜": d.date(), "구분": "생철MOU", "구매item": "A", "등급대분류": "X", "입하량(net)": 80.0})
    for d in pd.date_range("2026-02-01", "2026-02-10", freq="D"):
        rows.append({"날짜": d.date(), "구분": "생철MOU", "구매item": "A", "등급대분류": "X", "입하량(net)": 100.0})
    df = pd.DataFrame(rows)
    result = build_gubun_signal(df, compare="month", ref_date=datetime.date(2026, 3, 15), threshold=5.0)
    assert result["signal"]["level"] == "yellow"
    assert "인센티브" in result["signal"]["message"]


def test_build_gubun_signal_green():
    """전 구분 증가 → green."""
    rows = []
    for gubun in ["유통", "생철MOU"]:
        for d in pd.date_range("2026-03-01", "2026-03-10", freq="D"):
            rows.append({"날짜": d.date(), "구분": gubun, "구매item": "A", "등급대분류": "X", "입하량(net)": 120.0})
        for d in pd.date_range("2026-02-01", "2026-02-10", freq="D"):
            rows.append({"날짜": d.date(), "구분": gubun, "구매item": "A", "등급대분류": "X", "입하량(net)": 100.0})
    df = pd.DataFrame(rows)
    result = build_gubun_signal(df, compare="month", ref_date=datetime.date(2026, 3, 15), threshold=5.0)
    assert result["signal"]["level"] == "green"


def test_build_gubun_signal_by_item_group(sample_receipt):
    result = build_gubun_signal(sample_receipt, compare="month", ref_date=datetime.date(2026, 3, 15))
    assert len(result["by_item_group"]) > 0
    keys = list(result["by_item_group"].keys())
    assert all(isinstance(k, tuple) and len(k) == 2 for k in keys)


def test_build_gubun_signal_by_grade_group(sample_receipt):
    result = build_gubun_signal(sample_receipt, compare="month", ref_date=datetime.date(2026, 3, 15))
    assert len(result["by_grade_group"]) > 0


def test_build_gubun_signal_site_filter(sample_receipt):
    """site 필터 적용 시 해당 사소구분 데이터만 사용."""
    df = sample_receipt.copy()
    df["사소구분"] = "포항소"
    result_all = build_gubun_signal(df, compare="month", ref_date=datetime.date(2026, 3, 15))
    result_pohang = build_gubun_signal(df, compare="month", ref_date=datetime.date(2026, 3, 15), site="포항소")
    assert result_all["by_group"] == result_pohang["by_group"]


def test_build_gubun_signal_week(sample_receipt):
    """compare='week' 모드 — 오류 없이 실행됨."""
    result = build_gubun_signal(sample_receipt, compare="week", ref_date=datetime.date(2026, 3, 15))
    assert "by_group" in result
    assert "signal" in result
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd C:\Users\user\Desktop\260331_project\0403_new
python -m pytest tests/test_gubun_signal.py -v 2>&1 | head -20
```
예상: `ModuleNotFoundError: No module named 'pipeline.gubun_signal'`

- [ ] **Step 3: `pipeline/gubun_signal.py` 구현**

```python
# pipeline/gubun_signal.py
"""구분별 입고량 변화율 및 가격정책 신호 계산."""
from __future__ import annotations

import datetime
from collections import defaultdict

import pandas as pd


# ── 구분 그룹 매핑 ──────────────────────────────────────────────

_SUFFIX_ORDER = ["전용야드", "MOU", "회수", "수입", "유통"]


def map_gubun_group(gubun_val: str) -> str:
    """구분값을 상위 그룹명으로 매핑.

    매핑 순서: 전용야드 → MOU → 회수 → 수입 → 유통 → 원래값
    """
    for suffix in _SUFFIX_ORDER:
        if gubun_val.endswith(suffix):
            return suffix
    return gubun_val


# ── 기간 계산 ───────────────────────────────────────────────────

def _month_ranges(ref_date: datetime.date) -> tuple[datetime.date, datetime.date, datetime.date, datetime.date]:
    """ref_date 기준 당월 1일~ref_date, 전월 1일~말일 반환."""
    cur_start = ref_date.replace(day=1)
    cur_end = ref_date
    # 전월 말일
    prev_end = cur_start - datetime.timedelta(days=1)
    prev_start = prev_end.replace(day=1)
    return cur_start, cur_end, prev_start, prev_end


def _week_ranges(ref_date: datetime.date) -> tuple[datetime.date, datetime.date, datetime.date, datetime.date]:
    """ref_date 기준 이번 주(일~토) 시작일~ref_date, 전주 일~토 반환."""
    # 이번 주 일요일
    cur_start = ref_date - datetime.timedelta(days=(ref_date.weekday() + 1) % 7)
    cur_end = ref_date
    prev_end = cur_start - datetime.timedelta(days=1)
    prev_start = prev_end - datetime.timedelta(days=(prev_end.weekday() + 1) % 7)
    return cur_start, cur_end, prev_start, prev_end


# ── 집계 헬퍼 ──────────────────────────────────────────────────

def _agg_by(df: pd.DataFrame, group_cols: list[str]) -> pd.Series:
    """group_cols 기준 입하량(net) 합산."""
    if df.empty:
        return pd.Series(dtype=float)
    return df.groupby(group_cols)["입하량(net)"].sum()


def _pct_change(current: float, prev: float) -> float:
    """전기 대비 증감률(%). prev=0이면 0 반환."""
    if prev <= 0:
        return 0.0
    return (current - prev) / prev * 100.0


# ── 신호 감지 ──────────────────────────────────────────────────

_POLICY_GROUPS = {"유통", "MOU", "전용야드"}   # 가격 정책 영향 구분


def _detect_signal(group_result: dict, threshold: float) -> dict:
    """group_result 기반 정책 신호 감지.

    group_result: {그룹명: {"current": float, "prev": float, "pct": float}}
    threshold: 감소로 판정할 % 기준 (양수, e.g. 5.0 → -5% 이하를 감소로 판정)
    """
    present = {g for g in _POLICY_GROUPS if group_result.get(g, {}).get("prev", 0) > 0}
    if not present:
        return {"level": "gray", "message": "데이터 없음"}

    decreasing = {
        g for g in present
        if group_result[g]["pct"] <= -threshold
    }
    increasing = {
        g for g in present
        if group_result[g]["pct"] >= threshold
    }

    distribution_down = "유통" in decreasing
    incentive_down = bool(decreasing & {"MOU", "전용야드"})
    all_down = present.issubset(decreasing | {"회수", "수입"})
    all_up = present.issubset(increasing | {"회수", "수입"})

    if all_up:
        return {"level": "green", "message": "현행 가격 경쟁력 양호 — 전 구분 입고 증가"}
    if all_down:
        return {"level": "red", "message": "기본가 조정 검토 — 유통·MOU·전용야드 모두 감소"}
    if incentive_down and not distribution_down:
        return {"level": "yellow", "message": "인센티브 조정 검토 — MOU/전용야드 감소, 유통 유지"}
    if distribution_down and not incentive_down:
        return {"level": "yellow", "message": "기본가 소폭 조정 검토 — 유통 감소, MOU/전용야드 유지"}
    if decreasing:
        return {"level": "yellow", "message": f"일부 구분 감소 — {', '.join(sorted(decreasing))}"}
    return {"level": "gray", "message": "유의미한 변화 없음"}


# ── 메인 함수 ──────────────────────────────────────────────────

def build_gubun_signal(
    receipt_df: pd.DataFrame,
    compare: str = "month",
    ref_date: datetime.date | None = None,
    threshold: float = 5.0,
    site: str | None = None,
) -> dict:
    """구분별 입고량 변화율 및 가격정책 신호를 계산한다.

    Args:
        receipt_df: _preprocess_receipt() 결과 DataFrame.
                    필수 컬럼: 날짜, 구분, 구매item, 등급대분류, 입하량(net)
                    선택 컬럼: 사소구분 (site 필터용)
        compare: "month" (전월 대비) | "week" (전주 대비)
        ref_date: 기준일. None이면 receipt_df 최신 날짜 사용.
        threshold: 감소 판정 임계값(%). 기본 5.0 → -5% 이하를 감소로 판정.
        site: 사소구분 필터. None이면 전체.

    Returns:
        {
            "by_group": {그룹명: {"current": float, "prev": float, "pct": float}},
            "by_item_group": {(품목, 그룹): {"current": float, "prev": float, "pct": float}},
            "by_grade_group": {(등급대분류, 그룹): {"current": float, "prev": float, "pct": float}},
            "signal": {"level": str, "message": str},
            "cur_start": date, "cur_end": date, "prev_start": date, "prev_end": date,
        }
    """
    df = receipt_df.copy()

    # 날짜 컬럼 정규화
    if not pd.api.types.is_object_dtype(df["날짜"]):
        df["날짜"] = pd.to_datetime(df["날짜"]).dt.date

    if ref_date is None:
        ref_date = df["날짜"].max()

    # 사소구분 필터
    if site and "사소구분" in df.columns:
        df = df[df["사소구분"] == site]

    # 기간 계산
    if compare == "week":
        cur_start, cur_end, prev_start, prev_end = _week_ranges(ref_date)
    else:
        cur_start, cur_end, prev_start, prev_end = _month_ranges(ref_date)

    cur_df  = df[(df["날짜"] >= cur_start)  & (df["날짜"] <= cur_end)]
    prev_df = df[(df["날짜"] >= prev_start) & (df["날짜"] <= prev_end)]

    # 구분 → 그룹 매핑 컬럼 추가
    cur_df  = cur_df.copy()
    prev_df = prev_df.copy()
    cur_df["_group"]  = cur_df["구분"].apply(map_gubun_group)
    prev_df["_group"] = prev_df["구분"].apply(map_gubun_group)

    def _build_result(cur_series: pd.Series, prev_series: pd.Series) -> dict:
        all_keys = set(cur_series.index) | set(prev_series.index)
        out = {}
        for k in all_keys:
            c = float(cur_series.get(k, 0.0))
            p = float(prev_series.get(k, 0.0))
            out[k] = {"current": c, "prev": p, "pct": _pct_change(c, p)}
        return out

    # by_group
    cur_grp  = _agg_by(cur_df,  ["_group"])
    prev_grp = _agg_by(prev_df, ["_group"])
    by_group = _build_result(cur_grp, prev_grp)

    # by_item_group
    cur_ig  = _agg_by(cur_df,  ["구매item", "_group"])
    prev_ig = _agg_by(prev_df, ["구매item", "_group"])
    by_item_group = _build_result(cur_ig, prev_ig)

    # by_grade_group
    cur_gg  = _agg_by(cur_df,  ["등급대분류", "_group"])
    prev_gg = _agg_by(prev_df, ["등급대분류", "_group"])
    by_grade_group = _build_result(cur_gg, prev_gg)

    signal = _detect_signal(by_group, threshold)

    return {
        "by_group": by_group,
        "by_item_group": by_item_group,
        "by_grade_group": by_grade_group,
        "signal": signal,
        "cur_start": cur_start,
        "cur_end": cur_end,
        "prev_start": prev_start,
        "prev_end": prev_end,
    }
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
cd C:\Users\user\Desktop\260331_project\0403_new
python -m pytest tests/test_gubun_signal.py -v
```
예상: 모든 테스트 PASS

- [ ] **Step 5: 커밋**

```bash
git add pipeline/gubun_signal.py tests/test_gubun_signal.py
git commit -m "feat: add gubun_signal pipeline module for price policy signal detection"
```

---

## Task 2: `dashboard/charts.py` — 신규 차트 함수 3개 추가

**Files:**
- Modify: `dashboard/charts.py`

- [ ] **Step 1: `make_multi_month_bar` 추가**

`dashboard/charts.py` 파일 끝에 아래 함수를 추가한다.

```python
def make_multi_month_bar(
    daily: pd.DataFrame,
    months: list,            # pd.Period 리스트
    metric: str = "입고",    # "입고" | "사용" | "재고"
) -> go.Figure:
    """멀티 월 나란히 비교 그룹 막대 차트.

    months: pd.Period 리스트 (예: [Period('2026-01'), Period('2026-02')])
    metric: "입고" → recv_qty 합산, "사용" → use_qty 합산, "재고" → 마지막 inv
    """
    if not months or daily.empty:
        return go.Figure().update_layout(title="데이터 없음")

    col_map = {"입고": "recv_qty", "사용": "use_qty", "재고": "inv"}
    col = col_map.get(metric, "recv_qty")

    daily = daily.copy()
    daily["month"] = pd.to_datetime(daily["date"]).dt.to_period("M")

    sites = sorted(daily["사소구분"].dropna().unique())
    site_colors = {
        "포항소": ACTUAL_COLOR_RECV,
        "광양소": ACTUAL_COLOR_USE,
    }

    fig = go.Figure()

    month_labels = [str(m) for m in months]

    for site in sites:
        site_df = daily[daily["사소구분"] == site]
        values = []
        for m in months:
            m_df = site_df[site_df["month"] == m]
            if metric == "재고":
                # 재고: 해당 월 마지막 날 inv 합산
                val = float(
                    m_df.sort_values("date")
                    .groupby(["사소구분", "구매item"])["inv"].last().sum()
                ) if not m_df.empty else 0.0
            else:
                val = float(m_df[col].sum()) if not m_df.empty else 0.0
            values.append(val)

        fig.add_trace(go.Bar(
            name=site,
            x=month_labels,
            y=values,
            marker_color=site_colors.get(site, BRAND_COLORS[len(fig.data) % len(BRAND_COLORS)]),
            hovertemplate="%{x}<br>%{y:,.0f}<extra></extra>",
        ))

    fig.update_layout(
        barmode="group",
        xaxis_title="월",
        yaxis=dict(title=f"{metric}량", tickformat=",.0f", gridcolor="#E2E8F0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        plot_bgcolor="#FAFAFA",
        paper_bgcolor="#FFFFFF",
    )
    return fig
```

- [ ] **Step 2: `make_comparison_bar` 추가**

```python
def make_comparison_bar(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    label_a: str = "A기간",
    label_b: str = "B기간",
    group_col: str = "구분",     # X축 기준 컬럼
) -> go.Figure:
    """A기간 vs B기간 나란히 비교 막대 차트.

    df_a, df_b: 각 기간 filtered receipt DataFrame.
                필수 컬럼: group_col, 입하량(net)
    label_a, label_b: 범례/툴팁에 표시할 기간 이름
    group_col: X축으로 사용할 컬럼 ("구분" | "구매item" | "등급대분류" | "공급사")
    """
    def _agg(df: pd.DataFrame) -> pd.Series:
        if df.empty or group_col not in df.columns:
            return pd.Series(dtype=float)
        return df.groupby(group_col)["입하량(net)"].sum().sort_values(ascending=False)

    agg_a = _agg(df_a)
    agg_b = _agg(df_b)
    all_cats = list(dict.fromkeys(list(agg_a.index) + list(agg_b.index)))  # A 순서 유지

    vals_a = [float(agg_a.get(c, 0.0)) for c in all_cats]
    vals_b = [float(agg_b.get(c, 0.0)) for c in all_cats]

    # 증감률 레이블 계산
    pct_texts = []
    for a, b in zip(vals_a, vals_b):
        if b > 0:
            pct = (a - b) / b * 100
            pct_texts.append(f"{'+' if pct >= 0 else ''}{pct:.0f}%")
        else:
            pct_texts.append("")

    fig = go.Figure()

    fig.add_trace(go.Bar(
        name=label_a,
        x=all_cats,
        y=vals_a,
        marker_color=ACTUAL_COLOR_RECV,
        hovertemplate="%{x}<br>%{y:,.0f}<extra></extra>",
        text=pct_texts,
        textposition="outside",
        textfont=dict(size=11),
    ))
    fig.add_trace(go.Bar(
        name=label_b,
        x=all_cats,
        y=vals_b,
        marker_color="#94A3B8",
        hovertemplate="%{x}<br>%{y:,.0f}<extra></extra>",
    ))

    # 증감률 색상: 텍스트 색상은 값 기준으로 Plotly에서 직접 지정 불가,
    # 대신 음수(감소)는 빨강, 양수(증가)는 초록 annotation 추가
    for i, (cat, pct_txt) in enumerate(zip(all_cats, pct_texts)):
        if not pct_txt:
            continue
        color = "#16a34a" if pct_txt.startswith("+") else "#dc2626"
        fig.update_traces(
            selector=dict(name=label_a),
            textfont_color=color,
        )

    fig.update_layout(
        barmode="group",
        xaxis_title=group_col,
        yaxis=dict(title="입고량", tickformat=",.0f", gridcolor="#E2E8F0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        plot_bgcolor="#FAFAFA",
        paper_bgcolor="#FFFFFF",
    )
    return fig
```

- [ ] **Step 3: `make_gubun_signal_bar` 추가**

```python
def make_gubun_signal_bar(
    by_result: dict,
    label_current: str = "당기",
    label_prev: str = "전기",
    exclude_groups: list | None = None,
) -> go.Figure:
    """구분별 당기/전기 입고량 비교 그룹 막대 차트.

    by_result: build_gubun_signal()의 by_group / by_item_group / by_grade_group 값.
               {key: {"current": float, "prev": float, "pct": float}}
    exclude_groups: 차트에서 제외할 그룹 목록 (예: ["회수", "수입"])
    """
    exclude = set(exclude_groups or [])

    # 단순 문자열 키(by_group)와 튜플 키(by_item_group, by_grade_group) 모두 처리
    def _label(k) -> str:
        return " × ".join(k) if isinstance(k, tuple) else k

    items = [
        (k, v) for k, v in by_result.items()
        if _label(k).split(" × ")[-1] not in exclude
    ]
    # 당기 내림차순 정렬
    items.sort(key=lambda x: x[1]["current"], reverse=True)

    if not items:
        return go.Figure().update_layout(title="데이터 없음")

    labels = [_label(k) for k, _ in items]
    vals_cur  = [v["current"] for _, v in items]
    vals_prev = [v["prev"] for _, v in items]
    pct_vals  = [v["pct"] for _, v in items]

    pct_texts = [
        f"{'+' if p >= 0 else ''}{p:.1f}%"
        for p in pct_vals
    ]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name=label_current,
        x=labels, y=vals_cur,
        marker_color=ACTUAL_COLOR_RECV,
        hovertemplate="%{x}<br>%{y:,.0f}<extra></extra>",
        text=pct_texts,
        textposition="outside",
    ))
    fig.add_trace(go.Bar(
        name=label_prev,
        x=labels, y=vals_prev,
        marker_color="#94A3B8",
        hovertemplate="%{x}<br>%{y:,.0f}<extra></extra>",
    ))

    fig.update_layout(
        barmode="group",
        xaxis=dict(tickangle=-30, automargin=True),
        yaxis=dict(title="입고량", tickformat=",.0f", gridcolor="#E2E8F0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        plot_bgcolor="#FAFAFA",
        paper_bgcolor="#FFFFFF",
    )
    return fig
```

- [ ] **Step 4: 임포트 확인 (차트 함수 연기 없이 로드 되는지)**

```bash
cd C:\Users\user\Desktop\260331_project\0403_new
python -c "from dashboard.charts import make_multi_month_bar, make_comparison_bar, make_gubun_signal_bar; print('OK')"
```
예상: `OK`

- [ ] **Step 5: 커밋**

```bash
git add dashboard/charts.py
git commit -m "feat: add make_multi_month_bar, make_comparison_bar, make_gubun_signal_bar to charts"
```

---

## Task 3: `app.py` — 월별 현황 섹션 탭화

**Files:**
- Modify: `dashboard/app.py` (월별 현황 섹션, 약 line 881~989)

변경 전 구조: 단일 필터 + 단일 차트
변경 후 구조: `st.tabs(["단일 월 심층 비교", "멀티 월 비교"])` 로 분리

- [ ] **Step 1: import 추가 확인**

`app.py` 상단 import 블록에 아래 줄이 없으면 추가한다.

```python
from dashboard.charts import make_monthly_chart, make_receipt_detail_bar, make_multi_month_bar, make_comparison_bar, make_gubun_signal_bar
```

- [ ] **Step 2: 월별 현황 섹션을 탭으로 교체**

`app.py`의 `# ── 섹션 1: 월간 추이` 블록 전체(약 line 881~989)를 아래로 교체한다.

```python
    # ── 섹션 1: 월간 추이 ──────────────────────────────────────
    st.header("월간 추이")
    st.caption("사소·품목별 입고·사용·재고 월간 집계 (실적/계획/전월/전년동월 비교)")

    _tab_monthly_a, _tab_monthly_b = st.tabs(["단일 월 심층 비교", "멀티 월 비교"])

    # ── 탭A: 단일 월 심층 비교 ──────────────────────────────────
    with _tab_monthly_a:
        # 월 선택 (기본값: 실적 최신 월)
        _all_months = sorted(pd.to_datetime(daily["date"]).dt.to_period("M").unique().tolist())
        _month_labels = [str(m) for m in _all_months]
        _act_mask_all = daily["is_actual"].fillna(False).astype(bool)
        _default_month = (
            pd.to_datetime(daily[_act_mask_all]["date"]).dt.to_period("M").max()
            if _act_mask_all.any() else _all_months[-1]
        )
        _default_idx = _month_labels.index(str(_default_month))

        mf0, mf1, mf2, mf3 = st.columns([1, 1, 1, 2])
        with mf0:
            selected_month_str = st.selectbox(
                "월 선택", _month_labels, index=_default_idx, key="monthly_month"
            )
            selected_month = pd.Period(selected_month_str, freq="M")
        with mf1:
            show_types = st.multiselect(
                "실적/계획", ["실적", "계획"],
                default=["실적", "계획"], key="monthly_show_types",
            )
        with mf2:
            show_metrics = st.multiselect(
                "수불 구분", ["입고", "사용", "재고"],
                default=["입고", "사용", "재고"], key="monthly_show_metrics",
            )
        with mf3:
            item_options = ["총계"] + sorted(daily["구매item"].dropna().unique().tolist())
            selected_items = st.multiselect(
                "ITEM 필터", item_options, default=["총계"], key="monthly_items",
            )

        # 총계 여부와 개별 품목 리스트 분리
        total_prominent = not selected_items or "총계" in selected_items
        item_list = [x for x in (selected_items or []) if x != "총계"]

        # 품목 필터 (전 기간 — 전월比 계산용)
        if item_list and not total_prominent:
            daily_item = daily[daily["구매item"].isin(item_list)]
        else:
            daily_item = daily

        # 선택 월로 필터
        daily_chart = daily_item[
            pd.to_datetime(daily_item["date"]).dt.to_period("M") == selected_month
        ]

        # 품목 필터를 원본 예상 데이터에도 적용
        if item_list and not total_prominent:
            exp_recv_item = exp_recv_all[exp_recv_all["구매item"].isin(item_list)]
            exp_use_item  = exp_use_all[exp_use_all["구매item"].isin(item_list)]
        else:
            exp_recv_item = exp_recv_all
            exp_use_item  = exp_use_all

        # 전년동월 데이터 준비 (선택 월 - 12개월)
        prev_year_month = selected_month - 12
        daily_prev_year = daily_item[
            pd.to_datetime(daily_item["date"]).dt.to_period("M") == prev_year_month
        ] if not daily_item.empty else pd.DataFrame()

        # 월간 추이 요약
        _m_summary = _monthly_summary(
            daily_item, target_month=selected_month,
            exp_recv=exp_recv_item, exp_use=exp_use_item,
        )
        _render_summary_box(_m_summary)
        if api_key:
            if st.checkbox("AI 요약 (월간 추이)", key="ai_monthly"):
                with st.spinner("AI 요약 생성 중..."):
                    try:
                        st.caption(_ai_summary(_m_summary, api_key))
                    except Exception as e:
                        st.caption(f"AI 요약 오류: {e}")

        split_site = st.toggle("사소 구분", value=False, key="monthly_split_site")

        chart_kwargs = dict(
            show_metrics=show_metrics,
            show_types=show_types,
            item_list=item_list,
            total_prominent=total_prominent,
        )

        if split_site:
            col_ph, col_gy = st.columns(2)
            for col, site in [(col_ph, "포항소"), (col_gy, "광양소")]:
                with col:
                    st.subheader(site)
                    sub = daily_chart[daily_chart["사소구분"] == site]
                    st.plotly_chart(make_monthly_chart(sub, **chart_kwargs), use_container_width=True)
        else:
            st.plotly_chart(make_monthly_chart(daily_chart, **chart_kwargs), use_container_width=True)

        # 하단 테이블
        tbl = (
            daily_chart.groupby(["date", "is_actual"])
            .agg(recv_qty=("recv_qty", "sum"), use_qty=("use_qty", "sum"), inv=("inv", "sum"))
            .reset_index()
        )
        tbl.columns = ["날짜", "실적여부", "입고량", "사용량", "재고"]
        tbl["실적여부"] = tbl["실적여부"].map({True: "실적", False: "계획"})
        st.dataframe(
            tbl,
            use_container_width=True,
            hide_index=True,
            column_config={
                "입고량": st.column_config.NumberColumn(format="%,.0f"),
                "사용량": st.column_config.NumberColumn(format="%,.0f"),
                "재고": st.column_config.NumberColumn(format="%,.0f"),
            },
        )

    # ── 탭B: 멀티 월 비교 ───────────────────────────────────────
    with _tab_monthly_b:
        _all_months_b = sorted(pd.to_datetime(daily["date"]).dt.to_period("M").unique().tolist())
        _month_labels_b = [str(m) for m in _all_months_b]

        tb_c1, tb_c2 = st.columns([2, 1])
        with tb_c1:
            selected_months_b = st.multiselect(
                "비교할 월 선택 (최대 12개월)",
                _month_labels_b,
                default=_month_labels_b[-min(3, len(_month_labels_b)):],
                key="multi_month_select",
            )
        with tb_c2:
            metric_b = st.radio(
                "수불 항목", ["입고", "사용", "재고"],
                horizontal=True, key="multi_month_metric",
            )

        if selected_months_b:
            months_b = [pd.Period(m, freq="M") for m in selected_months_b]
            st.plotly_chart(
                make_multi_month_bar(daily, months_b, metric=metric_b),
                use_container_width=True,
            )
        else:
            st.info("비교할 월을 1개 이상 선택하세요.")
```

- [ ] **Step 3: `_LOAD_VERSION` 업데이트**

`app.py` 상단의 `_LOAD_VERSION = "v9"` 를 `"v10"` 으로 변경한다.

- [ ] **Step 4: 앱 실행 확인**

```bash
cd C:\Users\user\Desktop\260331_project\0403_new
python -m streamlit run dashboard/app.py --server.port 8502
```
브라우저에서 http://localhost:8502 접속 → "월간 추이" 섹션에 탭 2개 확인

- [ ] **Step 5: 커밋**

```bash
git add dashboard/app.py
git commit -m "feat: split monthly section into tab A (single month) and tab B (multi-month comparison)"
```

---

## Task 4: `app.py` — 입고 상세 기간 비교 모드

**Files:**
- Modify: `dashboard/app.py` (입고 상세 섹션, 약 line 990~1100)

- [ ] **Step 1: 입고 상세 섹션 시작 부분에 모드 토글 추가**

`# ── 섹션 2: 입고 상세 ──────────────────────────────────────` 직후,
`receipt = _preprocess_receipt(...)` 바로 앞에 아래를 삽입한다.

```python
    _compare_mode = st.toggle("기간 비교 모드", value=False, key="receipt_compare_mode")
```

- [ ] **Step 2: 날짜 필터 블록 교체**

기존 `fc1, fc2, fc3 = st.columns(...)` ~ `end_date = ...` 블록을 아래로 교체한다.

```python
    receipt = _preprocess_receipt(receipt_raw, grade_lookup, supplier_gubuns, gubun_grades, region_ref)

    dates = sorted(receipt["날짜"].unique())
    if dates:
        min_date, max_date = dates[0], dates[-1]
    else:
        min_date = max_date = datetime.date.today()

    _sel_start = max(selected_month.start_time.date(), min_date)
    _sel_end   = min(selected_month.end_time.date(),   max_date)

    if _compare_mode:
        # ── 기간 비교 모드 ─────────────────────────────────────
        st.caption("빠른 선택 또는 직접 설정으로 두 기간을 비교합니다.")

        # 빠른 선택 버튼
        _qc1, _qc2, _qc3, _ = st.columns([1, 1, 1, 3])
        _quick = None
        with _qc1:
            if st.button("전월 비교", key="quick_prev_month"):
                _quick = "prev_month"
        with _qc2:
            if st.button("전분기 비교", key="quick_prev_quarter"):
                _quick = "prev_quarter"
        with _qc3:
            if st.button("전년동기 비교", key="quick_prev_year"):
                _quick = "prev_year"

        # 빠른 선택 → session_state에 날짜 세팅
        if _quick == "prev_month":
            _a_end   = _sel_end
            _a_start = _sel_start
            _b_end   = (_a_start - datetime.timedelta(days=1))
            _b_start = _b_end.replace(day=1)
            st.session_state["cmp_a_start"] = _a_start
            st.session_state["cmp_a_end"]   = _a_end
            st.session_state["cmp_b_start"] = _b_start
            st.session_state["cmp_b_end"]   = _b_end
        elif _quick == "prev_quarter":
            _a_end   = _sel_end
            _a_start = _sel_start
            _b_start = _a_start - datetime.timedelta(days=90)
            _b_end   = _a_end   - datetime.timedelta(days=90)
            st.session_state["cmp_a_start"] = _a_start
            st.session_state["cmp_a_end"]   = _a_end
            st.session_state["cmp_b_start"] = max(_b_start, min_date)
            st.session_state["cmp_b_end"]   = max(_b_end,   min_date)
        elif _quick == "prev_year":
            _a_end   = _sel_end
            _a_start = _sel_start
            _b_start = _a_start.replace(year=_a_start.year - 1)
            _b_end   = _a_end.replace(year=_a_end.year - 1)
            st.session_state["cmp_a_start"] = _a_start
            st.session_state["cmp_a_end"]   = _a_end
            st.session_state["cmp_b_start"] = max(_b_start, min_date)
            st.session_state["cmp_b_end"]   = max(_b_end,   min_date)

        _da_c1, _da_c2, _db_c1, _db_c2 = st.columns(4)
        with _da_c1:
            cmp_a_start = st.date_input(
                "A기간 시작", key="cmp_a_start",
                value=st.session_state.get("cmp_a_start", _sel_start),
                min_value=min_date, max_value=max_date,
            )
        with _da_c2:
            cmp_a_end = st.date_input(
                "A기간 종료", key="cmp_a_end",
                value=st.session_state.get("cmp_a_end", _sel_end),
                min_value=min_date, max_value=max_date,
            )
        with _db_c1:
            _b_default_start = st.session_state.get(
                "cmp_b_start",
                max((_sel_start - datetime.timedelta(days=31)).replace(day=1), min_date),
            )
            cmp_b_start = st.date_input(
                "B기간 시작", key="cmp_b_start",
                value=_b_default_start,
                min_value=min_date, max_value=max_date,
            )
        with _db_c2:
            _b_default_end = st.session_state.get(
                "cmp_b_end",
                max(_sel_start - datetime.timedelta(days=1), min_date),
            )
            cmp_b_end = st.date_input(
                "B기간 종료", key="cmp_b_end",
                value=_b_default_end,
                min_value=min_date, max_value=max_date,
            )

        start_date = cmp_a_start
        end_date   = cmp_a_end

    else:
        # ── 단일 기간 모드 (기존) ──────────────────────────────
        fc1, fc2, fc3 = st.columns([1, 1, 1])
        with fc1:
            start_date = st.date_input("시작일", value=_sel_start, min_value=min_date, max_value=max_date)
        with fc2:
            end_date = st.date_input("종료일", value=_sel_end, min_value=min_date, max_value=max_date)
        with fc3:
            site_opts2 = ["전체"] + sorted(receipt["사소구분"].dropna().unique().tolist())
            f_site = st.selectbox("사소 필터", site_opts2, key="site2")
```

- [ ] **Step 3: 사소 필터 (비교 모드 전용)**

기존 `fc3`의 사소 필터(`f_site = st.selectbox("사소 필터" ...)`)를 비교 모드에도 추가한다.  
비교 모드 날짜 컬럼 바로 아래에 삽입:

```python
        # 비교 모드 사소 필터
        site_opts2 = ["전체"] + sorted(receipt["사소구분"].dropna().unique().tolist())
        f_site = st.selectbox("사소 필터", site_opts2, key="site2_cmp")
```

- [ ] **Step 4: 기존 구분/공급사/품목/등급 필터 유지 확인**

필터 블록(`fc4`, `fc5`, `fc6`, `fc6b`, `fc7`)은 양 모드에서 동일하게 사용되므로 변경 불필요.
아래 변수들이 양쪽 모드에서 모두 정의됨을 확인: `start_date`, `end_date`, `f_site`

- [ ] **Step 5: 차트/요약 출력 블록에 비교 모드 분기 추가**

기존 `st.plotly_chart(make_receipt_detail_bar(...))` 호출 이전에 아래 분기를 추가한다.  
(기존 필터 마스크 계산 및 `filtered` 생성 코드 이후, 차트 출력 직전에 삽입)

```python
    if _compare_mode:
        # B기간 필터링 (A기간과 동일한 필터 조건, 날짜만 교체)
        mask_b = (receipt["날짜"] >= cmp_b_start) & (receipt["날짜"] <= cmp_b_end)
        if f_site != "전체":
            mask_b &= receipt["사소구분"] == f_site
        if f_gubun:
            mask_b &= receipt["구분"].isin(f_gubun)
        if f_supplier and "합계" not in f_supplier:
            mask_b &= receipt["공급사"].isin(f_supplier)
        if f_item and "합계" not in f_item:
            mask_b &= receipt["구매item"].isin(f_item)
        if f_grade_cat and "합계" not in f_grade_cat:
            mask_b &= receipt["등급대분류"].isin(f_grade_cat)
        if f_grade and "합계" not in f_grade:
            mask_b &= receipt["등급"].isin(f_grade)
        filtered_b = receipt[mask_b]

        label_a = f"{cmp_a_start}~{cmp_a_end}"
        label_b = f"{cmp_b_start}~{cmp_b_end}"

        # 비교 기준 컬럼 선택
        grp_col_options = ["구분", "구매item", "등급대분류", "공급사"]
        grp_col = st.selectbox("비교 기준", grp_col_options, key="cmp_group_col")

        st.plotly_chart(
            make_comparison_bar(filtered, filtered_b, label_a, label_b, group_col=grp_col),
            use_container_width=True,
        )
        # 집계 테이블 (A/B 나란히)
        agg_a = filtered.groupby(grp_col)["입하량(net)"].sum().rename("A기간")
        agg_b = filtered_b.groupby(grp_col)["입하량(net)"].sum().rename("B기간")
        cmp_tbl = pd.concat([agg_a, agg_b], axis=1).fillna(0)
        cmp_tbl["증감량"] = cmp_tbl["A기간"] - cmp_tbl["B기간"]
        cmp_tbl["증감률(%)"] = ((cmp_tbl["A기간"] - cmp_tbl["B기간"]) / cmp_tbl["B기간"].replace(0, float("nan")) * 100).round(1)
        st.dataframe(
            cmp_tbl.reset_index().sort_values("A기간", ascending=False),
            use_container_width=True, hide_index=True,
            column_config={
                "A기간": st.column_config.NumberColumn(format="%,.0f"),
                "B기간": st.column_config.NumberColumn(format="%,.0f"),
                "증감량": st.column_config.NumberColumn(format="%,.0f"),
            },
        )
    else:
        # 기존 단일 기간 차트 출력 (변경 없음)
        ...  # 기존 make_receipt_detail_bar 호출 코드 그대로 유지
```

> **주의**: `...` 부분은 기존 `make_receipt_detail_bar` 호출 코드를 그대로 유지한다. 삭제하지 말 것.

- [ ] **Step 6: 앱 실행 확인**

브라우저에서 "기간 비교 모드" 토글 ON → A/B 날짜 피커 표시, "전월 비교" 버튼 클릭 → 날짜 자동 세팅, 차트 렌더링 확인.

- [ ] **Step 7: 커밋**

```bash
git add dashboard/app.py
git commit -m "feat: add period comparison mode to receipt detail section"
```

---

## Task 5: `app.py` — 구분별 가격정책 신호 섹션 추가

**Files:**
- Modify: `dashboard/app.py`

- [ ] **Step 1: import 추가**

`app.py` 상단 import 블록에 추가:

```python
from pipeline.gubun_signal import build_gubun_signal
```

- [ ] **Step 2: `_render_gubun_signal_section` 함수 정의**

`render()` 함수 앞(파일 내 다른 헬퍼 함수들과 같은 위치, `def render():` 바로 위)에 추가:

```python
def _render_gubun_signal_section(
    receipt: pd.DataFrame,
    api_key: str | None = None,
) -> None:
    """구분별 가격정책 신호 섹션 렌더링."""
    from dashboard.charts import make_gubun_signal_bar

    st.header("구분별 가격정책 신호")
    st.caption("구분(유통/MOU/전용야드)별 입고량 변화 패턴으로 가격 조정 필요 여부를 감지합니다.")

    # ── 필터 ─────────────────────────────────────────────────
    sg_c1, sg_c2, sg_c3 = st.columns([1, 1, 1])
    with sg_c1:
        sg_site_opts = ["전체"] + sorted(receipt["사소구분"].dropna().unique().tolist()) if "사소구분" in receipt.columns else ["전체"]
        sg_site = st.selectbox("사소구분", sg_site_opts, key="sg_site")
    with sg_c2:
        sg_compare = st.radio("비교 기준", ["전월 대비", "전주 대비"], horizontal=True, key="sg_compare")
    with sg_c3:
        sg_threshold = st.slider("감소 임계값 (%)", min_value=1, max_value=20, value=5, key="sg_threshold")

    compare_key = "week" if "전주" in sg_compare else "month"
    site_filter = None if sg_site == "전체" else sg_site

    signal_data = build_gubun_signal(
        receipt,
        compare=compare_key,
        threshold=float(sg_threshold),
        site=site_filter,
    )

    # ── 정책 신호 배너 ────────────────────────────────────────
    level = signal_data["signal"]["level"]
    message = signal_data["signal"]["message"]
    period_label = (
        f"{signal_data['cur_start']} ~ {signal_data['cur_end']} "
        f"vs {signal_data['prev_start']} ~ {signal_data['prev_end']}"
    )

    LEVEL_STYLE = {
        "red":    ("🔴", "#fef2f2", "#b91c1c"),
        "yellow": ("🟡", "#fffbeb", "#92400e"),
        "green":  ("🟢", "#f0fdf4", "#166534"),
        "gray":   ("⚪", "#f8fafc", "#475569"),
    }
    icon, bg, color = LEVEL_STYLE.get(level, LEVEL_STYLE["gray"])
    st.markdown(
        f'<div style="background:{bg};border-left:4px solid {color};'
        f'border-radius:0.5rem;padding:12px 16px;margin-bottom:12px;">'
        f'<span style="font-size:1.1rem;font-weight:700;color:{color}">{icon} {message}</span>'
        f'<div style="font-size:0.75rem;color:#64748b;margin-top:4px">비교 기간: {period_label}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── 분석 단위 탭 ──────────────────────────────────────────
    _sg_tab1, _sg_tab2, _sg_tab3 = st.tabs(["구분별", "품목×구분", "등급×구분"])

    cur_label  = f"당기({signal_data['cur_start']}~{signal_data['cur_end']})"
    prev_label = f"전기({signal_data['prev_start']}~{signal_data['prev_end']})"

    with _sg_tab1:
        if signal_data["by_group"]:
            st.plotly_chart(
                make_gubun_signal_bar(
                    signal_data["by_group"],
                    label_current=cur_label,
                    label_prev=prev_label,
                    exclude_groups=["회수", "수입"],  # 참고용 별도 표시
                ),
                use_container_width=True,
            )
            # 회수/수입 참고 표시
            ref_groups = {k: v for k, v in signal_data["by_group"].items() if k in ("회수", "수입")}
            if ref_groups:
                st.caption("* 회수·수입은 가격 정책 영향 없음 (참고)")
                ref_data = {k: v for k, v in signal_data["by_group"].items() if k in ref_groups}
                st.plotly_chart(
                    make_gubun_signal_bar(ref_data, label_current=cur_label, label_prev=prev_label),
                    use_container_width=True,
                )
        else:
            st.info("데이터 없음")

    with _sg_tab2:
        if signal_data["by_item_group"]:
            st.plotly_chart(
                make_gubun_signal_bar(
                    signal_data["by_item_group"],
                    label_current=cur_label,
                    label_prev=prev_label,
                    exclude_groups=["회수", "수입"],
                ),
                use_container_width=True,
            )
        else:
            st.info("데이터 없음")

    with _sg_tab3:
        if signal_data["by_grade_group"]:
            st.plotly_chart(
                make_gubun_signal_bar(
                    signal_data["by_grade_group"],
                    label_current=cur_label,
                    label_prev=prev_label,
                    exclude_groups=["회수", "수입"],
                ),
                use_container_width=True,
            )
        else:
            st.info("데이터 없음")
```

- [ ] **Step 3: `render()` 내 섹션 호출 삽입**

`# ── 섹션 2: 입고 상세 ──` 와 `# ── 섹션 3: 지역별 입고 현황` 사이에 추가:

```python
    # ── 섹션 3: 구분별 가격정책 신호 ──────────────────────────
    st.divider()
    _render_gubun_signal_section(receipt, api_key=api_key if api_key else None)
```

> **주의**: 기존 `# ── 섹션 3: 지역별 입고 현황 + AI 챗봇` 헤더의 번호가 4로 밀린다. 코멘트만 수정하면 됨.

- [ ] **Step 4: 앱 실행 확인**

"구분별 가격정책 신호" 섹션 확인 — 배너, 탭 3개(구분별/품목×구분/등급×구분) 모두 렌더링 확인.

- [ ] **Step 5: 커밋**

```bash
git add dashboard/app.py
git commit -m "feat: add gubun signal section for price policy detection"
```

---

## Task 6: AI 챗봇 연동 + CLAUDE.md 업데이트

**Files:**
- Modify: `dashboard/app.py` (build_graph 호출부, ANALYSIS_SYSTEM 관련)
- Modify: `pipeline/graph.py` (ANALYSIS_SYSTEM 프롬프트, build_graph 시그니처)
- Modify: `CLAUDE.md`

- [ ] **Step 1: `pipeline/graph.py` — `build_graph` 시그니처 및 프롬프트 수정**

`ANALYSIS_SYSTEM` 변수에 `gubun_summary` 설명 추가:

```python
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
- import는 pandas, numpy만 허용합니다.
- 한국어로 답변하는 코드를 작성하세요.

예시:
```python
actual = daily[daily["is_actual"]]
top = actual.groupby("구매item")["use_qty"].sum().sort_values(ascending=False)
result = "사용량 상위 품목:\\n" + "\\n".join(f"{i+1}. {k}: {v:,.0f}" for i,(k,v) in enumerate(top.items()))
```"""
```

`build_graph` 함수 시그니처에 `gubun_summary` 파라미터 추가:

```python
def build_graph(daily: pd.DataFrame, supplier_df: pd.DataFrame, retriever, api_key: str, gubun_summary: pd.DataFrame | None = None):
```

`analysis_node` 내 `_safe_exec` 호출 부분에서 `gubun_summary` 전달:

```python
        exec_result = _safe_exec(generated_code, daily, supplier_df, gubun_summary)
```

`_safe_exec` 함수 시그니처 및 local_vars 수정:

```python
def _safe_exec(code: str, daily: pd.DataFrame, supplier_df: pd.DataFrame, gubun_summary: pd.DataFrame | None = None) -> str:
    ...
    local_vars: dict = {
        "pd": pd, "pandas": pd,
        "daily": daily.copy(),
        "supplier_df": supplier_df.copy(),
        "gubun_summary": gubun_summary.copy() if gubun_summary is not None else pd.DataFrame(),
        "result": "결과 없음",
    }
```

- [ ] **Step 2: `app.py` — `build_graph` 호출부 수정**

`app.py` 에서 `build_graph(...)` 호출 시 `gubun_summary` 전달.  
먼저 `gubun_summary` DataFrame 생성 로직을 해당 호출 직전에 추가:

```python
            # gubun_summary DataFrame 생성 (AI 챗봇용)
            _sig = build_gubun_signal(receipt, compare="month")
            _gubun_rows = [
                {"구분그룹": k, "당기입고량": v["current"], "전기입고량": v["prev"], "증감률": v["pct"]}
                for k, v in _sig["by_group"].items()
            ]
            _gubun_summary_df = pd.DataFrame(_gubun_rows)
```

그리고 `build_graph` 호출을:

```python
            graph = build_graph(daily, supplier_df, retriever, api_key, gubun_summary=_gubun_summary_df)
```

으로 수정.

- [ ] **Step 3: `CLAUDE.md` 업데이트**

`CLAUDE.md`의 **섹션 구성** 항목을 아래로 업데이트:

```markdown
## 섹션 구성 (app.py render())

1. **월간 추이**: 탭A(단일 월 심층 — 실적/계획/전월/전년동월 체크박스 + KPI 박스) / 탭B(멀티 월 나란히 비교 그룹 막대)
2. **입고 상세**: 기간/사소/구분/공급사/품목/등급 필터 → 단일 기간 또는 A vs B 기간 비교 모드
3. **구분별 가격정책 신호**: 구분별(유통/MOU/전용야드) 입고량 변화율 + 정책 신호 감지 (전월/전주 대비)
4. **지역별 입고 현황 + AI 챗봇**: 좌우 2컬럼 배치
   - 지역 지도: Choropleth
   - AI 챗봇: LangGraph (RAG 조회 / 데이터 분석, gubun_summary 포함)
```

**알려진 이슈** 테이블에 추가:

```markdown
| `use_container_width` 경고 | 무시 가능 | Streamlit 버전 이슈, `width='stretch'`로 교체 예정 |
```

- [ ] **Step 4: 앱 전체 실행 확인**

```bash
cd C:\Users\user\Desktop\260331_project\0403_new
python -m streamlit run dashboard/app.py --server.port 8502
```

확인 항목:
1. 월간 추이 탭 A/B 정상 렌더링
2. 입고 상세 비교 모드 ON/OFF 전환
3. 구분별 가격정책 신호 섹션 표시
4. AI 챗봇 "현재 MOU 입고 상황은?" 질문 → 정상 응답 (API key 필요)

- [ ] **Step 5: 최종 커밋**

```bash
git add pipeline/graph.py dashboard/app.py CLAUDE.md
git commit -m "feat: integrate gubun_summary into AI chatbot and update CLAUDE.md"
```

---

## 자체 검토 결과

**Spec 커버리지 확인:**
- [x] 월별 현황 탭A (단일 월 심층 비교) — Task 3
- [x] 월별 현황 탭B (멀티 월 나란히) — Task 3
- [x] 입고 상세 빠른 선택 버튼 — Task 4
- [x] 입고 상세 A/B 자유 기간 설정 — Task 4
- [x] 입고 상세 증감률 레이블 — Task 2 (`make_comparison_bar`)
- [x] 구분별 가격정책 신호 패널 — Task 5
- [x] 구분별/품목×구분/등급×구분 탭 — Task 5
- [x] 감소 임계값 조정 슬라이더 — Task 5
- [x] AI 챗봇 gubun_summary 연동 — Task 6
- [x] `_LOAD_VERSION` 업데이트 — Task 3

**플레이스홀더**: 없음  
**타입 일관성**: `build_gubun_signal` 반환 dict의 키 구조가 Task 1 → Task 2 → Task 5 전체에서 동일하게 사용됨 확인  
**범위**: 단일 구현 계획으로 적합
