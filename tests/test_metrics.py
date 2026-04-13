import pytest
import pandas as pd
from datetime import date
from pipeline.metrics import daily_recv_use_inv, bucket_metrics
from pipeline.loader import LoadedData


def make_std_receipt():
    return pd.DataFrame({
        "사소구분": ["포항소", "포항소"],
        "구매item": ["ADS01", "ADS01"],
        "date": [date(2026, 3, 1), date(2026, 3, 2)],
        "qty": [100.0, 80.0],
        "등급": ["생압G", "생압G"],
        "공급사": ["공급사04", "공급사04"],
    })


def make_std_usage():
    return pd.DataFrame({
        "사소구분": ["포항소", "포항소"],
        "구매item": ["ADS01", "ADS01"],
        "date": [date(2026, 3, 1), date(2026, 3, 2)],
        "qty": [50.0, 60.0],
    })


def make_exp_receipt():
    return pd.DataFrame({
        "사소구분": ["포항소"],
        "구매item": ["ADS01"],
        "date": [date(2026, 3, 3)],
        "qty": [180.0],
    })


def make_exp_usage():
    return pd.DataFrame({
        "사소구분": ["포항소"],
        "구매item": ["ADS01"],
        "date": [date(2026, 3, 3)],
        "qty": [150.0],
    })


def make_opening():
    return pd.DataFrame({
        "사소구분": ["포항소"],
        "구매item": ["ADS01"],
        "재고량": [1000.0],
    })


def test_daily_recv_use_inv_columns():
    result = daily_recv_use_inv(
        make_std_receipt(), make_std_usage(),
        make_exp_receipt(), make_exp_usage(), make_opening()
    )
    for col in ["사소구분", "구매item", "date", "recv_qty", "use_qty", "inv", "is_actual"]:
        assert col in result.columns


def test_daily_inventory_calculation():
    result = daily_recv_use_inv(
        make_std_receipt(), make_std_usage(),
        make_exp_receipt(), make_exp_usage(), make_opening()
    )
    pohang = result[(result["사소구분"] == "포항소") & (result["구매item"] == "ADS01")]
    pohang = pohang.sort_values("date").reset_index(drop=True)
    # 3/1: 1000 + 100 - 50 = 1050
    assert pohang.loc[0, "inv"] == pytest.approx(1050.0)
    # 3/2: 1050 + 80 - 60 = 1070
    assert pohang.loc[1, "inv"] == pytest.approx(1070.0)
    # 3/3: 예상 → 1070 + 180 - 150 = 1100
    assert pohang.loc[2, "inv"] == pytest.approx(1100.0)


def test_actual_flag():
    result = daily_recv_use_inv(
        make_std_receipt(), make_std_usage(),
        make_exp_receipt(), make_exp_usage(), make_opening()
    )
    pohang = result[(result["사소구분"] == "포항소") & (result["구매item"] == "ADS01")]
    pohang = pohang.sort_values("date").reset_index(drop=True)
    assert pohang.loc[0, "is_actual"] == True   # 3/1 실적
    assert pohang.loc[1, "is_actual"] == True   # 3/2 실적
    assert pohang.loc[2, "is_actual"] == False  # 3/3 예상


def test_bucket_metrics_returns_dict(
    sample_receipt, sample_usage, sample_exp_receipt,
    sample_exp_usage, sample_opening, sample_ref
):
    data = LoadedData(
        receipt=sample_receipt,
        usage=sample_usage,
        exp_receipt=sample_exp_receipt,
        exp_usage=sample_exp_usage,
        opening=sample_opening,
        ref=sample_ref,
    )
    result = bucket_metrics(data)
    assert "daily" in result
    assert len(result["daily"]) > 0
