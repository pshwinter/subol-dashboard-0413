# pipeline/gubun_signal.py
"""구분별 입고량 변화율 및 가격정책 신호 계산."""
from __future__ import annotations

import datetime
import pandas as pd

_SUFFIX_ORDER = ["전용야드", "MOU", "회수", "수입", "유통"]


def map_gubun_group(gubun_val: str) -> str:
    for suffix in _SUFFIX_ORDER:
        if gubun_val.endswith(suffix):
            return suffix
    return gubun_val


def _month_ranges(ref_date: datetime.date):
    cur_start = ref_date.replace(day=1)
    cur_end = ref_date
    prev_end = cur_start - datetime.timedelta(days=1)
    prev_start = prev_end.replace(day=1)
    return cur_start, cur_end, prev_start, prev_end


def _week_ranges(ref_date: datetime.date):
    cur_start = ref_date - datetime.timedelta(days=(ref_date.weekday() + 1) % 7)
    cur_end = ref_date
    prev_end = cur_start - datetime.timedelta(days=1)
    prev_start = prev_end - datetime.timedelta(days=(prev_end.weekday() + 1) % 7)
    return cur_start, cur_end, prev_start, prev_end


def _agg_by(df: pd.DataFrame, group_cols: list[str]) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)
    return df.groupby(group_cols)["입하량(net)"].sum()


def _pct_change(current: float, prev: float) -> float:
    if prev <= 0:
        return 0.0
    return (current - prev) / prev * 100.0


def _count_working_days(start: datetime.date, end: datetime.date) -> int:
    """start~end(포함) 기간의 영업일 수 (평일 - 한국 공휴일)."""
    try:
        import holidays as _holidays
        kr = _holidays.KR(years=range(start.year, end.year + 1))
        holiday_dates = set(kr.keys())
    except (ImportError, Exception):
        holiday_dates = set()
    count = 0
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in holiday_dates:
            count += 1
        d += datetime.timedelta(days=1)
    return max(count, 1)


_POLICY_GROUPS = {"유통", "MOU", "전용야드"}


def _detect_signal(group_result: dict, threshold: float) -> dict:
    present = {g for g in _POLICY_GROUPS if group_result.get(g, {}).get("prev", 0) > 0}
    if not present:
        return {"level": "gray", "message": "데이터 없음"}

    decreasing = {g for g in present if group_result[g]["pct"] <= -threshold}
    increasing = {g for g in present if group_result[g]["pct"] >= threshold}

    distribution_down = "유통" in decreasing
    incentive_down = bool(decreasing & {"MOU", "전용야드"})
    all_down = present.issubset(decreasing | {"회수", "수입"})
    all_up = present.issubset(increasing | {"회수", "수입"})

    def _fmt(groups):
        return ", ".join(sorted(groups))

    if all_up:
        return {"level": "green", "message": "현행 가격 경쟁력 양호 — 전 구분 입고 증가"}
    if all_down:
        return {"level": "red", "message": "기본가 조정 검토 — 유통·MOU·전용야드 모두 감소"}
    if incentive_down and not distribution_down:
        msg = "인센티브 조정 검토 — MOU/전용야드 감소, 유통 유지"
        if increasing - {"유통"}:
            msg += f" (증가: {_fmt(increasing)})"
        return {"level": "yellow", "message": msg}
    if distribution_down and not incentive_down:
        msg = "기본가 소폭 조정 검토 — 유통 감소, MOU/전용야드 유지"
        if increasing - {"유통"}:
            msg += f" (증가: {_fmt(increasing - {'유통'})})"
        return {"level": "yellow", "message": msg}
    if decreasing and increasing:
        return {"level": "yellow", "message": f"혼재 — 감소: {_fmt(decreasing)} / 증가: {_fmt(increasing)}"}
    if decreasing:
        return {"level": "yellow", "message": f"일부 구분 감소 — {_fmt(decreasing)}"}
    if increasing:
        return {"level": "green", "message": f"입고 증가세 — {_fmt(increasing)} 증가"}
    return {"level": "gray", "message": "유의미한 변화 없음"}


def build_gubun_signal(
    receipt_df: pd.DataFrame,
    compare: str = "month",
    ref_date: datetime.date | None = None,
    threshold: float = 5.0,
    site: str | None = None,
    cur_period: tuple | None = None,
    prev_period: tuple | None = None,
) -> dict:
    """cur_period / prev_period 가 주어지면 compare/ref_date 무시하고 해당 기간 사용."""
    df = receipt_df.copy()
    # 날짜 컬럼을 datetime.date 타입으로 정규화
    sample = df["날짜"].dropna().iloc[0] if not df["날짜"].dropna().empty else None
    if sample is not None and not isinstance(sample, datetime.date):
        df["날짜"] = pd.to_datetime(df["날짜"]).dt.date

    # ref_date는 site 필터 적용 전 전체 데이터 기준으로 결정
    if cur_period and prev_period:
        cur_start, cur_end = cur_period
        prev_start, prev_end = prev_period
    else:
        if ref_date is None:
            ref_date = df["날짜"].max()
        if compare == "week":
            cur_start, cur_end, prev_start, prev_end = _week_ranges(ref_date)
        else:
            cur_start, cur_end, prev_start, prev_end = _month_ranges(ref_date)

    if site and "사소구분" in df.columns:
        df = df[df["사소구분"] == site]

    cur_df  = df[(df["날짜"] >= cur_start)  & (df["날짜"] <= cur_end)].copy()
    prev_df = df[(df["날짜"] >= prev_start) & (df["날짜"] <= prev_end)].copy()

    cur_df["_group"]  = cur_df["구분"].apply(map_gubun_group)
    prev_df["_group"] = prev_df["구분"].apply(map_gubun_group)

    cur_wdays = _count_working_days(cur_start, cur_end)
    prev_wdays = _count_working_days(prev_start, prev_end)

    def _build_result(cur_series: pd.Series, prev_series: pd.Series) -> dict:
        all_keys = set(cur_series.index) | set(prev_series.index)
        out = {}
        for k in all_keys:
            c = float(cur_series.get(k, 0.0)) / cur_wdays
            p = float(prev_series.get(k, 0.0)) / prev_wdays
            out[k] = {"current": c, "prev": p, "pct": _pct_change(c, p)}
        return out

    by_group = _build_result(_agg_by(cur_df, ["_group"]), _agg_by(prev_df, ["_group"]))
    by_grade = _build_result(_agg_by(cur_df, ["등급대분류"]), _agg_by(prev_df, ["등급대분류"]))
    by_grade_group = _build_result(_agg_by(cur_df, ["등급대분류", "_group"]), _agg_by(prev_df, ["등급대분류", "_group"]))

    return {
        "by_group": by_group,
        "by_grade": by_grade,
        "by_grade_group": by_grade_group,
        "signal": _detect_signal(by_group, threshold),
        "cur_start": cur_start,
        "cur_end": cur_end,
        "prev_start": prev_start,
        "prev_end": prev_end,
    }
