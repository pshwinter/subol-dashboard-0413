# dashboard/app.py
import io
import re
import calendar
import datetime
import smtplib
from collections import defaultdict
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from langchain_core.messages import HumanMessage, AIMessage
import streamlit as st
import pandas as pd
from pipeline.loader import load_workbooks, build_gubun_classifier, classify_gubun_series
from pipeline.metrics import bucket_metrics
from pipeline.supplier import build_supplier_summary
from pipeline.rag import build_chunks, RAGRetriever
from pipeline.graph import build_graph
from dashboard.charts import make_monthly_chart, make_receipt_detail_bar, make_multi_month_bar, make_comparison_bar, make_gubun_signal_bar
from report.exporter import export_workbook_bytes

from pipeline.transform import SITE_MAP, standardize_expected_df
from pipeline.gubun_signal import build_gubun_signal


_LOAD_VERSION = "v11"   # 코드 변경 시 올려서 캐시 강제 무효화

# 숫자·증감% 색상 강조 패턴 (모듈 레벨 컴파일 — _colorize() 공용)
_COLORIZE_PATTERN = re.compile(r'(\+[\d.]+%)|(-[\d.]+%)|([\d,]+(?:\.\d+)?)')


@st.cache_data
def load_all(data_bytes: bytes, ref_bytes: bytes, _version: str = _LOAD_VERSION):
    data = load_workbooks(
        data_path=io.BytesIO(data_bytes),
        ref_path=io.BytesIO(ref_bytes),
    )
    daily    = bucket_metrics(data)["daily"]
    supplier = build_supplier_summary(data.receipt, data.ref)
    supplier_gubuns, gubun_grades = build_gubun_classifier(data.ref, data.ref2)

    # 등급대분류 컬럼명 자동 탐색 (공백 유무 무관)
    gr = data.grade_ref.copy()
    col_map = {c: c.replace(" ", "") for c in gr.columns}
    gr = gr.rename(columns=col_map)
    if "등급대분류" not in gr.columns:
        raise ValueError(
            f"등급구분 시트에 '등급대분류' 컬럼이 없습니다. 실제 컬럼: {list(data.grade_ref.columns)}"
        )
    grade_lookup = gr.set_index("등급")["등급대분류"].to_dict()

    # 계획 比 계산을 위한 원본 예상 데이터 (실적 날짜 제거 이전 전체)
    exp_recv = standardize_expected_df(data.exp_receipt)
    exp_use  = standardize_expected_df(data.exp_usage)

    return daily, supplier, data.receipt, supplier_gubuns, gubun_grades, grade_lookup, exp_recv, exp_use, data.region_ref


def _inject_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;700;800&family=Inter:wght@400;500;600;700&display=swap');

    /* ── Base ── */
    html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }
    .stApp { background: #f0f4f8 !important; }
    .main .block-container { padding-top: 1.5rem !important; max-width: 1600px !important; }

    /* ── Sidebar ── */
    [data-testid="stSidebar"] > div:first-child {
        background: linear-gradient(180deg, #0f2341 0%, #1a3560 100%) !important;
    }
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span { color: #cbd5e1 !important; }
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {
        color: #f1f5f9 !important;
        font-family: 'Manrope', sans-serif !important;
    }
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
        background: rgba(255,255,255,0.07) !important;
        border: 1px dashed rgba(255,255,255,0.25) !important;
        border-radius: 0.5rem !important;
    }
    [data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.1) !important; }

    /* ── Headers ── */
    h1 {
        font-family: 'Manrope', sans-serif !important;
        font-weight: 800 !important;
        color: #00288e !important;
        letter-spacing: -0.02em !important;
        font-size: 2.25rem !important;
    }
    h2 {
        font-family: 'Manrope', sans-serif !important;
        font-weight: 700 !important;
        color: #00288e !important;
        font-size: 2rem !important;
        border-bottom: 2px solid #e4e9ed;
        padding-bottom: 0.4rem;
    }
    h3 {
        font-family: 'Manrope', sans-serif !important;
        font-weight: 600 !important;
        color: #171c1f !important;
    }

    /* ── Caption ── */
    [data-testid="stCaptionContainer"] p {
        color: #757684 !important;
        font-size: 0.7rem !important;
        text-transform: uppercase !important;
        letter-spacing: 0.07em !important;
        font-weight: 600 !important;
    }

    /* ── Download / Primary Buttons ── */
    [data-testid="stDownloadButton"] > button,
    [data-testid="stBaseButton-primary"] {
        background: linear-gradient(135deg, #00288e, #1e40af) !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 0.375rem !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 700 !important;
        box-shadow: 0 2px 8px rgba(0,40,142,0.3) !important;
        transition: all 0.2s !important;
    }
    [data-testid="stDownloadButton"] > button:hover,
    [data-testid="stBaseButton-primary"]:hover {
        box-shadow: 0 4px 14px rgba(0,40,142,0.4) !important;
        transform: translateY(-1px) !important;
    }

    /* ── Select / Multiselect ── */
    [data-baseweb="select"] > div:first-child {
        background: #ffffff !important;
        border: none !important;
        border-radius: 0.375rem !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08) !important;
    }

    /* ── Toggle ── */
    [data-testid="stToggle"] p { font-weight: 600 !important; font-size: 0.85rem !important; }

    /* ── DataFrame ── */
    [data-testid="stDataFrame"] iframe {
        border-radius: 0.75rem !important;
    }

    /* ── Divider ── */
    [data-testid="stDivider"] hr {
        border: none !important;
        height: 1px !important;
        background: linear-gradient(90deg, transparent, #dfe3e7 30%, #dfe3e7 70%, transparent) !important;
        margin: 2rem 0 !important;
    }

    /* ── Plotly chart container ── */
    [data-testid="stPlotlyChart"] {
        background: #ffffff !important;
        border-radius: 1rem !important;
        box-shadow: 0 1px 4px rgba(0,0,0,0.07) !important;
        padding: 0.5rem !important;
    }

    /* ── Chat ── */
    [data-testid="stChatMessage"] {
        border-radius: 0.75rem !important;
        background: #ffffff !important;
    }
    </style>
    """, unsafe_allow_html=True)


def _preprocess_receipt(
    receipt_raw: pd.DataFrame,
    grade_lookup: dict,
    supplier_gubuns: dict,
    gubun_grades: dict,
    region_ref: pd.DataFrame,
) -> pd.DataFrame:
    """receipt_raw에 사소구분·날짜·등급대분류·구분·지역 컬럼을 추가해 반환."""
    receipt = receipt_raw.copy()
    receipt["사소구분"] = receipt["사소구분"].map(SITE_MAP)
    receipt["날짜"] = (
        pd.to_datetime(receipt["입하일시"]) - pd.Timedelta(hours=7)
    ).dt.date
    receipt["등급대분류"] = receipt["등급"].map(grade_lookup)
    receipt["구분"] = classify_gubun_series(receipt, supplier_gubuns, gubun_grades)
    if not region_ref.empty:
        receipt = receipt.merge(
            region_ref[["공급사", "지역대구분", "지역소구분"]].drop_duplicates("공급사"),
            on="공급사", how="left",
        )
    return receipt


def _last_inv(df: pd.DataFrame, group_cols) -> float:
    """df를 날짜 기준 정렬 후 group_cols별 마지막 재고 합산."""
    if df.empty:
        return 0.0
    return float(df.sort_values("date").groupby(group_cols)["inv"].last().sum())


def _pct_str(value: float, baseline: float, label: str) -> str:
    """증감률 문자열 반환. baseline=0이면 빈 문자열."""
    if baseline <= 0:
        return ""
    pct = (value - baseline) / baseline * 100
    return f"{label} {'+' if pct >= 0 else ''}{pct:.0f}%"


def _colorize(text: str) -> str:
    """숫자·증감% 색상 강조 (단일 패스, 중복 없음)."""
    _NUM_COLOR  = "#1D4ED8"   # 숫자 — 브랜드 블루
    _POS_COLOR  = "#16a34a"   # +% — 초록
    _NEG_COLOR  = "#dc2626"   # -% — 빨강
    buf, i = [], 0
    for m in _COLORIZE_PATTERN.finditer(text):
        buf.append(text[i:m.start()])
        if m.group(1):
            buf.append(f'<span style="color:{_POS_COLOR};font-weight:700">{m.group(1)}</span>')
        elif m.group(2):
            buf.append(f'<span style="color:{_NEG_COLOR};font-weight:700">{m.group(2)}</span>')
        else:
            buf.append(f'<span style="color:{_NUM_COLOR};font-weight:700">{m.group(3)}</span>')
        i = m.end()
    buf.append(text[i:])
    return "".join(buf)


def _build_receipt_mask(
    receipt: pd.DataFrame,
    f_site: str,
    f_gubun: list,
    f_supplier: list,
    f_item: list,
    f_grade_cat: list,
    f_grade: list,
) -> pd.Series:
    """입고 상세 공통 필터 마스크 (날짜 제외)."""
    mask = pd.Series(True, index=receipt.index)
    if f_site != "전체":
        mask &= receipt["사소구분"] == f_site
    if f_gubun:
        mask &= receipt["구분"].isin(f_gubun)
    if f_supplier and "합계" not in f_supplier:
        mask &= receipt["공급사"].isin(f_supplier)
    if f_item and "합계" not in f_item:
        mask &= receipt["구매item"].isin(f_item)
    if f_grade_cat and "합계" not in f_grade_cat:
        mask &= receipt["등급대분류"].isin(f_grade_cat)
    if f_grade and "합계" not in f_grade:
        mask &= receipt["등급"].isin(f_grade)
    return mask


def _render_summary_box(text: str):
    """요약 박스 렌더링 — KPI 카드(총계+사소 포함) + 등급 서브라인."""
    lines = text.split("\n")
    if not lines:
        return

    SEP = " / "

    # ── 괄호 안 내용 → pill 변환 헬퍼 ────────────────────────────
    def _pillify(s: str) -> str:
        colored = _colorize(s)
        def _pill(m):
            pills = []
            for part in m.group(1).split(", "):
                part = part.strip()
                col = "#16a34a" if part.startswith("+") else ("#dc2626" if part.startswith("-") else "#444653")
                pills.append(
                    f'<span style="background:rgba(0,0,0,0.07);color:{col};'
                    f'border-radius:99px;padding:1px 7px;font-size:0.7rem;font-weight:700;white-space:nowrap">'
                    f'{part}</span>'
                )
            return " " + " ".join(pills)
        return re.sub(r'\(([^)]+)\)', _pill, colored)

    # ── 총계 라인 파싱 ─────────────────────────────────────────
    main_segs = lines[0].split(SEP)   # [입고…, 사용…, 재고…]

    # ── 사소 라인 파싱: {사이트명: [입고_seg, 사용_seg, 재고_seg]} ──
    site_data: dict[str, list[str]] = {}
    grade_lines: list[str] = []

    for line in lines[1:]:
        if line.startswith("__SITE__"):
            content = line[len("__SITE__"):]
            parts = content.split(SEP)
            # 첫 파트: "광양 : 입고 xx톤 (...)"
            colon_idx = parts[0].find(" : ")
            if colon_idx >= 0:
                site_name = parts[0][:colon_idx]
                recv_seg  = parts[0][colon_idx + 3:]
            else:
                site_name = "?"
                recv_seg  = parts[0]
            use_seg = parts[1] if len(parts) > 1 else ""
            inv_seg = parts[2] if len(parts) > 2 else ""
            site_data[site_name] = [recv_seg, use_seg, inv_seg]
        elif line.startswith("__GRADE__"):
            grade_lines.append(line[len("__GRADE__"):])

    # ── 카드 메타 ──────────────────────────────────────────────
    CARD_META = [
        ("#00288e", "#eef2ff"),   # 입고 — 딥 블루
        ("#92400e", "#fffbeb"),   # 사용 — 앰버
        ("#1e3a5f", "#f0f5ff"),   # 재고 — 다크 슬레이트
    ]

    card_html = ""
    for i, main_seg in enumerate(main_segs[:3]):
        accent, bg = CARD_META[i]

        # 총계 행
        total_html = (
            f'<div style="font-size:0.92rem;font-weight:600;color:#1e293b;line-height:1.7">'
            f'{_pillify(main_seg)}</div>'
        )

        # 사소 행
        site_rows = ""
        for site_name, segs in site_data.items():
            seg = segs[i] if i < len(segs) else ""
            site_rows += (
                f'<div style="display:flex;align-items:center;gap:6px;'
                f'padding:3px 0;border-top:1px solid rgba(0,0,0,0.05);margin-top:4px">'
                f'<span style="font-size:0.7rem;font-weight:700;color:{accent};'
                f'white-space:nowrap;min-width:28px">▸ {site_name}</span>'
                f'<span style="font-size:0.78rem;color:#475569;line-height:1.5">{_pillify(seg)}</span>'
                f'</div>'
            )

        card_html += (
            f'<div style="flex:1;background:{bg};border-radius:0.75rem;padding:14px 18px;'
            f'position:relative;overflow:hidden;min-width:0;">'
            f'<div style="position:absolute;top:0;left:0;width:4px;height:100%;'
            f'background:{accent};border-radius:4px 0 0 4px;"></div>'
            f'<div style="padding-left:10px">'
            f'{total_html}'
            f'{site_rows}'
            f'</div>'
            f'</div>'
        )

    # ── 등급 서브라인 (카드 하단) ──────────────────────────────
    grade_html = ""
    if grade_lines:
        grade_parts = "".join(
            f'<div style="display:flex;gap:6px;padding:3px 0;font-size:0.8rem;color:#334155">'
            f'<span style="color:#d97706;font-weight:700">◆</span>'
            f'<span>{_colorize(g).replace(SEP, "&ensp;<b>|</b>&ensp;")}</span></div>'
            for g in grade_lines
        )
        grade_html = (
            f'<div style="background:#ffffff;border-radius:0.75rem;padding:10px 16px;'
            f'margin-top:10px;box-shadow:0 1px 3px rgba(0,0,0,0.05);">'
            f'{grade_parts}</div>'
        )

    st.markdown(
        f'<div style="display:flex;gap:12px;margin-bottom:4px;">{card_html}</div>'
        f'{grade_html}',
        unsafe_allow_html=True,
    )


def _monthly_summary(
    daily_all: pd.DataFrame,
    target_month=None,
    exp_recv: pd.DataFrame | None = None,
    exp_use:  pd.DataFrame | None = None,
) -> str:
    """월간 추이 섹션용 요약 텍스트 생성.

    daily_all   : 전 기간 데이터 (전월比 계산용으로 전월 포함)
    target_month: 표시 기준 월 (pd.Period). None이면 실적 최신 월 사용.
    exp_recv    : 원본 예상입고량 (실적 날짜 제거 이전) — 계획 比 계산용
    exp_use     : 원본 예상사용량 — 계획 比 계산용
    """
    if daily_all.empty:
        return "데이터 없음"

    is_actual_mask = daily_all["is_actual"].fillna(False).astype(bool)
    actual_all = daily_all[is_actual_mask].copy()
    plan       = daily_all[~is_actual_mask].copy()   # copy: 원본 daily 변경 방지

    if actual_all.empty:
        return "실적 데이터 없음"

    actual_all["month"] = pd.to_datetime(actual_all["date"]).dt.to_period("M")
    months_sorted = actual_all["month"].sort_values().unique()

    # 표시 기준 월 결정
    current_month = target_month if target_month is not None else months_sorted[-1]

    actual = actual_all[actual_all["month"] == current_month]   # 선택 월 실적만
    if actual.empty:
        return f"{current_month} 실적 데이터 없음"

    # 실적 마지막 날짜 (해당 월 내 몇 일치 실적인지)
    last_actual_date = pd.Timestamp(actual["date"].max())
    actual_day = last_actual_date.day  # 예: 3월 20일이면 20

    # plan_month: 선택 월 전체 계획 (monthly daily 기반, 월말f 재고용)
    if not plan.empty:
        plan["month"] = pd.to_datetime(plan["date"]).dt.to_period("M")
        plan_month = plan[plan["month"] == current_month].copy()
    else:
        plan_month = pd.DataFrame()

    # 계획 比용: 원본 예상 데이터에서 선택 월 1일 ~ 마지막 실적 날짜 합산
    # (daily의 plan은 실적 있는 날이 제거되어 있어 합산이 과소 추정됨)
    def _plan_qty(exp_df: pd.DataFrame | None, site: str | None = None) -> float:
        if exp_df is None or exp_df.empty:
            return 0.0
        exp_dates = pd.to_datetime(exp_df["date"])
        mask = (exp_dates.dt.to_period("M") == current_month) & (exp_dates <= last_actual_date)
        if site:
            mask &= exp_df["사소구분"] == site
        return float(exp_df.loc[mask, "qty"].sum())

    recv_sum    = actual["recv_qty"].sum()
    use_sum     = actual["use_qty"].sum()
    current_inv = _last_inv(actual, ["사소구분", "구매item"])

    recv_notes: list[str] = []
    use_notes:  list[str] = []

    prev_month  = current_month - 1
    actual_prev = actual_all[actual_all["month"] == prev_month]
    if not actual_prev.empty:
        prev_cal_days = calendar.monthrange(prev_month.year, prev_month.month)[1]
        adj_recv = actual_prev["recv_qty"].sum() / prev_cal_days * actual_day
        adj_use  = actual_prev["use_qty"].sum()  / prev_cal_days * actual_day
        if s := _pct_str(recv_sum, adj_recv, "전월 比"): recv_notes.append(s)
        if s := _pct_str(use_sum,  adj_use,  "전월 比"): use_notes.append(s)

    if s := _pct_str(recv_sum, _plan_qty(exp_recv), "계획 比"): recv_notes.append(s)
    if s := _pct_str(use_sum,  _plan_qty(exp_use),  "계획 比"): use_notes.append(s)

    recv_label = f"입고 {recv_sum:,.0f}톤" + (f" ({', '.join(recv_notes)})" if recv_notes else "")
    use_label  = f"사용 {use_sum:,.0f}톤"  + (f" ({', '.join(use_notes)})"  if use_notes  else "")

    inv_label = f"재고 {current_inv:,.0f}톤"
    if not plan_month.empty:
        expected_inv = _last_inv(plan_month, ["사소구분", "구매item"])
        prev_inv_m   = _last_inv(actual_prev, ["사소구분", "구매item"])
        inv_notes = [f"월말f {expected_inv:,.0f}"]
        if s := _pct_str(expected_inv, prev_inv_m, "전월 比"): inv_notes.append(s)
        inv_label += f" ({', '.join(inv_notes)})"

    SEP = " / "
    summary = SEP.join([recv_label, use_label, inv_label])

    # 사소별 한 줄 요약
    site_lines = []
    for site in sorted(actual["사소구분"].unique()):
        site_display = site[:-1] if site.endswith("소") else site
        a_s      = actual[actual["사소구분"] == site]
        recv_s   = a_s["recv_qty"].sum()
        use_s    = a_s["use_qty"].sum()
        inv_s    = _last_inv(a_s, "구매item")
        a_s_prev = actual_prev[actual_prev["사소구분"] == site] if not actual_prev.empty else pd.DataFrame()

        recv_s_notes: list[str] = []
        use_s_notes:  list[str] = []

        if not a_s_prev.empty:
            prev_cal_days_s = calendar.monthrange(prev_month.year, prev_month.month)[1]
            adj_r = a_s_prev["recv_qty"].sum() / prev_cal_days_s * actual_day
            adj_u = a_s_prev["use_qty"].sum()  / prev_cal_days_s * actual_day
            if s := _pct_str(recv_s, adj_r, "전월 比"): recv_s_notes.append(s)
            if s := _pct_str(use_s,  adj_u, "전월 比"): use_s_notes.append(s)

        if s := _pct_str(recv_s, _plan_qty(exp_recv, site), "계획 比"): recv_s_notes.append(s)
        if s := _pct_str(use_s,  _plan_qty(exp_use,  site), "계획 比"): use_s_notes.append(s)

        inv_s_label = f"재고 {inv_s:,.0f}톤"
        if not plan_month.empty:
            p_s_m = plan_month[plan_month["사소구분"] == site]
            if not p_s_m.empty:
                exp_s      = _last_inv(p_s_m, "구매item")
                prev_inv_s = _last_inv(a_s_prev, "구매item")
                inv_s_notes = [f"월말f {exp_s:,.0f}"]
                if s := _pct_str(exp_s, prev_inv_s, "전월 比"): inv_s_notes.append(s)
                inv_s_label += f" ({', '.join(inv_s_notes)})"

        recv_s_label = f"입고 {recv_s:,.0f}톤" + (f" ({', '.join(recv_s_notes)})" if recv_s_notes else "")
        use_s_label  = f"사용 {use_s:,.0f}톤"  + (f" ({', '.join(use_s_notes)})"  if use_s_notes  else "")

        line = SEP.join([f"{site_display} : {recv_s_label}", use_s_label, inv_s_label])
        site_lines.append("__SITE__" + line)

    return "\n".join([summary] + site_lines)


def _group_gubun(values: list[str], min_prefix_len: int = 2) -> dict[str, str]:
    """구분값 목록에서 공통 접미사를 찾아 {원래값: 그룹명} 매핑 반환.

    예) ["생압전용야드","경압전용야드","생철MOU","경압MOU","유통","회수"]
        → {"생압전용야드":"전용야드","경압전용야드":"전용야드",
           "생철MOU":"MOU","경압MOU":"MOU","유통":"유통","회수":"회수"}

    우선순위: 긴 접미사 > 짧은 접미사 (더 의미있는 그룹명 선택)
    조건: 접두사(prefix) 길이 >= min_prefix_len
    """
    suffix_to_members: dict[str, set] = defaultdict(set)
    for v in values:
        for slen in range(2, len(v) - min_prefix_len + 1):
            suffix_to_members[v[-slen:]].add(v)

    # 2개 이상 공유하는 접미사만 후보
    candidates = {s: m for s, m in suffix_to_members.items() if len(m) >= 2}

    assignment: dict[str, str] = {}
    # 긴 접미사부터 배정 (전용야드 4자 > 용야드 3자 > 야드 2자)
    for suffix in sorted(candidates, key=len, reverse=True):
        unassigned = [v for v in candidates[suffix] if v not in assignment]
        if len(unassigned) >= 2:
            for v in unassigned:
                assignment[v] = suffix

    for v in values:
        if v not in assignment:
            assignment[v] = v
    return assignment


def _receipt_summary(filtered: pd.DataFrame, start_date, end_date, receipt_all=None) -> str:
    """입고 상세 섹션용 요약 텍스트 생성."""
    if filtered.empty:
        return ""

    total  = filtered["입하량(net)"].sum()
    count  = len(filtered)
    days   = max((end_date - start_date).days + 1, 1)
    avg    = total / days

    SEP = " / "
    total_label = f"총 입고 {total:,.0f}톤"

    # 전월 比 (일 평균 기준)
    if receipt_all is not None:
        prev_end   = start_date.replace(day=1) - datetime.timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        prev_days  = max((prev_end - prev_start).days + 1, 1)
        prev_f = receipt_all[
            (receipt_all["날짜"] >= prev_start) & (receipt_all["날짜"] <= prev_end)
        ]
        if not prev_f.empty:
            prev_avg = prev_f["입하량(net)"].sum() / prev_days
            if prev_avg > 0:
                pct = (avg - prev_avg) / prev_avg * 100
                total_label += f" (전월 比 {'+' if pct >= 0 else ''}{pct:.0f}%)"

    lines = [SEP.join([
        total_label,
        f"입고 건수 {count:,}건",
        f"일 평균 {avg:,.0f}톤",
    ])]

    # 구분별 합계 — 공통 접미사로 묶어 표시
    # 예) 생압전용야드+경압전용야드 → 전용야드(생압 x톤, 경압 x톤)
    if "구분" in filtered.columns:
        gubun_qty = (
            filtered.groupby("구분")["입하량(net)"].sum()
            .sort_values(ascending=False)
        )
        gubun_qty = gubun_qty[gubun_qty > 0]
        if not gubun_qty.empty:
            group_map = _group_gubun(gubun_qty.index.tolist())

            # 그룹별 집계 (순서: 그룹 총량 내림차순)
            group_totals: dict[str, float] = defaultdict(float)
            group_members: dict[str, list] = defaultdict(list)  # group → [(prefix, qty)]
            for g, qty in gubun_qty.items():
                grp = group_map[g]
                group_totals[grp] += qty
                prefix = g[: len(g) - len(grp)] if g != grp else ""
                group_members[grp].append((prefix, qty))

            sorted_groups = sorted(group_totals.items(), key=lambda x: x[1], reverse=True)
            gubun_parts = []
            for grp, grp_total in sorted_groups:
                members = group_members[grp]
                if len(members) > 1:
                    # 접두사별 세부내역 (수량 내림차순)
                    members_sorted = sorted(members, key=lambda x: x[1], reverse=True)
                    inner = ", ".join(
                        f"{pfx} {qty:,.0f}톤" if pfx else f"{grp} {qty:,.0f}톤"
                        for pfx, qty in members_sorted
                    )
                    gubun_parts.append(f"{grp}({inner})")
                else:
                    gubun_parts.append(f"{grp} {grp_total:,.0f}톤")
            lines.append(SEP.join(gubun_parts))

    # 국내 / 수입 분리
    has_gubun = "구분" in filtered.columns
    import_df  = filtered[filtered["구분"] == "수입"] if has_gubun else pd.DataFrame()
    domestic_df = filtered[filtered["구분"] != "수입"] if has_gubun else filtered

    # 국내: 등급대분류 상위 4개, 각 등급대분류별 공급사 상위 2개
    if "등급대분류" in domestic_df.columns and not domestic_df.empty:
        dom_total = domestic_df["입하량(net)"].sum()
        grade_qty = (
            domestic_df.groupby("등급대분류")["입하량(net)"].sum()
            .sort_values(ascending=False)
        )
        grade_qty = grade_qty[grade_qty.index.notna()]
        grade_parts = []
        for i, (g, q) in enumerate(grade_qty.head(7).items()):
            if i < 2:
                sup_qty = (
                    domestic_df[domestic_df["등급대분류"] == g]
                    .groupby("공급사")["입하량(net)"].sum()
                    .sort_values(ascending=False)
                    .head(2)
                )
                sup_str = ", ".join(f"{n}({sq:,.0f}톤)" for n, sq in sup_qty.items())
                grade_parts.append(f"<b>{g}</b>({q:,.0f}톤)[{sup_str}]")
            else:
                grade_parts.append(f"<b>{g}</b>({q:,.0f}톤)")
        lines.append(f"__GRADE__<b>국내</b>({dom_total:,.0f}톤) : {SEP.join(grade_parts)}")

    # 수입: 공급사 상위 2개를 한 줄로
    if not import_df.empty:
        imp_total = import_df["입하량(net)"].sum()
        sup_qty = (
            import_df.groupby("공급사")["입하량(net)"].sum()
            .sort_values(ascending=False)
            .head(2)
        )
        sup_parts = SEP.join(f"{n}({q:,.0f}톤)" for n, q in sup_qty.items())
        lines.append(f"__GRADE__<b>수입</b>({imp_total:,.0f}톤) : {sup_parts}")

    return "\n".join(lines)


@st.cache_data(ttl=300)
def _ai_summary(summary_text: str, _api_key: str) -> str:
    """요약 수치를 GPT에 전달해 2문장 자연어 요약 생성 (5분 캐시)."""
    from openai import OpenAI

    client = OpenAI(api_key=_api_key)
    prompt = (
        "당신은 철강 공장 수불 현황을 요약하는 전문가입니다.\n"
        "아래 현황 수치를 바탕으로 2문장 이내 한국어로 핵심을 요약하세요.\n"
        "수치는 그대로 사용하고, 추측하지 마세요.\n\n"
        f"[현황]\n{summary_text}"
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=150,
        temperature=0.1,
        timeout=15,
    )
    if not resp.choices:
        return "AI 요약 생성 실패"
    return resp.choices[0].message.content


def _render_region_map(
    filtered: pd.DataFrame,
    map_height: int = 640,
) -> None:
    """지역대구분별 포항·광양 입고량 — 고정 크기 지도 카드."""
    import json, os, folium
    from branca.element import Figure
    from streamlit.components.v1 import html as st_html

    GEOJSON_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "korea_provinces.geojson")

    REGION_COORDS = {
        "경인": (37.41, 126.95), "경남": (35.23, 128.68),
        "경북": (36.49, 128.89), "충남": (36.52, 126.80),
        "충북": (36.99, 127.93), "전남": (34.82, 126.98),
        "전북": (35.72, 127.15), "강원": (37.55, 128.21),
        "제주": (33.49, 126.53),
    }
    POHANG_COORD    = (36.03, 129.36)
    GWANGYANG_COORD = (34.94, 127.70)
    KOREA_BOUNDS    = [[33.0, 124.5], [38.7, 130.0]]
    SHADOW = "1px 1px 2px #fff,-1px -1px 2px #fff,1px -1px 2px #fff,-1px 1px 2px #fff"

    # GeoJSON name_eng → 지역대구분 매핑
    ENG_TO_REGION = {
        "Seoul": "경인", "Incheon": "경인", "Gyeonggi-do": "경인",
        "Busan": "경남", "Ulsan": "경남", "Gyeongsangnam-do": "경남",
        "Daegu": "경북", "Gyeongsangbuk-do": "경북",
        "Daejeon": "충남", "Chungcheongnam-do": "충남", "Sejongsi": "충남",
        "Chungcheongbuk-do": "충북",
        "Gwangju": "전남", "Jeollanam-do": "전남",
        "Jeollabuk-do": "전북",
        "Gangwon-do": "강원",
        "Jeju-do": "제주",
    }

    agg = (
        filtered.groupby(["사소구분", "지역대구분"])["입하량(net)"]
        .sum().reset_index()
    )
    pohang    = agg[agg["사소구분"] == "포항소"].set_index("지역대구분")["입하량(net)"]
    gwangyang = agg[agg["사소구분"] == "광양소"].set_index("지역대구분")["입하량(net)"]

    # 지역대구분별 합계 (포항+광양) → choropleth 색상 계산용
    region_total = {
        r: pohang.get(r, 0) + gwangyang.get(r, 0)
        for r in REGION_COORDS
    }
    max_vol = max(region_total.values()) if region_total else 1

    def _blue(vol: float) -> str:
        """납품량 → 파란색 계열 hex (#dbeafe 연→ #1e3a8a 진)"""
        frac = min(vol / max_vol, 1.0) if max_vol > 0 else 0
        r = int(219 + (30  - 219) * frac)
        g = int(234 + (58  - 234) * frac)
        b = int(254 + (138 - 254) * frac)
        return f"#{r:02x}{g:02x}{b:02x}"

    # 요약 수치 (박스 상단)
    st.markdown(
        f'<div style="display:flex;gap:16px;margin-bottom:8px;">'
        f'<div style="flex:1;background:#e8f0fe;border-radius:8px;padding:10px 14px;border-left:4px solid #1565C0">'
        f'<div style="font-size:0.7rem;font-weight:700;color:#1565C0;text-transform:uppercase;letter-spacing:.05em">포항 입고</div>'
        f'<div style="font-size:1.1rem;font-weight:800;color:#1565C0">{pohang.sum():,.0f} t</div></div>'
        f'<div style="flex:1;background:#fde8e8;border-radius:8px;padding:10px 14px;border-left:4px solid #b71c1c">'
        f'<div style="font-size:0.7rem;font-weight:700;color:#b71c1c;text-transform:uppercase;letter-spacing:.05em">광양 입고</div>'
        f'<div style="font-size:1.1rem;font-weight:800;color:#b71c1c">{gwangyang.sum():,.0f} t</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # folium 지도 — Figure로 실제 지도 크기 지정, 인터랙션 비활성화
    fig = Figure(width="100%", height=f"{map_height}px")
    m = folium.Map(
        location=[36.0, 130.0], zoom_start=7, tiles=None,
        zoom_control=False, dragging=False,
        scrollWheelZoom=False, doubleClickZoom=False,
        touchZoom=False, keyboard=False,
        max_bounds=True,
        min_lat=KOREA_BOUNDS[0][0], max_lat=KOREA_BOUNDS[1][0],
        min_lon=KOREA_BOUNDS[0][1], max_lon=KOREA_BOUNDS[1][1],
    )
    fig.add_child(m)
    m.get_root().html.add_child(folium.Element(
        '<style>'
        '.leaflet-container{background:#f8faff!important;cursor:default!important}'
        '.leaflet-grab{cursor:default!important}'
        '</style>'
    ))

    if os.path.exists(GEOJSON_PATH):
        with open(GEOJSON_PATH, encoding="utf-8") as f:
            korea_geo = json.load(f)

        def _style_fn(feature):
            eng    = feature["properties"].get("name_eng", "")
            region = ENG_TO_REGION.get(eng)
            vol    = region_total.get(region, 0) if region else 0
            return {
                "fillColor":   _blue(vol),
                "color":       "#4a5568",
                "weight":      1.0,
                "fillOpacity": 0.80 if vol > 0 else 0.25,
            }

        folium.GeoJson(korea_geo, style_function=_style_fn).add_to(m)

        # 범례 (색상 그라디언트 바)
        legend_html = (
            '<div style="position:fixed;bottom:20px;left:10px;z-index:1000;'
            'background:rgba(255,255,255,0.92);border-radius:8px;padding:8px 12px;'
            'box-shadow:0 1px 4px rgba(0,0,0,0.2);font-size:11px;">'
            '<div style="font-weight:700;margin-bottom:4px;color:#333">납품량 (포항+광양)</div>'
            '<div style="display:flex;align-items:center;gap:6px;">'
            '<span style="color:#555">적음</span>'
            '<div style="width:80px;height:12px;border-radius:3px;'
            'background:linear-gradient(to right,#dbeafe,#1e3a8a);"></div>'
            '<span style="color:#555">많음</span>'
            '</div>'
            f'<div style="margin-top:3px;color:#888">최대 {max_vol:,.0f} t</div>'
            '</div>'
        )
        m.get_root().html.add_child(folium.Element(legend_html))

    m.fit_bounds(KOREA_BOUNDS)

    # 포항·광양 마커
    for coord, label, color in [
        (POHANG_COORD, "포항", "#1565C0"), (GWANGYANG_COORD, "광양", "#b71c1c")
    ]:
        folium.Marker(coord, icon=folium.DivIcon(
            html=(f'<div style="font-size:18px;font-weight:bold;color:{color};'
                  f'text-shadow:{SHADOW}">★ {label}</div>'),
            icon_size=(60, 20), icon_anchor=(30, 10),
        )).add_to(m)

    # 지역별 물량 레이블
    for region, coord in REGION_COORDS.items():
        vol_p = pohang.get(region, 0)
        vol_g = gwangyang.get(region, 0)
        if vol_p <= 0 and vol_g <= 0:
            continue
        rows = [f'<div style="color:#333;font-weight:bold;font-size:15px">{region}</div>']
        if vol_p > 0:
            rows.append(f'<div style="color:#1565C0;font-size:15px">포항 <b>{vol_p/1000:,.1f}</b>천t</div>')
        if vol_g > 0:
            rows.append(f'<div style="color:#b71c1c;font-size:15px">광양 <b>{vol_g/1000:,.1f}</b>천t</div>')
        n = len(rows)
        folium.Marker(coord, icon=folium.DivIcon(
            html=(f'<div style="line-height:1.4;text-shadow:{SHADOW};white-space:nowrap">'
                  + "".join(rows) + "</div>"),
            icon_size=(160, n * 14), icon_anchor=(0, n * 7),
        )).add_to(m)

    # Figure HTML로 렌더링 (실제 지도 높이 = map_height)
    map_html = fig._repr_html_()
    wrapped = (
        f'<div style="background:#ffffff;border-radius:12px;overflow:hidden;'
        f'box-shadow:0 1px 6px rgba(0,0,0,0.10);width:100%;">'
        f'{map_html}'
        f'</div>'
    )
    st_html(wrapped, height=map_height + 20)


def _send_gmail(
    sender: str,
    password: str,
    recipients: list[str],
    subject: str,
    body: str,
    attachment_bytes: bytes,
    attachment_name: str,
) -> None:
    """Gmail SMTP SSL로 메일 발송 (엑셀 첨부)."""
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    part = MIMEBase("application", "octet-stream")
    part.set_payload(attachment_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{attachment_name}"')
    msg.attach(part)

    import ssl
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as smtp:
        smtp.login(sender, password)
        smtp.sendmail(sender, recipients, msg.as_string())


def _render_gubun_signal_section(receipt: pd.DataFrame, api_key: str | None = None) -> None:
    """구분별 가격정책 신호 섹션 렌더링."""
    st.header("구분별 가격정책 신호")
    st.caption("구분(유통/MOU/전용야드)별 입고량 변화 패턴으로 가격 조정 필요 여부를 감지합니다.")

    sg_c1, sg_c2, sg_c3 = st.columns([1, 1, 1])
    with sg_c1:
        sg_site_opts = (
            ["전체"] + sorted(receipt["사소구분"].dropna().unique().tolist())
            if "사소구분" in receipt.columns else ["전체"]
        )
        sg_site = st.selectbox("사소구분", sg_site_opts, key="sg_site")
    with sg_c2:
        sg_compare = st.radio("비교 기준", ["전월 대비", "전주 대비", "직접 설정"], horizontal=True, key="sg_compare")
    with sg_c3:
        sg_threshold = st.slider("임계값 (%)", min_value=1, max_value=20, value=5, key="sg_threshold")

    # 직접 설정 모드: 날짜 범위 입력
    sg_cur_period = None
    sg_prev_period = None
    if sg_compare == "직접 설정":
        _min_date = receipt["날짜"].min() if not receipt.empty else datetime.date.today() - datetime.timedelta(days=365)
        _max_date = receipt["날짜"].max() if not receipt.empty else datetime.date.today()
        dc1, dc2 = st.columns(2)
        with dc1:
            _cur_range = st.date_input(
                "당기 기간",
                value=(_max_date.replace(day=1), _max_date),
                min_value=_min_date, max_value=_max_date,
                key="sg_cur_range",
            )
        with dc2:
            _prev_start_default = (_max_date.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
            _prev_end_default   = _max_date.replace(day=1) - datetime.timedelta(days=1)
            _prev_range = st.date_input(
                "전기 기간",
                value=(_prev_start_default, _prev_end_default),
                min_value=_min_date, max_value=_max_date,
                key="sg_prev_range",
            )
        if isinstance(_cur_range, (list, tuple)) and len(_cur_range) == 2:
            sg_cur_period = (_cur_range[0], _cur_range[1])
        if isinstance(_prev_range, (list, tuple)) and len(_prev_range) == 2:
            sg_prev_period = (_prev_range[0], _prev_range[1])

    compare_key = "week" if "전주" in sg_compare else "month"
    site_filter = None if sg_site == "전체" else sg_site

    signal_data = build_gubun_signal(
        receipt,
        compare=compare_key,
        threshold=float(sg_threshold),
        site=site_filter,
        cur_period=sg_cur_period,
        prev_period=sg_prev_period,
    )

    level = signal_data["signal"]["level"]
    message = signal_data["signal"]["message"]
    period_label = (
        f"{signal_data['cur_start']} ~ {signal_data['cur_end']} "
        f"vs {signal_data['prev_start']} ~ {signal_data['prev_end']}"
    )

    LEVEL_STYLE = {
        "red":    ("🔴", "#fef2f2", "#b91c1c"),
        "yellow": ("🟡", "#fffbeb", "#92400e"),
        "green":  ("🟢", "#f0fdf4", "#166534"),
        "gray":   ("⚪", "#f8fafc", "#475569"),
    }
    icon, bg, color = LEVEL_STYLE.get(level, LEVEL_STYLE["gray"])
    st.markdown(
        f'<div style="background:{bg};border-left:4px solid {color};'
        f'border-radius:0.5rem;padding:12px 16px;margin-bottom:12px;">'
        f'<span style="font-size:1.1rem;font-weight:700;color:{color}">{icon} {message}</span>'
        f'<div style="font-size:0.75rem;color:#64748b;margin-top:4px">비교 기간: {period_label}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── 대분류×구분 상세 변화 요약 ─────────────────────────────────
    _POLICY_GUBUN_ORDER = ["유통", "MOU", "전용야드"]
    threshold_val = float(sg_threshold)

    # by_grade_group 에서 정책 구분 + 유의미한 변화만 추출
    sig_changes: dict[str, list] = defaultdict(list)   # gubun → [(grade, pct), ...]
    for k, v in signal_data.get("by_grade_group", {}).items():
        grade = k[0] if isinstance(k, tuple) else k
        gubun = k[1] if isinstance(k, tuple) else k
        if gubun in _POLICY_GUBUN_ORDER and abs(v["pct"]) >= threshold_val:
            sig_changes[gubun].append((grade, v["pct"]))

    active_gubun = [g for g in _POLICY_GUBUN_ORDER if g in sig_changes]
    if active_gubun:
        st.markdown("**대분류별 유의미한 변화**")
        detail_cols = st.columns(len(active_gubun))
        for ci, gubun in enumerate(active_gubun):
            with detail_cols[ci]:
                items_sorted = sorted(sig_changes[gubun], key=lambda x: x[1])
                rows_html = ""
                for grade, pct in items_sorted:
                    arrow = "▲" if pct > 0 else "▼"
                    color = "#16a34a" if pct > 0 else "#dc2626"
                    rows_html += (
                        f'<div style="display:flex;justify-content:space-between;'
                        f'font-size:0.82rem;padding:2px 0;">'
                        f'<span>{grade}</span>'
                        f'<span style="color:{color};font-weight:600">{arrow} {pct:+.1f}%</span>'
                        f'</div>'
                    )
                st.markdown(
                    f'<div style="border:1px solid #e2e8f0;border-radius:0.5rem;padding:10px 14px;">'
                    f'<div style="font-weight:700;font-size:0.9rem;margin-bottom:6px">{gubun}</div>'
                    f'{rows_html}</div>',
                    unsafe_allow_html=True,
                )
    else:
        st.caption(f"유의미한 변화 없음 (임계값 ±{sg_threshold}% 미만)")

    st.divider()

    _sg_tab1, _sg_tab2, _sg_tab3 = st.tabs(["구분별", "대분류별", "대분류×구분"])

    cur_label  = f"당기({signal_data['cur_start']}~{signal_data['cur_end']})"
    prev_label = f"전기({signal_data['prev_start']}~{signal_data['prev_end']})"

    with _sg_tab1:
        all_groups = {k: v for k, v in signal_data["by_group"].items()}
        if all_groups:
            with st.container(border=True):
                if any(k in all_groups for k in ("회수", "수입")):
                    st.caption("* 회수·수입은 가격 정책 영향 없음 (참고)")
                st.plotly_chart(
                    make_gubun_signal_bar(all_groups, label_current=cur_label, label_prev=prev_label),
                    use_container_width=True,
                )
        else:
            st.info("데이터 없음")

    with _sg_tab2:
        if signal_data.get("by_grade"):
            st.plotly_chart(
                make_gubun_signal_bar(signal_data["by_grade"], label_current=cur_label, label_prev=prev_label),
                use_container_width=True,
            )
        else:
            st.info("데이터 없음")

    with _sg_tab3:
        grade_policy = {
            k: v for k, v in signal_data.get("by_grade_group", {}).items()
            if (k[1] if isinstance(k, tuple) else k) not in ("회수", "수입")
        }
        if grade_policy:
            # 대분류별 총 입고량(당기+전기) 기준 내림차순 정렬
            grade_totals = {}
            for k, v in grade_policy.items():
                grade = k[0] if isinstance(k, tuple) else k
                grade_totals[grade] = grade_totals.get(grade, 0) + v["current"] + v["prev"]
            grades_order = sorted(grade_totals, key=lambda g: grade_totals[g], reverse=True)

            # 2개씩 행 배치
            for row_start in range(0, len(grades_order), 2):
                row_grades = grades_order[row_start: row_start + 2]
                cols = st.columns(len(row_grades))
                for ci, grade in enumerate(row_grades):
                    grade_subset = {k: v for k, v in grade_policy.items() if isinstance(k, tuple) and k[0] == grade}
                    with cols[ci]:
                        with st.container(border=True):
                            st.markdown(f"**{grade}**")
                            st.plotly_chart(
                                make_gubun_signal_bar(grade_subset, label_current=cur_label, label_prev=prev_label),
                                use_container_width=True,
                            )
        else:
            st.info("데이터 없음")


def render():
    st.set_page_config(page_title="철스크랩 수불현황", layout="wide")
    _inject_css()
    st.title("철스크랩 수불현황")

    # ── 사이드바 ────────────────────────────────────────────────
    st.sidebar.header("데이터 업로드")
    data_file = st.sidebar.file_uploader("수불 데이터 (.xlsx)", type=["xlsx"], key="data_upload")
    ref_file = st.sidebar.file_uploader("기준정보 (.xlsx)", type=["xlsx"], key="ref_upload")

    if not data_file or not ref_file:
        st.info("왼쪽 사이드바에서 수불 데이터와 기준정보 파일을 업로드해 주세요.")
        st.stop()

    try:
        daily, supplier_df, receipt_raw, supplier_gubuns, gubun_grades, grade_lookup, exp_recv_all, exp_use_all, region_ref = load_all(
            data_file.read(), ref_file.read()
        )
    except Exception as e:
        import traceback
        st.error(f"파일 로딩 오류: {e}")
        with st.expander("상세 오류 (디버그용)"):
            st.code(traceback.format_exc())
        st.stop()

    # ── 데이터 다운로드 placeholder (선택월 확정 후 채워짐) ─────────
    st.sidebar.divider()
    _download_slot = st.sidebar.container()

    # ── 챗봇 설정 (사이드바) ────────────────────────────────────
    st.sidebar.divider()
    st.sidebar.header("챗봇 설정")
    api_key = st.sidebar.text_input(
        "OpenAI API Key", type="password", key="api_key", placeholder="sk-...",
    )

    # ── 메일 발송 (사이드바) ─────────────────────────────────────
    st.sidebar.divider()
    st.sidebar.header("메일 발송")
    mail_sender    = st.sidebar.text_input("발신자 이메일", key="mail_sender",    placeholder="your@gmail.com")
    mail_password  = st.sidebar.text_input("Gmail 앱 비밀번호", type="password",  key="mail_password", placeholder="앱 비밀번호 16자리")
    mail_recipient = st.sidebar.text_input("수신자 이메일", key="mail_recipient", placeholder="a@b.com, c@d.com")

    # ── 섹션 1: 월간 추이 ──────────────────────────────────────
    st.header("월간 추이")
    st.caption("사소·품목별 입고·사용·재고 월간 집계 (실적/계획/전월/전년동월 비교)")

    # selected_month 기본값 초기화 (탭A 외부에서 접근용)
    _all_months_init = sorted(pd.to_datetime(daily["date"]).dt.to_period("M").unique().tolist())
    _act_mask_init = daily["is_actual"].fillna(False).astype(bool)
    selected_month = (
        pd.to_datetime(daily[_act_mask_init]["date"]).dt.to_period("M").max()
        if _act_mask_init.any() else _all_months_init[-1]
    )

    _tab_monthly_a, _tab_monthly_b = st.tabs(["단일 월 심층 비교", "멀티 월 비교"])

    # ── 탭A: 단일 월 심층 비교 ──────────────────────────────────
    with _tab_monthly_a:
        _all_months = sorted(pd.to_datetime(daily["date"]).dt.to_period("M").unique().tolist())
        _month_labels = [str(m) for m in _all_months]
        _act_mask_all = daily["is_actual"].fillna(False).astype(bool)
        _default_month = (
            pd.to_datetime(daily[_act_mask_all]["date"]).dt.to_period("M").max()
            if _act_mask_all.any() else _all_months[-1]
        )
        _default_idx = _month_labels.index(str(_default_month))

        mf0, mf1, mf2, mf3 = st.columns([1, 1, 1, 2])
        with mf0:
            selected_month_str = st.selectbox(
                "월 선택", _month_labels, index=_default_idx, key="monthly_month"
            )
            selected_month = pd.Period(selected_month_str, freq="M")
        with mf1:
            show_types = st.multiselect(
                "실적/계획", ["실적", "계획"],
                default=["실적", "계획"], key="monthly_show_types",
            )
        with mf2:
            show_metrics = st.multiselect(
                "수불 구분", ["입고", "사용", "재고"],
                default=["입고", "사용", "재고"], key="monthly_show_metrics",
            )
        with mf3:
            item_options = ["총계"] + sorted(daily["구매item"].dropna().unique().tolist())
            selected_items = st.multiselect(
                "ITEM 필터", item_options, default=["총계"], key="monthly_items",
            )

        total_prominent = not selected_items or "총계" in selected_items
        item_list = [x for x in (selected_items or []) if x != "총계"]

        if item_list and not total_prominent:
            daily_item = daily[daily["구매item"].isin(item_list)]
        else:
            daily_item = daily

        daily_chart = daily_item[
            pd.to_datetime(daily_item["date"]).dt.to_period("M") == selected_month
        ]

        if item_list and not total_prominent:
            exp_recv_item = exp_recv_all[exp_recv_all["구매item"].isin(item_list)]
            exp_use_item  = exp_use_all[exp_use_all["구매item"].isin(item_list)]
        else:
            exp_recv_item = exp_recv_all
            exp_use_item  = exp_use_all

        _m_summary = _monthly_summary(
            daily_item, target_month=selected_month,
            exp_recv=exp_recv_item, exp_use=exp_use_item,
        )
        _render_summary_box(_m_summary)
        if api_key:
            if st.checkbox("AI 요약 (월간 추이)", key="ai_monthly"):
                with st.spinner("AI 요약 생성 중..."):
                    try:
                        st.caption(_ai_summary(_m_summary, api_key))
                    except Exception as e:
                        st.caption(f"AI 요약 오류: {e}")

        split_site = st.toggle("사소 구분", value=False, key="monthly_split_site")

        chart_kwargs = dict(
            show_metrics=show_metrics,
            show_types=show_types,
            item_list=item_list,
            total_prominent=total_prominent,
        )

        if split_site:
            col_ph, col_gy = st.columns(2)
            for col, site in [(col_ph, "포항소"), (col_gy, "광양소")]:
                with col:
                    st.subheader(site)
                    sub = daily_chart[daily_chart["사소구분"] == site]
                    st.plotly_chart(make_monthly_chart(sub, **chart_kwargs), use_container_width=True)
        else:
            st.plotly_chart(make_monthly_chart(daily_chart, **chart_kwargs), use_container_width=True)

        tbl = (
            daily_chart.groupby(["date", "is_actual"])
            .agg(recv_qty=("recv_qty", "sum"), use_qty=("use_qty", "sum"), inv=("inv", "sum"))
            .reset_index()
        )
        tbl.columns = ["날짜", "실적여부", "입고량", "사용량", "재고"]
        tbl["실적여부"] = tbl["실적여부"].map({True: "실적", False: "계획"})
        st.dataframe(
            tbl,
            use_container_width=True,
            hide_index=True,
            column_config={
                "입고량": st.column_config.NumberColumn(format="%,.0f"),
                "사용량": st.column_config.NumberColumn(format="%,.0f"),
                "재고": st.column_config.NumberColumn(format="%,.0f"),
            },
        )

    # ── 탭B: 멀티 월 비교 ───────────────────────────────────────
    with _tab_monthly_b:
        _all_months_b = sorted(pd.to_datetime(daily["date"]).dt.to_period("M").unique().tolist())
        _month_labels_b = [str(m) for m in _all_months_b]

        tb_c1, tb_c2 = st.columns([2, 1])
        with tb_c1:
            selected_months_b = st.multiselect(
                "비교할 월 선택 (최대 12개월)",
                _month_labels_b,
                default=_month_labels_b[-min(3, len(_month_labels_b)):],
                key="multi_month_select",
            )
        with tb_c2:
            metric_b = st.radio(
                "수불 항목", ["입고", "사용", "재고"],
                horizontal=True, key="multi_month_metric",
            )

        if selected_months_b:
            months_b = [pd.Period(m, freq="M") for m in selected_months_b]
            st.plotly_chart(
                make_multi_month_bar(daily, months_b, metric=metric_b),
                use_container_width=True,
            )
        else:
            st.info("비교할 월을 1개 이상 선택하세요.")

    # ── 섹션 2: 입고 상세 ──────────────────────────────────────
    st.divider()
    st.header("입고 상세")
    st.caption("기간·사소·구분·공급사·품목·등급 기준 입하 실적 조회")

    _compare_mode = st.toggle("기간 비교 모드", value=False, key="receipt_compare_mode")

    receipt = _preprocess_receipt(receipt_raw, grade_lookup, supplier_gubuns, gubun_grades, region_ref)

    dates = sorted(receipt["날짜"].unique())
    if dates:
        min_date, max_date = dates[0], dates[-1]
    else:
        min_date = max_date = datetime.date.today()

    # 선택 월 기준 기본 날짜 (데이터 범위 내로 클램프)
    _sel_start = max(selected_month.start_time.date(), min_date)
    _sel_end   = min(selected_month.end_time.date(),   max_date)

    if _compare_mode:
        # ── 기간 비교 모드 ─────────────────────────────────────
        st.caption("빠른 선택 또는 직접 설정으로 두 기간을 비교합니다.")

        _qc1, _qc2, _qc3, _ = st.columns([1, 1, 1, 3])
        _quick = None
        with _qc1:
            if st.button("전월 비교", key="quick_prev_month"):
                _quick = "prev_month"
        with _qc2:
            if st.button("전분기 비교", key="quick_prev_quarter"):
                _quick = "prev_quarter"
        with _qc3:
            if st.button("전년동기 비교", key="quick_prev_year"):
                _quick = "prev_year"

        if _quick == "prev_month":
            st.session_state["cmp_a_start"] = _sel_start
            st.session_state["cmp_a_end"]   = _sel_end
            _b_end = _sel_start - datetime.timedelta(days=1)
            st.session_state["cmp_b_start"] = _b_end.replace(day=1)
            st.session_state["cmp_b_end"]   = _b_end
        elif _quick == "prev_quarter":
            st.session_state["cmp_a_start"] = _sel_start
            st.session_state["cmp_a_end"]   = _sel_end
            st.session_state["cmp_b_start"] = max(_sel_start - datetime.timedelta(days=90), min_date)
            st.session_state["cmp_b_end"]   = max(_sel_end   - datetime.timedelta(days=90), min_date)
        elif _quick == "prev_year":
            try:
                st.session_state["cmp_a_start"] = _sel_start
                st.session_state["cmp_a_end"]   = _sel_end
                st.session_state["cmp_b_start"] = max(_sel_start.replace(year=_sel_start.year - 1), min_date)
                st.session_state["cmp_b_end"]   = max(_sel_end.replace(year=_sel_end.year - 1), min_date)
            except ValueError:
                pass

        _da_c1, _da_c2, _db_c1, _db_c2 = st.columns(4)
        with _da_c1:
            cmp_a_start = st.date_input(
                "A기간 시작", key="cmp_a_start",
                value=st.session_state.get("cmp_a_start", _sel_start),
                min_value=min_date, max_value=max_date,
            )
        with _da_c2:
            cmp_a_end = st.date_input(
                "A기간 종료", key="cmp_a_end",
                value=st.session_state.get("cmp_a_end", _sel_end),
                min_value=min_date, max_value=max_date,
            )
        with _db_c1:
            _b_def_start = st.session_state.get(
                "cmp_b_start",
                max((_sel_start - datetime.timedelta(days=31)).replace(day=1), min_date),
            )
            cmp_b_start = st.date_input(
                "B기간 시작", key="cmp_b_start",
                value=_b_def_start,
                min_value=min_date, max_value=max_date,
            )
        with _db_c2:
            _b_def_end = st.session_state.get(
                "cmp_b_end",
                max(_sel_start - datetime.timedelta(days=1), min_date),
            )
            cmp_b_end = st.date_input(
                "B기간 종료", key="cmp_b_end",
                value=_b_def_end,
                min_value=min_date, max_value=max_date,
            )

        start_date = cmp_a_start
        end_date   = cmp_a_end

        site_opts2 = ["전체"] + sorted(receipt["사소구분"].dropna().unique().tolist())
        f_site = st.selectbox("사소 필터", site_opts2, key="site2_cmp")

    else:
        # ── 단일 기간 모드 (기존) ──────────────────────────────
        fc1, fc2, fc3 = st.columns([1, 1, 1])
        with fc1:
            start_date = st.date_input("시작일", value=_sel_start, min_value=min_date, max_value=max_date)
        with fc2:
            end_date = st.date_input("종료일", value=_sel_end, min_value=min_date, max_value=max_date)
        with fc3:
            site_opts2 = ["전체"] + sorted(receipt["사소구분"].dropna().unique().tolist())
            f_site = st.selectbox("사소 필터", site_opts2, key="site2")

    # 2행: 구분 + 공급사
    fc4, fc5 = st.columns([1, 2])
    with fc4:
        f_gubun = st.multiselect("구분 필터", sorted(receipt["구분"].dropna().unique()))
    with fc5:
        f_supplier = st.multiselect(
            "공급사 필터",
            ["합계"] + sorted(receipt["공급사"].dropna().unique()),
        )

    # 3행: 품목 + 등급대분류 + 등급
    fc6, fc6b, fc7 = st.columns([1, 1, 1])
    with fc6:
        f_item = st.multiselect(
            "품목 필터",
            ["합계"] + sorted(receipt["구매item"].dropna().unique()),
        )
    with fc6b:
        f_grade_cat = st.multiselect(
            "등급대분류 필터",
            ["합계"] + sorted(receipt["등급대분류"].dropna().unique()),
        )
    with fc7:
        f_grade = st.multiselect(
            "등급 필터",
            ["합계"] + sorted(receipt["등급"].dropna().unique()),
        )

    # 날짜 외 필터 마스크 (전월 比 계산용)
    collapse_supplier = bool(f_supplier and "합계" in f_supplier)
    mask_no_date = _build_receipt_mask(receipt, f_site, f_gubun, f_supplier, f_item, f_grade_cat, f_grade)
    receipt_no_date = receipt[mask_no_date]

    mask = mask_no_date & (receipt["날짜"] >= start_date) & (receipt["날짜"] <= end_date)
    filtered = receipt[mask].reset_index(drop=True)

    if _compare_mode:
        # B기간 필터링
        mask_b = (
            _build_receipt_mask(receipt, f_site, f_gubun, f_supplier, f_item, f_grade_cat, f_grade)
            & (receipt["날짜"] >= cmp_b_start)
            & (receipt["날짜"] <= cmp_b_end)
        )
        filtered_b = receipt[mask_b]

        label_a = f"{cmp_a_start}~{cmp_a_end}"
        label_b = f"{cmp_b_start}~{cmp_b_end}"

        grp_col_options = ["구분", "구매item", "등급대분류", "공급사"]
        grp_col = st.selectbox("비교 기준", grp_col_options, key="cmp_group_col")

        st.plotly_chart(
            make_comparison_bar(filtered, filtered_b, label_a, label_b, group_col=grp_col),
            use_container_width=True,
        )

        agg_a = filtered.groupby(grp_col)["입하량(net)"].sum().rename("A기간")
        agg_b = filtered_b.groupby(grp_col)["입하량(net)"].sum().rename("B기간")
        cmp_tbl = pd.concat([agg_a, agg_b], axis=1).fillna(0)
        cmp_tbl["증감량"] = cmp_tbl["A기간"] - cmp_tbl["B기간"]
        cmp_tbl["증감률(%)"] = (
            (cmp_tbl["A기간"] - cmp_tbl["B기간"])
            / cmp_tbl["B기간"].replace(0, float("nan")) * 100
        ).round(1)
        st.dataframe(
            cmp_tbl.reset_index().sort_values("A기간", ascending=False),
            use_container_width=True, hide_index=True,
            column_config={
                "A기간": st.column_config.NumberColumn(format="%,.0f"),
                "B기간": st.column_config.NumberColumn(format="%,.0f"),
                "증감량": st.column_config.NumberColumn(format="%,.0f"),
            },
        )
    else:
        # ── 입고 상세 요약 ────────────────────────────────────────
        _r_summary = _receipt_summary(filtered, start_date, end_date, receipt_no_date)
        if _r_summary:
            _render_summary_box(_r_summary)
            if api_key:
                if st.checkbox("AI 요약 (입고 상세)", key="ai_receipt"):
                    with st.spinner("AI 요약 생성 중..."):
                        try:
                            st.caption(_ai_summary(_r_summary, api_key))
                        except Exception as e:
                            st.caption(f"AI 요약 오류: {e}")

        if not filtered.empty:
            # 지역소구분 컬럼 포함 여부에 따라 그룹 컬럼 동적 결정
            _grp_cols = ["날짜", "사소구분", "구분", "공급사", "구매item", "등급대분류", "등급"]
            if "지역소구분" in filtered.columns:
                _grp_cols.insert(3, "지역소구분")
            daily_tbl = (
                filtered
                .groupby(_grp_cols, dropna=False)["입하량(net)"]
                .sum()
                .reset_index()
                .rename(columns={"입하량(net)": "입고량"})
                .sort_values("날짜")
            )
            st.dataframe(
                daily_tbl,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "입고량": st.column_config.NumberColumn(format="%,.0f"),
                },
            )

            tog_col0, tog_col2, tog_col3 = st.columns([2, 1, 1])
            with tog_col0:
                view_mode = st.radio(
                    "기간 표시",
                    ["기간 합계", "일자별", "주차별"],
                    horizontal=True,
                    key="receipt_view_mode",
                    label_visibility="collapsed",
                )
            with tog_col2:
                split_site = st.toggle("사소 구분", value=False, key="receipt_split_site")
            with tog_col3:
                no_limit = st.toggle("공급사 제한 해제", value=False, key="receipt_no_limit")

            by_date = view_mode == "일자별"
            by_week = view_mode == "주차별"
            supplier_limit = None if no_limit else 10
            single_item = len(filtered["구매item"].unique()) == 1

            if split_site:
                col_ph, col_gy = st.columns(2)
                for col, site in [(col_ph, "포항소"), (col_gy, "광양소")]:
                    with col:
                        st.subheader(site)
                        sub = filtered[filtered["사소구분"] == site]
                        if sub.empty:
                            st.info("데이터 없음")
                        else:
                            st.plotly_chart(
                                make_receipt_detail_bar(
                                    sub, single_item=single_item,
                                    by_date=by_date, by_week=by_week,
                                    supplier_limit=supplier_limit,
                                    collapse_supplier=collapse_supplier,
                                ),
                                use_container_width=True,
                            )
            else:
                st.plotly_chart(
                    make_receipt_detail_bar(
                        filtered, single_item=single_item,
                        by_date=by_date, by_week=by_week,
                        supplier_limit=supplier_limit,
                        collapse_supplier=collapse_supplier,
                    ),
                    use_container_width=True,
                )

        else:
            st.info("조회된 데이터가 없습니다.")

    # ── 섹션 3: 구분별 가격정책 신호 ──────────────────────────
    st.divider()
    _render_gubun_signal_section(receipt, api_key=api_key if api_key else None)

    # ── 섹션 4: 지도 + AI 챗봇 (좌/우 배치) ───────────────────
    st.divider()
    _map_col, _chat_col = st.columns([1, 1])

    with _map_col:
        if not filtered.empty and "지역대구분" in filtered.columns:
            st.subheader("지역별 입고 현황")
            _render_region_map(filtered)

    with _chat_col:
        st.header("AI 수불 분석 챗봇")
        st.caption("LangGraph 라우터 · 하이브리드 서치(BM25+TF-IDF) · RRF 리랭커 · CSV 분석 에이전트")

    # 하이브리드 RAG 인덱스 빌드 (캐시)
    @st.cache_resource
    def build_retriever(_daily, _supplier):
        chunks = build_chunks(_daily, _supplier)
        return RAGRetriever(chunks)

    retriever = build_retriever(daily, supplier_df)

    # 대화 이력 초기화 (LangGraph messages 형식)
    if "lg_messages" not in st.session_state:
        st.session_state.lg_messages = []
    if "display_history" not in st.session_state:
        st.session_state.display_history = []

    with _chat_col:
        # 기존 대화 렌더링
        for msg in st.session_state.display_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("route"):
                    st.caption(f"경로: {'RAG 조회' if msg['route'] == 'rag' else '데이터 분석'}")

        user_input = st.chat_input("질문하세요. 예) 포항소 재고는? / 사용량이 가장 많은 달은?")

        if user_input:
            if not api_key:
                st.warning("왼쪽 사이드바에서 OpenAI API Key를 입력해 주세요.")
            else:
                with st.chat_message("user"):
                    st.markdown(user_input)

                with st.chat_message("assistant"):
                    with st.spinner("LangGraph 처리 중..."):
                        try:
                            # gubun_summary DataFrame 생성 (AI 챗봇용)
                            try:
                                _sig = build_gubun_signal(receipt, compare="month")
                                _gubun_rows = [
                                    {
                                        "구분그룹": k,
                                        "당기입고량": v["current"],
                                        "전기입고량": v["prev"],
                                        "증감률": v["pct"],
                                    }
                                    for k, v in _sig["by_group"].items()
                                ]
                                _gubun_summary_df = pd.DataFrame(_gubun_rows)
                            except Exception:
                                _gubun_summary_df = pd.DataFrame()
                            graph = build_graph(daily, supplier_df, retriever, api_key, gubun_summary=_gubun_summary_df)

                            init_state = {
                                "messages": st.session_state.lg_messages + [HumanMessage(content=user_input)],
                                "route": "",
                                "context": [],
                                "answer": "",
                            }
                            result = graph.invoke(init_state)

                            answer = result["answer"]
                            route  = result.get("route", "rag")
                            context = result.get("context", [])

                        except Exception as e:
                            answer = None
                            route  = ""
                            context = []
                            st.error(f"오류: {e}")

                    if answer:
                        if route == "analysis":
                            parts = answer.split("\n\n<분석 상세>")
                            st.markdown(parts[0])
                            if len(parts) > 1:
                                with st.expander("분석 상세 (생성 코드 + 실행 결과)", expanded=False):
                                    st.code(parts[1], language="text")
                        else:
                            st.markdown(answer)

                        st.caption(f"경로: {'RAG 조회' if route == 'rag' else '데이터 분석'}")

                        with st.expander("참조 컨텍스트", expanded=False):
                            for c in context:
                                st.markdown(f"- {c}")

                if answer:
                    st.session_state.lg_messages.append(HumanMessage(content=user_input))
                    st.session_state.lg_messages.append(AIMessage(content=answer))

                    st.session_state.display_history.append(
                        {"role": "user", "content": user_input, "route": ""}
                    )
                    st.session_state.display_history.append(
                        {"role": "assistant", "content": answer, "route": route}
                    )

        if st.session_state.display_history:
            if st.button("대화 초기화", key="clear_chat"):
                st.session_state.lg_messages = []
                st.session_state.display_history = []
                st.rerun()

    # ── 데이터 다운로드 slot 채우기 ───────────────────────────────
    try:
        excel_bytes = export_workbook_bytes(daily, supplier_df, receipt, str(selected_month))
    except Exception as _ex:
        import traceback
        st.sidebar.error(f"Export 오류: {_ex}")
        st.sidebar.code(traceback.format_exc())
        excel_bytes = b""

    excel_filename = f"수불현황_{selected_month}.xlsx"
    with _download_slot:
        st.header("데이터 다운로드")
        st.download_button(
            label="Excel 다운로드",
            data=excel_bytes,
            file_name=excel_filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # ── 메일 발송 버튼 ───────────────────────────────────────────
    if st.sidebar.button("메일 발송", use_container_width=True):
        if not mail_sender or not mail_password or not mail_recipient:
            st.sidebar.warning("발신자 이메일, 앱 비밀번호, 수신자 이메일을 모두 입력하세요.")
        elif not excel_bytes:
            st.sidebar.warning("Excel 데이터 생성에 실패했습니다.")
        else:
            recipients = [r.strip() for r in mail_recipient.split(",") if r.strip()]
            try:
                _send_gmail(
                    sender=mail_sender,
                    password=mail_password,
                    recipients=recipients,
                    subject=f"수불현황 보고 ({selected_month})",
                    body=f"{selected_month} 수불현황 데이터를 첨부합니다.",
                    attachment_bytes=excel_bytes,
                    attachment_name=excel_filename,
                )
                st.sidebar.success("메일이 발송되었습니다.")
            except Exception as _mail_ex:
                st.sidebar.error(f"메일 발송 실패: {_mail_ex}")


render()
