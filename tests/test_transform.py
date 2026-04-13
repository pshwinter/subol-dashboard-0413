import pytest
import pandas as pd
from datetime import date
from pipeline.transform import standardize_movement_df, standardize_expected_df


def test_standardize_movement_site_mapping(sample_receipt):
    result = standardize_movement_df(sample_receipt, qty_col="입하량(net)", date_col="입하일시")
    assert set(result["사소구분"].unique()).issubset({"광양소", "포항소"})


def test_standardize_movement_date_type(sample_receipt):
    result = standardize_movement_df(sample_receipt, qty_col="입하량(net)", date_col="입하일시")
    assert isinstance(result["date"].iloc[0], date)


def test_standardize_movement_qty_float(sample_receipt):
    result = standardize_movement_df(sample_receipt, qty_col="입하량(net)", date_col="입하일시")
    assert result["qty"].dtype == float


def test_standardize_expected_long_format(sample_exp_receipt):
    result = standardize_expected_df(sample_exp_receipt)
    assert "date" in result.columns
    assert "qty" in result.columns
    assert "구매item" in result.columns
    # Wide 2열 → Long 2행
    assert len(result) == 2


def test_standardize_expected_site_mapping(sample_exp_receipt):
    result = standardize_expected_df(sample_exp_receipt)
    assert set(result["사소구분"].unique()).issubset({"광양소", "포항소"})


def test_standardize_expected_nan_to_zero():
    df = pd.DataFrame({
        "사소구분": ["포항소"],
        "ITEM": ["ADS01"],
        pd.Timestamp("2026-03-01"): [None],
    })
    result = standardize_expected_df(df)
    assert result["qty"].iloc[0] == 0.0


def test_business_day_boundary():
    """07:00 기준 일자 경계 테스트"""
    df = pd.DataFrame({
        "사소구분": ["포항"],
        "입하량(net)": [10.0],
        "구매item": ["ADS01"],
        "등급": ["생압G"],
        "공급사": ["공급사01"],
        # 2026-03-02 06:30 → 비즈니스 일자는 2026-03-01
        "입하일시": pd.to_datetime(["2026-03-02 06:30:00"]),
    })
    result = standardize_movement_df(df, qty_col="입하량(net)", date_col="입하일시")
    assert result["date"].iloc[0] == date(2026, 3, 1)


def test_business_day_at_boundary():
    """07:00 정각은 당일로 처리"""
    df = pd.DataFrame({
        "사소구분": ["포항"],
        "입하량(net)": [10.0],
        "구매item": ["ADS01"],
        "등급": ["생압G"],
        "공급사": ["공급사01"],
        # 2026-03-02 07:00 → 비즈니스 일자는 2026-03-02
        "입하일시": pd.to_datetime(["2026-03-02 07:00:00"]),
    })
    result = standardize_movement_df(df, qty_col="입하량(net)", date_col="입하일시")
    assert result["date"].iloc[0] == date(2026, 3, 2)


def test_business_day_upper_boundary():
    """06:59:59는 전일 데이터"""
    df = pd.DataFrame({
        "사소구분": ["포항"],
        "입하량(net)": [10.0],
        "구매item": ["ADS01"],
        "등급": ["생압G"],
        "공급사": ["공급사01"],
        "입하일시": pd.to_datetime(["2026-03-02 06:59:59"]),
    })
    result = standardize_movement_df(df, qty_col="입하량(net)", date_col="입하일시")
    assert result["date"].iloc[0] == date(2026, 3, 1)
