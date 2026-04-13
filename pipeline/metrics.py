import pandas as pd
from pipeline.loader import LoadedData
from pipeline.transform import standardize_movement_df, standardize_expected_df, _apply_site_map


def _filter_out_keys(df: pd.DataFrame, act_keys: set) -> pd.DataFrame:
    """act_keys에 해당하는 (사소구분, 구매item, date) 행을 제거."""
    idx = pd.MultiIndex.from_arrays([df["사소구분"], df["구매item"], df["date"]])
    act_midx = pd.MultiIndex.from_tuples(act_keys)
    return df[~idx.isin(act_midx)]


def _select_opening(opening: pd.DataFrame, min_date) -> pd.DataFrame:
    """데이터 시작일 기준으로 기초재고 날짜 선택.

    opening에 'date' 컬럼이 있으면 min_date 이하 중 가장 최근 날짜 행만 추출.
    없으면 (구형식) 그대로 반환.
    """
    if "date" not in opening.columns or min_date is None:
        return opening

    avail = sorted(opening["date"].unique())
    valid = [d for d in avail if d <= min_date]
    selected = valid[-1] if valid else avail[0]
    return opening[opening["date"] == selected].drop(columns=["date"]).copy()


def bucket_metrics(data: LoadedData) -> dict[str, pd.DataFrame]:
    """LoadedData → 사소×ITEM×날짜 집계 결과."""
    receipt = standardize_movement_df(data.receipt, qty_col="입하량(net)", date_col="입하일시")
    usage = standardize_movement_df(data.usage, qty_col="입하량(net)", date_col="입하일시")
    exp_receipt = standardize_expected_df(data.exp_receipt)
    exp_usage = standardize_expected_df(data.exp_usage)

    # 실적 시작일 기준으로 기초재고 날짜 선택
    min_date = receipt["date"].min() if not receipt.empty else (
        usage["date"].min() if not usage.empty else None
    )
    opening = _select_opening(data.opening.copy(), min_date)

    if "구매ITEM" in opening.columns:
        opening = opening.rename(columns={"구매ITEM": "구매item"})

    _apply_site_map(opening, "opening")

    daily = daily_recv_use_inv(receipt, usage, exp_receipt, exp_usage, opening)
    return {"daily": daily}


def daily_recv_use_inv(
    receipt: pd.DataFrame,
    usage: pd.DataFrame,
    exp_receipt: pd.DataFrame,
    exp_usage: pd.DataFrame,
    opening: pd.DataFrame,
) -> pd.DataFrame:
    """일별 입고/사용/재고 계산.

    - receipt, usage: standardize_movement_df 결과 (컬럼: 사소구분, 구매item, date, qty)
    - exp_receipt, exp_usage: standardize_expected_df 결과 (동일 구조)
    - opening: 사소구분, 구매item, 재고량
    반환: 사소구분, 구매item, date, recv_qty, use_qty, inv, is_actual
    """
    # 실적 일별 집계
    recv_act = (
        receipt.groupby(["사소구분", "구매item", "date"])["qty"]
        .sum()
        .reset_index()
        .rename(columns={"qty": "recv_qty"})
    )
    use_act = (
        usage.groupby(["사소구분", "구매item", "date"])["qty"]
        .sum()
        .reset_index()
        .rename(columns={"qty": "use_qty"})
    )

    # 실적이 있는 (사소, item, date) 집합
    recv_act_keys = set(zip(recv_act["사소구분"], recv_act["구매item"], recv_act["date"]))
    use_act_keys = set(zip(use_act["사소구분"], use_act["구매item"], use_act["date"]))

    # 예상 데이터에서 실적이 있는 날 제거
    exp_recv_fil = _filter_out_keys(exp_receipt, recv_act_keys).rename(columns={"qty": "recv_qty"})
    exp_use_fil = _filter_out_keys(exp_usage, use_act_keys).rename(columns={"qty": "use_qty"})

    # 입고 병합 (실적 + 예상)
    recv_act["is_actual"] = True
    exp_recv_fil["is_actual"] = False
    recv_all = pd.concat(
        [recv_act[["사소구분", "구매item", "date", "recv_qty", "is_actual"]],
         exp_recv_fil[["사소구분", "구매item", "date", "recv_qty", "is_actual"]]],
        ignore_index=True,
    )

    # 사용 병합 (실적 + 예상)
    use_act["is_actual"] = True
    exp_use_fil["is_actual"] = False
    use_all = pd.concat(
        [use_act[["사소구분", "구매item", "date", "use_qty", "is_actual"]],
         exp_use_fil[["사소구분", "구매item", "date", "use_qty", "is_actual"]]],
        ignore_index=True,
    )

    # 입고+사용 outer join
    daily = pd.merge(
        recv_all, use_all,
        on=["사소구분", "구매item", "date"],
        how="outer",
        suffixes=("_r", "_u"),
    )
    daily["recv_qty"] = daily["recv_qty"].fillna(0)
    daily["use_qty"] = daily["use_qty"].fillna(0)

    is_actual_r = daily["is_actual_r"].astype("boolean").fillna(False)
    is_actual_u = daily["is_actual_u"].astype("boolean").fillna(False)

    # 실적 날짜이지만 해당 품목의 실적 데이터가 없는 경우 예상값 → 0으로 교체
    # (실사용O·실입고X → recv_qty 예상값이 실적으로 오인되는 문제 방지, 재고 오류도 수정)
    daily.loc[is_actual_u & ~is_actual_r, "recv_qty"] = 0.0
    daily.loc[is_actual_r & ~is_actual_u, "use_qty"] = 0.0

    daily["is_actual"] = is_actual_r | is_actual_u
    daily = daily.drop(columns=["is_actual_r", "is_actual_u"])
    daily = daily.sort_values(["사소구분", "구매item", "date"]).reset_index(drop=True)

    # 기초재고 lookup
    opening_map = (
        opening.set_index(["사소구분", "구매item"])["재고량"].to_dict()
    )

    # 사소×ITEM 그룹별 누적 재고 계산
    parts = []
    for (site, item), grp in daily.groupby(["사소구분", "구매item"]):
        grp = grp.sort_values("date").copy()
        init = opening_map.get((site, item), 0.0)
        grp["inv"] = init + (grp["recv_qty"].cumsum() - grp["use_qty"].cumsum())
        parts.append(grp)

    result = pd.concat(parts, ignore_index=True)
    return result[["사소구분", "구매item", "date", "recv_qty", "use_qty", "inv", "is_actual"]]
