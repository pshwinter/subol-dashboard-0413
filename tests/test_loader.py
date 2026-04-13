import pytest
from pipeline.loader import load_workbooks, LoadedData

def test_load_workbooks_returns_loaded_data():
    data = load_workbooks(
        data_path="260330_수불_더미데이터.xlsx",
        ref_path="260330_기준정보.xlsx",
    )
    assert isinstance(data, LoadedData)
    assert len(data.receipt) > 0
    assert len(data.usage) > 0
    assert len(data.exp_receipt) > 0
    assert len(data.exp_usage) > 0
    assert len(data.opening) > 0
    assert len(data.ref) > 0

def test_loaded_data_receipt_columns():
    data = load_workbooks(
        data_path="260330_수불_더미데이터.xlsx",
        ref_path="260330_기준정보.xlsx",
    )
    for col in ["사소구분", "입하량(net)", "구매item", "등급", "공급사", "입하일시"]:
        assert col in data.receipt.columns

def test_loaded_data_usage_columns():
    data = load_workbooks(
        data_path="260330_수불_더미데이터.xlsx",
        ref_path="260330_기준정보.xlsx",
    )
    for col in ["사소구분", "입하량(net)", "구매item", "입하일시"]:
        assert col in data.usage.columns
