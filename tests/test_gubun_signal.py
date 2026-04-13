import datetime
import pandas as pd
import pytest
from pipeline.gubun_signal import map_gubun_group, build_gubun_signal, _count_working_days


def test_map_gubun_group_mou():
    assert map_gubun_group("생철MOU") == "MOU"
    assert map_gubun_group("경압MOU") == "MOU"

def test_map_gubun_group_dedicated():
    assert map_gubun_group("생압전용야드") == "전용야드"
    assert map_gubun_group("경압전용야드") == "전용야드"

def test_map_gubun_group_distribution():
    assert map_gubun_group("유통") == "유통"

def test_map_gubun_group_recovery():
    assert map_gubun_group("회수") == "회수"

def test_map_gubun_group_import():
    assert map_gubun_group("수입") == "수입"

def test_map_gubun_group_unknown():
    assert map_gubun_group("알수없음") == "알수없음"


@pytest.fixture
def sample_receipt():
    """일평균 기준 비교를 위해 전 기간 매일 일정량 입고.

    유통: 당기(3/1~3/15) 100t/일, 전기(2/1~2/28) 80t/일 → 당기 일평균 > 전기 (증가)
    MOU: 당기 50t/일, 전기 100t/일 → 당기 일평균 < 전기 (감소)
    """
    rows = []
    for d in pd.date_range("2026-03-01", "2026-03-15", freq="D"):
        rows.append({"날짜": d.date(), "구분": "유통", "구매item": "생철", "등급대분류": "경량", "입하량(net)": 100.0})
    for d in pd.date_range("2026-02-01", "2026-02-28", freq="D"):
        rows.append({"날짜": d.date(), "구분": "유통", "구매item": "생철", "등급대분류": "경량", "입하량(net)": 80.0})
    for d in pd.date_range("2026-03-01", "2026-03-15", freq="D"):
        rows.append({"날짜": d.date(), "구분": "생철MOU", "구매item": "생철", "등급대분류": "경량", "입하량(net)": 50.0})
    for d in pd.date_range("2026-02-01", "2026-02-28", freq="D"):
        rows.append({"날짜": d.date(), "구분": "생철MOU", "구매item": "생철", "등급대분류": "경량", "입하량(net)": 100.0})
    return pd.DataFrame(rows)


def test_build_gubun_signal_groups(sample_receipt):
    result = build_gubun_signal(sample_receipt, compare="month", ref_date=datetime.date(2026, 3, 15))
    assert "유통" in result["by_group"]
    assert "MOU" in result["by_group"]

def test_build_gubun_signal_pct(sample_receipt):
    """일평균 = 총량 / 영업일수 로 계산되는지 검증."""
    result = build_gubun_signal(sample_receipt, compare="month", ref_date=datetime.date(2026, 3, 15))
    cur_wdays = _count_working_days(datetime.date(2026, 3, 1), datetime.date(2026, 3, 15))
    prev_wdays = _count_working_days(datetime.date(2026, 2, 1), datetime.date(2026, 2, 28))
    유통 = result["by_group"]["유통"]
    # 총량: cur = 100 × 15일, prev = 80 × 28일
    assert 유통["current"] == pytest.approx(100.0 * 15 / cur_wdays, rel=1e-6)
    assert 유통["prev"] == pytest.approx(80.0 * 28 / prev_wdays, rel=1e-6)
    # 당기 일평균이 전기 일평균보다 높아야 함
    assert 유통["pct"] > 0

def test_build_gubun_signal_mou_decrease(sample_receipt):
    """MOU 당기 일평균 < 전기 일평균 → pct < 0."""
    result = build_gubun_signal(sample_receipt, compare="month", ref_date=datetime.date(2026, 3, 15))
    mou = result["by_group"]["MOU"]
    assert mou["pct"] < 0

def test_build_gubun_signal_red_signal():
    """유통·MOU·전용야드 모두 일평균 대폭 감소 → red."""
    rows = []
    for gubun in ["유통", "생철MOU", "생압전용야드"]:
        for d in pd.date_range("2026-03-01", "2026-03-15", freq="D"):
            rows.append({"날짜": d.date(), "구분": gubun, "구매item": "A", "등급대분류": "X", "입하량(net)": 50.0})
        for d in pd.date_range("2026-02-01", "2026-02-28", freq="D"):
            rows.append({"날짜": d.date(), "구분": gubun, "구매item": "A", "등급대분류": "X", "입하량(net)": 100.0})
    df = pd.DataFrame(rows)
    result = build_gubun_signal(df, compare="month", ref_date=datetime.date(2026, 3, 15), threshold=5.0)
    assert result["signal"]["level"] == "red"

def test_build_gubun_signal_yellow_incentive():
    """유통 일평균 증가, MOU 일평균 대폭 감소 → yellow + 인센티브."""
    rows = []
    # 유통: 당기 130t/일, 전기 100t/일 → 증가 (not decreasing)
    for d in pd.date_range("2026-03-01", "2026-03-15", freq="D"):
        rows.append({"날짜": d.date(), "구분": "유통", "구매item": "A", "등급대분류": "X", "입하량(net)": 130.0})
    for d in pd.date_range("2026-02-01", "2026-02-28", freq="D"):
        rows.append({"날짜": d.date(), "구분": "유통", "구매item": "A", "등급대분류": "X", "입하량(net)": 100.0})
    # MOU: 당기 40t/일, 전기 100t/일 → 대폭 감소
    for d in pd.date_range("2026-03-01", "2026-03-15", freq="D"):
        rows.append({"날짜": d.date(), "구분": "생철MOU", "구매item": "A", "등급대분류": "X", "입하량(net)": 40.0})
    for d in pd.date_range("2026-02-01", "2026-02-28", freq="D"):
        rows.append({"날짜": d.date(), "구분": "생철MOU", "구매item": "A", "등급대분류": "X", "입하량(net)": 100.0})
    df = pd.DataFrame(rows)
    result = build_gubun_signal(df, compare="month", ref_date=datetime.date(2026, 3, 15), threshold=5.0)
    assert result["signal"]["level"] == "yellow"
    assert "인센티브" in result["signal"]["message"]

def test_build_gubun_signal_green():
    """유통·MOU 모두 일평균 증가 → green."""
    rows = []
    for gubun in ["유통", "생철MOU"]:
        for d in pd.date_range("2026-03-01", "2026-03-15", freq="D"):
            rows.append({"날짜": d.date(), "구분": gubun, "구매item": "A", "등급대분류": "X", "입하량(net)": 120.0})
        for d in pd.date_range("2026-02-01", "2026-02-28", freq="D"):
            rows.append({"날짜": d.date(), "구분": gubun, "구매item": "A", "등급대분류": "X", "입하량(net)": 100.0})
    df = pd.DataFrame(rows)
    result = build_gubun_signal(df, compare="month", ref_date=datetime.date(2026, 3, 15), threshold=5.0)
    assert result["signal"]["level"] == "green"

def test_build_gubun_signal_by_grade_group(sample_receipt):
    result = build_gubun_signal(sample_receipt, compare="month", ref_date=datetime.date(2026, 3, 15))
    assert len(result["by_grade_group"]) > 0

def test_build_gubun_signal_site_filter(sample_receipt):
    df = sample_receipt.copy()
    df["사소구분"] = "포항소"
    result_all = build_gubun_signal(df, compare="month", ref_date=datetime.date(2026, 3, 15))
    result_pohang = build_gubun_signal(df, compare="month", ref_date=datetime.date(2026, 3, 15), site="포항소")
    assert result_all["by_group"] == result_pohang["by_group"]

def test_build_gubun_signal_week(sample_receipt):
    result = build_gubun_signal(sample_receipt, compare="week", ref_date=datetime.date(2026, 3, 15))
    assert "by_group" in result
    assert "signal" in result


def test_build_gubun_signal_yellow_distribution_down():
    """유통 일평균 대폭 감소, MOU 일평균 증가 → yellow + 기본가."""
    rows = []
    # 유통: 당기 40t/일, 전기 100t/일 → 대폭 감소
    for d in pd.date_range("2026-03-01", "2026-03-15", freq="D"):
        rows.append({"날짜": d.date(), "구분": "유통", "구매item": "A", "등급대분류": "X", "입하량(net)": 40.0})
    for d in pd.date_range("2026-02-01", "2026-02-28", freq="D"):
        rows.append({"날짜": d.date(), "구분": "유통", "구매item": "A", "등급대분류": "X", "입하량(net)": 100.0})
    # MOU: 당기 130t/일, 전기 100t/일 → 증가 (not decreasing)
    for d in pd.date_range("2026-03-01", "2026-03-15", freq="D"):
        rows.append({"날짜": d.date(), "구분": "생철MOU", "구매item": "A", "등급대분류": "X", "입하량(net)": 130.0})
    for d in pd.date_range("2026-02-01", "2026-02-28", freq="D"):
        rows.append({"날짜": d.date(), "구분": "생철MOU", "구매item": "A", "등급대분류": "X", "입하량(net)": 100.0})
    df = pd.DataFrame(rows)
    result = build_gubun_signal(df, compare="month", ref_date=datetime.date(2026, 3, 15), threshold=5.0)
    assert result["signal"]["level"] == "yellow"
    assert "기본가" in result["signal"]["message"]


def test_build_gubun_signal_gray_no_prev_data():
    """전기 데이터 없음 (당월 데이터만) → gray."""
    rows = []
    for d in pd.date_range("2026-03-01", "2026-03-10", freq="D"):
        rows.append({"날짜": d.date(), "구분": "유통", "구매item": "A", "등급대분류": "X", "입하량(net)": 100.0})
    df = pd.DataFrame(rows)
    result = build_gubun_signal(df, compare="month", ref_date=datetime.date(2026, 3, 15), threshold=5.0)
    assert result["signal"]["level"] == "gray"


def test_build_gubun_signal_returns_date_keys(sample_receipt):
    """반환 dict에 cur_start, cur_end, prev_start, prev_end 포함."""
    result = build_gubun_signal(sample_receipt, compare="month", ref_date=datetime.date(2026, 3, 15))
    assert result["cur_start"] == datetime.date(2026, 3, 1)
    assert result["cur_end"] == datetime.date(2026, 3, 15)
    assert result["prev_start"] == datetime.date(2026, 2, 1)
    assert result["prev_end"] == datetime.date(2026, 2, 28)


def test_build_gubun_signal_week_date_range():
    """compare='week': 이번 주 일요일~ref_date, 전주 일~토 범위 정확성."""
    rows = []
    rows.append({"날짜": datetime.date(2026, 3, 15), "구분": "유통", "구매item": "A", "등급대분류": "X", "입하량(net)": 100.0})
    df = pd.DataFrame(rows)
    result = build_gubun_signal(df, compare="week", ref_date=datetime.date(2026, 3, 15))
    assert result["cur_start"] == datetime.date(2026, 3, 15)
    assert result["cur_end"] == datetime.date(2026, 3, 15)
    assert result["prev_end"] == datetime.date(2026, 3, 14)


def test_count_working_days_basic():
    """2026-03-01(일, 삼일절) ~ 2026-03-15: 3/1은 일요일이므로 영업일 아님."""
    wdays = _count_working_days(datetime.date(2026, 3, 1), datetime.date(2026, 3, 15))
    # 3/2~3/6(5일) + 3/9~3/13(5일) = 10일 (삼일절은 일요일 → 추가 제외 없음)
    assert wdays == 10

def test_count_working_days_min_one():
    """영업일이 0이 되면 max(count, 1) = 1 반환."""
    # 2026-03-07(토) ~ 2026-03-08(일): 영업일 0 → 1
    wdays = _count_working_days(datetime.date(2026, 3, 7), datetime.date(2026, 3, 8))
    assert wdays == 1
