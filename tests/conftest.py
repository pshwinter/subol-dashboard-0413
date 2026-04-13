import pytest
import pandas as pd
from datetime import date

@pytest.fixture
def sample_receipt():
    return pd.DataFrame({
        "사소구분": ["광양", "포항", "광양"],
        "입하량(net)": [20.0, 30.0, 10.0],
        "구매item": ["ADS01", "ADS01", "ADS02"],
        "등급": ["생압G", "생압G", "압축P"],
        "공급사": ["공급사01", "공급사04", "공급사05"],
        "입하일시": pd.to_datetime(["2026-03-01", "2026-03-02", "2026-03-01"]),
    })

@pytest.fixture
def sample_usage():
    return pd.DataFrame({
        "사소구분": ["광양", "포항"],
        "입하량(net)": [15.0, 25.0],
        "구매item": ["ADS01", "ADS01"],
        "입하일시": pd.to_datetime(["2026-03-01", "2026-03-02"]),
    })

@pytest.fixture
def sample_exp_receipt():
    return pd.DataFrame({
        "사소구분": ["포항소"],
        "ITEM": ["ADS01"],
        pd.Timestamp("2026-03-03"): [180.0],
        pd.Timestamp("2026-03-04"): [180.0],
    })

@pytest.fixture
def sample_exp_usage():
    return pd.DataFrame({
        "사소구분": ["포항소"],
        "ITEM": ["ADS01"],
        pd.Timestamp("2026-03-03"): [150.0],
        pd.Timestamp("2026-03-04"): [150.0],
    })

@pytest.fixture
def sample_opening():
    return pd.DataFrame({
        "사소구분": ["포항소", "광양소"],
        "구매ITEM": ["ADS01", "ADS01"],
        "재고량": [3750.0, 2000.0],
    })

@pytest.fixture
def sample_ref():
    return pd.DataFrame({
        "공급사명": ["공급사01", "공급사02", "공급사04", "공급사05"],
        "구분": ["회수", "회수", "MOU", "MOU"],
        "ITEM": [None, None, "ADS01", "ADS01"],
    })
