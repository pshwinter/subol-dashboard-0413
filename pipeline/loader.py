from dataclasses import dataclass
import pandas as pd

DATA_PATH = "260330_수불_더미데이터_v2_fixed.xlsx"
REF_PATH  = "260408_기준정보.xlsx"


@dataclass
class LoadedData:
    receipt: pd.DataFrame
    usage: pd.DataFrame
    exp_receipt: pd.DataFrame
    exp_usage: pd.DataFrame
    opening: pd.DataFrame
    ref: pd.DataFrame          # 기준정보 (공급사별 구분 O 표시)
    ref2: pd.DataFrame         # 기준정보2 (등급→구분 매핑)
    grade_ref: pd.DataFrame    # 등급구분 (등급→등급대분류)
    region_ref: pd.DataFrame      # 지역구분 (공급사→지역대구분·소구분)
    steelmaker_ref: pd.DataFrame  # 제강사 위치 (회사구분, 회사명, 공장, 위치)


def _melt_opening(df: pd.DataFrame) -> pd.DataFrame:
    """기초재고 Wide 형식 → Long 변환.

    입력: 사소구분, 구매ITEM, [날짜1], [날짜2], ...
    출력: 사소구분, 구매ITEM, date, 재고량
    """
    id_cols = ["사소구분", "구매ITEM"]
    date_cols = [c for c in df.columns if c not in id_cols]
    melted = df.melt(
        id_vars=id_cols,
        value_vars=date_cols,
        var_name="date",
        value_name="재고량",
    )
    melted["date"] = pd.to_datetime(melted["date"]).dt.date
    melted["재고량"] = pd.to_numeric(melted["재고량"], errors="coerce").fillna(0)
    return melted


def load_workbooks(
    data_path: str = DATA_PATH,
    ref_path: str = REF_PATH,
) -> LoadedData:
    with pd.ExcelFile(data_path) as wb:
        receipt    = pd.read_excel(wb, sheet_name="입고")
        usage      = pd.read_excel(wb, sheet_name="사용")
        exp_receipt = pd.read_excel(wb, sheet_name="예상입고량")
        exp_usage  = pd.read_excel(wb, sheet_name="예상사용량")
        opening    = _melt_opening(pd.read_excel(wb, sheet_name="기초재고"))
    ref      = pd.read_excel(ref_path, sheet_name="기준정보")
    grade_ref = pd.read_excel(ref_path, sheet_name="등급구분")
    try:
        ref2 = pd.read_excel(ref_path, sheet_name="기준정보2")
    except Exception:
        ref2 = pd.DataFrame(columns=["등급", "구분"])
    try:
        region_ref = pd.read_excel(
            ref_path, sheet_name="지역구분",
            usecols=["공급사명", "지역대구분", "지역소구분"],
        ).rename(columns={"공급사명": "공급사"})
    except Exception:
        region_ref = pd.DataFrame(columns=["공급사", "지역대구분", "지역소구분"])
    try:
        steelmaker_ref = pd.read_excel(ref_path, sheet_name="제강사 위치")
    except Exception:
        steelmaker_ref = pd.DataFrame(columns=["회사구분", "회사명", "공장", "위치"])
    return LoadedData(
        receipt=receipt, usage=usage,
        exp_receipt=exp_receipt, exp_usage=exp_usage,
        opening=opening, ref=ref, ref2=ref2, grade_ref=grade_ref,
        region_ref=region_ref, steelmaker_ref=steelmaker_ref,
    )


# ── 구분 분류 유틸 ────────────────────────────────────────────

def build_gubun_classifier(ref: pd.DataFrame, ref2: pd.DataFrame):
    """기준정보·기준정보2로부터 구분 분류에 필요한 두 딕셔너리를 반환.

    Returns
    -------
    supplier_gubuns : dict[str, list[str]]
        {공급사명: [구분1, 구분2, ...]}  (O 표시 컬럼들)
    gubun_grades : dict[str, set[str]]
        {구분: {등급들}}  (기준정보2 기반)
    """
    gubun_cols = [c for c in ref.columns if c != "공급사명"]
    supplier_gubuns: dict[str, list[str]] = {}
    for _, row in ref.iterrows():
        gubuns = [col for col in gubun_cols if row.get(col) == "O"]
        supplier_gubuns[str(row["공급사명"])] = gubuns

    gubun_grades: dict[str, set[str]] = {}
    for _, row in ref2.iterrows():
        g = str(row["구분"])
        gubun_grades.setdefault(g, set()).add(str(row["등급"]))

    return supplier_gubuns, gubun_grades


def classify_gubun_series(
    receipt: pd.DataFrame,
    supplier_gubuns: dict,
    gubun_grades: dict,
) -> pd.Series:
    """입고 DataFrame의 각 행에 구분을 결정해 Series로 반환.

    규칙
    ----
    1. 기준정보에 없는 공급사 → 유통
    2. 회수 표시 공급사 → 등급 무관 전부 회수
    3. 그 외: 공급사의 구분 중 기준정보2에서 해당 등급과 매칭되는 구분 → 해당 구분
    4. 매칭 없음 → 유통
    """
    def _classify(row: pd.Series) -> str:
        gubuns = supplier_gubuns.get(str(row.get("공급사", "")), [])
        if not gubuns:
            return "유통"
        if "회수" in gubuns:
            return "회수"
        if "수입" in gubuns:
            return "수입"
        grade = str(row.get("등급", ""))
        for gubun in gubuns:
            if gubun == "유통":
                continue
            if grade in gubun_grades.get(gubun, set()):
                return gubun
        return "유통"

    return receipt.apply(_classify, axis=1)
