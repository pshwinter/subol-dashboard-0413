import pytest
import io
import pandas as pd
from datetime import date
from report.exporter import export_workbook_bytes


def make_daily():
    return pd.DataFrame({
        "사소구분": ["포항소", "포항소", "광양소"],
        "구매item": ["ADS01", "ADS01", "ADS01"],
        "date": [date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 1)],
        "recv_qty": [100.0, 80.0, 50.0],
        "use_qty": [50.0, 60.0, 30.0],
        "inv": [1050.0, 1070.0, 2020.0],
        "is_actual": [True, True, True],
    })


def make_supplier():
    return pd.DataFrame({
        "공급사명": ["공급사04", "공급사05"],
        "구분": ["MOU", "MOU"],
        "ITEM": ["ADS01", "ADS01"],
        "사소구분": ["포항소", "광양소"],
        "recv_qty": [100.0, 50.0],
    })


def test_export_returns_bytes():
    result = export_workbook_bytes(make_daily(), make_supplier())
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_export_sheet_names():
    result = export_workbook_bytes(make_daily(), make_supplier())
    wb = pd.ExcelFile(io.BytesIO(result))
    assert "수불현황" in wb.sheet_names
    assert "공급사" in wb.sheet_names


def test_export_subbul_has_data():
    result = export_workbook_bytes(make_daily(), make_supplier())
    df = pd.read_excel(io.BytesIO(result), sheet_name="수불현황")
    assert len(df) > 0


def test_export_supplier_has_data():
    result = export_workbook_bytes(make_daily(), make_supplier())
    df = pd.read_excel(io.BytesIO(result), sheet_name="공급사")
    assert len(df) > 0


def test_export_with_forecast_data():
    """is_actual=False 데이터 포함 시 오류 없이 실행되는지 확인."""
    daily = make_daily().copy()
    daily.loc[2, "is_actual"] = False
    result = export_workbook_bytes(daily, make_supplier())
    assert isinstance(result, bytes)
    assert len(result) > 0
