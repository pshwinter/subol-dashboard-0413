from __future__ import annotations

import io
from typing import Optional
import pandas as pd


SITES = [("포항소", "포항"), ("광양소", "광양")]


def export_workbook_bytes(
    daily: pd.DataFrame,
    supplier: pd.DataFrame,
    receipt: Optional[pd.DataFrame] = None,
    selected_month: Optional[str] = None,  # "2026-03" 형식
) -> bytes:
    """Excel bytes 반환.

    Sheets
    ------
    포항_월간추이 / 광양_월간추이 : ITEM × 날짜 피벗 (입고·사용·재고 + 총계)
    포항_입고상세 / 광양_입고상세 : 공급사·구분·구매item·등급 × 날짜 피벗
    """
    buf = io.BytesIO()

    # 당월 필터
    if selected_month:
        month_period = pd.Period(selected_month, freq="M")
        daily = daily[
            pd.to_datetime(daily["date"]).dt.to_period("M") == month_period
        ].copy()
        if receipt is not None and not receipt.empty:
            receipt = receipt[
                pd.to_datetime(receipt["날짜"]).dt.to_period("M") == month_period
            ].copy()

    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        if daily.empty and (receipt is None or receipt.empty):
            pd.DataFrame({"알림": ["데이터가 없습니다."]}).to_excel(
                writer, sheet_name="안내", index=False
            )
        else:
            for site_code, site_label in SITES:
                _write_monthly_sheet(writer, daily, site_code, site_label)
                if receipt is not None and not receipt.empty:
                    _write_receipt_sheet(writer, receipt, site_code, site_label)

    return buf.getvalue()


# ── 공통 포맷 헬퍼 ─────────────────────────────────────────────

def _make_formats(wb):
    border = {"border": 1}
    return {
        "header":   wb.add_format({**border, "bold": True, "bg_color": "#D9E1F2", "align": "center", "valign": "vcenter"}),
        "label":    wb.add_format({**border, "bold": True, "bg_color": "#F2F2F2"}),
        "total":    wb.add_format({**border, "bold": True, "bg_color": "#FCE4D6", "num_format": "#,##0"}),
        "actual":   wb.add_format({**border, "bg_color": "#FFFFFF", "num_format": "#,##0"}),
        "forecast": wb.add_format({**border, "bg_color": "#FFF3CD", "num_format": "#,##0"}),
        "text":     wb.add_format({**border}),
        "text_bold":wb.add_format({**border, "bold": True}),
    }


# ── 월간추이 탭 ────────────────────────────────────────────────

def _write_monthly_sheet(
    writer: pd.ExcelWriter,
    daily: pd.DataFrame,
    site_code: str,
    site_label: str,
) -> None:
    sheet_name = f"{site_label}_월간추이"
    wb = writer.book
    ws = wb.add_worksheet(sheet_name)
    writer.sheets[sheet_name] = ws
    fmt = _make_formats(wb)

    # 실적 데이터만 출력 (예측 행 제외)
    site_df = daily[(daily["사소구분"] == site_code) & daily["is_actual"]].copy()
    if site_df.empty:
        ws.write(0, 0, "데이터 없음")
        return

    dates = sorted(site_df["date"].unique())
    items = sorted(site_df["구매item"].dropna().unique())

    # ITEM별 집계 (날짜 중복 대비 sum) — 모든 (item, date) 조합으로 reindex해 KeyError 방지
    item_pivot = (
        site_df.groupby(["구매item", "date"])[["recv_qty", "use_qty", "inv"]]
        .sum()
        .reindex(pd.MultiIndex.from_product([items, dates]), fill_value=0)
    )

    # 헤더
    ws.write(0, 0, "구매item", fmt["header"])
    ws.write(0, 1, "항목", fmt["header"])
    for col_i, d in enumerate(dates, start=2):
        ws.write(0, col_i, str(d), fmt["header"])

    row_i = 1
    # ITEM별 행
    for item in items:
        for label, col in [("입고", "recv_qty"), ("사용", "use_qty"), ("재고", "inv")]:
            ws.write(row_i, 0, item, fmt["label"])
            ws.write(row_i, 1, label, fmt["label"])
            for col_i, d in enumerate(dates, start=2):
                ws.write_number(row_i, col_i, float(item_pivot.loc[(item, d), col]), fmt["actual"])
            row_i += 1

    # 총계 행
    total_df = site_df.groupby("date")[["recv_qty", "use_qty", "inv"]].sum()
    for label, col in [("입고", "recv_qty"), ("사용", "use_qty"), ("재고", "inv")]:
        ws.write(row_i, 0, "총계", fmt["total"])
        ws.write(row_i, 1, label, fmt["total"])
        for col_i, d in enumerate(dates, start=2):
            val = float(total_df.loc[d, col]) if d in total_df.index else 0.0
            ws.write_number(row_i, col_i, val, fmt["total"])
        row_i += 1

    # 열 너비
    ws.set_column(0, 0, 14)
    ws.set_column(1, 1, 8)
    ws.set_column(2, len(dates) + 1, 12)


# ── 입고상세 탭 ────────────────────────────────────────────────

def _write_receipt_sheet(
    writer: pd.ExcelWriter,
    receipt: pd.DataFrame,
    site_code: str,
    site_label: str,
) -> None:
    sheet_name = f"{site_label}_입고상세"
    wb = writer.book
    ws = wb.add_worksheet(sheet_name)
    writer.sheets[sheet_name] = ws
    fmt = _make_formats(wb)

    site_df = receipt[receipt["사소구분"] == site_code].copy()
    if site_df.empty:
        ws.write(0, 0, "데이터 없음")
        return

    # 컬럼 순서: 공급사, 구분, 구매item, 등급
    index_cols = ["공급사", "구분", "구매item", "등급"]
    index_cols = [c for c in index_cols if c in site_df.columns]

    pivot = site_df.pivot_table(
        index=index_cols,
        columns="날짜",
        values="입하량(net)",
        aggfunc="sum",
        fill_value=0,
    )
    dates = [str(c) for c in pivot.columns]
    pivot.columns = dates
    pivot = pivot.reset_index()

    # 합계 열
    pivot["합계"] = pivot[dates].sum(axis=1)
    pivot = pivot.sort_values("합계", ascending=False).reset_index(drop=True)

    all_cols = index_cols + dates + ["합계"]

    # 헤더
    for col_i, col_name in enumerate(all_cols):
        ws.write(0, col_i, col_name, fmt["header"])

    # 데이터 행
    for row_i, row in pivot.iterrows():
        excel_row = row_i + 1
        for col_i, col_name in enumerate(index_cols):
            ws.write(excel_row, col_i, row[col_name], fmt["text"])
        for col_i, d in enumerate(dates, start=len(index_cols)):
            ws.write_number(excel_row, col_i, float(row[d]), fmt["actual"])
        # 합계
        ws.write_number(excel_row, len(all_cols) - 1, float(row["합계"]), fmt["total"])

    # 열 너비
    for i in range(len(index_cols)):
        ws.set_column(i, i, 14)
    ws.set_column(len(index_cols), len(all_cols) - 1, 12)
