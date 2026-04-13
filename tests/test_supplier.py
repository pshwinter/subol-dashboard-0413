import pytest
import pandas as pd
from pipeline.supplier import build_supplier_summary


def test_supplier_summary_columns(sample_receipt, sample_ref):
    result = build_supplier_summary(sample_receipt, sample_ref)
    for col in ["공급사명", "구분", "ITEM", "사소구분", "recv_qty"]:
        assert col in result.columns


def test_supplier_unmatched_becomes_etc(sample_receipt, sample_ref):
    # 매칭되지 않는 공급사 추가
    extra = sample_receipt.copy()
    extra["공급사"] = "알수없는공급사"
    result = build_supplier_summary(extra, sample_ref)
    assert "기타" in result["공급사명"].values


def test_supplier_summary_aggregation(sample_receipt, sample_ref):
    result = build_supplier_summary(sample_receipt, sample_ref)
    # 전체 합계가 원본 qty 합계와 같아야 함
    assert result["recv_qty"].sum() == pytest.approx(sample_receipt["입하량(net)"].sum())
