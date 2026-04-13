from datetime import timedelta
import pandas as pd

SITE_MAP = {
    "광양": "광양소",
    "포항": "포항소",
    "광양소": "광양소",
    "포항소": "포항소",
}

_BUSINESS_DAY_OFFSET = timedelta(hours=7)   # 당일 07:00 ~ 익일 06:59 = 당일


def _apply_site_map(df: pd.DataFrame, label: str = "") -> None:
    """사소구분 컬럼에 SITE_MAP을 in-place 적용. 미등록 값이 있으면 ValueError."""
    mapped = df["사소구분"].map(SITE_MAP)
    unknown = df.loc[mapped.isna(), "사소구분"].unique().tolist()
    if unknown:
        prefix = f"{label} " if label else ""
        raise ValueError(f"{prefix}알 수 없는 사소구분 값: {unknown}")
    df["사소구분"] = mapped


def standardize_movement_df(
    df: pd.DataFrame,
    qty_col: str,
    date_col: str,
) -> pd.DataFrame:
    """입고/사용 실적 DataFrame 표준화.

    일자 기준: 당일 07:00:00 ~ 익일 06:59:59 = 당일 데이터
    반환 컬럼: 사소구분, 구매item, date, qty [, 등급, 공급사]
    """
    out = df.copy()
    _apply_site_map(out)
    out["date"] = (pd.to_datetime(out[date_col]) - _BUSINESS_DAY_OFFSET).dt.date
    out["qty"] = out[qty_col].fillna(0).astype(float)

    keep = ["사소구분", "구매item", "date", "qty"]
    for extra in ["등급", "공급사"]:
        if extra in out.columns:
            keep.append(extra)
    return out[keep].reset_index(drop=True)


def standardize_expected_df(df: pd.DataFrame) -> pd.DataFrame:
    """예상 데이터 Wide → Long 변환.

    예상 데이터는 이미 날짜 단위이므로 07:00 오프셋 불필요.
    반환 컬럼: 사소구분, 구매item, date, qty
    """
    out = df.copy()
    _apply_site_map(out)

    id_cols = ["사소구분", "ITEM"]
    date_cols = [c for c in out.columns if c not in id_cols]

    melted = out.melt(
        id_vars=id_cols,
        value_vars=date_cols,
        var_name="date",
        value_name="qty",
    )
    melted["date"] = pd.to_datetime(melted["date"]).dt.date
    melted["qty"] = pd.to_numeric(melted["qty"], errors='coerce').fillna(0).astype(float)
    melted = melted.rename(columns={"ITEM": "구매item"})
    return melted[["사소구분", "구매item", "date", "qty"]].reset_index(drop=True)
