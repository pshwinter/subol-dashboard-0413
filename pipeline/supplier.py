import pandas as pd
from pipeline.transform import standardize_movement_df, SITE_MAP


def build_supplier_summary(
    receipt: pd.DataFrame,
    ref: pd.DataFrame,
) -> pd.DataFrame:
    """입고 실적과 기준정보를 매칭하여 공급사별 입고량 집계 반환.

    ITEM은 실제 입고 품목(receipt.구매item)을 사용.
    ref에서는 구분(MOU/회수/유통) 정보만 가져옴.
    미매칭 공급사는 공급사명='기타', 구분='미분류'.
    반환 컬럼: 공급사명, 구분, ITEM, 사소구분, recv_qty
    """
    std = standardize_movement_df(receipt, qty_col="입하량(net)", date_col="입하일시")

    # ref에서 공급사별 대표 구분 추출
    # 우선: O 표시 컬럼 방식(새 기준정보) / 폴백: 구분 컬럼 방식(구 기준정보)
    gubun_cols = [c for c in ref.columns if c != "공급사명"]
    has_o_markers = any(ref[c].astype(str).eq("O").any() for c in gubun_cols)

    if has_o_markers:
        def _primary(row):
            gs = [c for c in gubun_cols if str(row.get(c, "")) == "O"]
            return gs[0] if gs else "미분류"
        ref_lookup = pd.DataFrame({
            "공급사": ref["공급사명"],
            "구분": ref.apply(_primary, axis=1),
        })
    elif "구분" in ref.columns:
        ref_lookup = (
            ref.rename(columns={"공급사명": "공급사"})[["공급사", "구분"]]
            .drop_duplicates(subset=["공급사"])
        )
    else:
        ref_lookup = pd.DataFrame({
            "공급사": ref["공급사명"],
            "구분": "미분류",
        })

    merged = std.merge(ref_lookup, on="공급사", how="left")

    # 미매칭 처리
    unmatched = merged["구분"].isna()
    merged["공급사명"] = merged["공급사"].where(~unmatched, "기타")
    merged["구분"] = merged["구분"].fillna("미분류")

    summary = (
        merged.groupby(["공급사명", "구분", "구매item", "사소구분"])["qty"]
        .sum()
        .reset_index()
        .rename(columns={"qty": "recv_qty", "구매item": "ITEM"})
    )
    return summary
