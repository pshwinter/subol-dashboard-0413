# dashboard/charts.py
import plotly.graph_objects as go
import pandas as pd
import datetime


ACTUAL_COLOR_RECV = "#3B82F6"    # 실적 입고 (브랜드 블루)
ACTUAL_COLOR_USE = "#D97706"     # 실적 사용 (앰버)
ACTUAL_COLOR_INV = "#1E40AF"     # 실적 재고 (다크 블루)
FORECAST_ALPHA = 0.4

FORECAST_INV = "rgba(30,64,175,0.35)"

# 품목별 색상 팔레트 (브랜드 팔레트 기반)
ITEM_COLORS = [
    "#D97706",  # amber
    "#6366F1",  # indigo
    "#10B981",  # emerald
    "#F43F5E",  # rose
    "#8B5CF6",  # violet
    "#0EA5E9",  # sky
    "#F97316",  # orange
]

# 입고 상세 차트용 팔레트
BRAND_COLORS = [
    "#1E40AF", "#3B82F6", "#D97706", "#10B981",
    "#6366F1", "#F43F5E", "#8B5CF6", "#0EA5E9",
    "#F97316", "#14B8A6",
]


def make_monthly_chart(
    daily: pd.DataFrame,
    show_metrics: list | None = None,
    show_types: list | None = None,
    item_list: list | None = None,
    total_prominent: bool = True,
) -> go.Figure:
    """월간 추이 복합 차트.

    show_metrics   : ["입고", "사용", "재고"] 중 표시할 항목
    show_types     : ["실적", "계획"] 중 표시할 유형
    item_list      : 개별 표시할 품목 리스트 (빈 리스트 = 총계만)
    total_prominent: True → 총계 바/선 진하게, False → 흐리게(배경)
    """
    if show_metrics is None:
        show_metrics = ["입고", "사용", "재고"]
    if show_types is None:
        show_types = ["실적", "계획"]
    if item_list is None:
        item_list = []

    show_actual   = "실적" in show_types
    show_forecast = "계획" in show_types
    show_recv = "입고" in show_metrics
    show_use  = "사용" in show_metrics
    show_inv  = "재고" in show_metrics

    actual = daily[daily["is_actual"]]
    forecast_all = daily[~daily["is_actual"]]

    if daily.empty:
        return go.Figure().update_layout(
            title="데이터 없음", hovermode="x unified"
        )

    if not actual.empty:
        last_actual_date = actual["date"].max()
        actual_dates = set(actual["date"].unique())
        forecast = forecast_all[~forecast_all["date"].isin(actual_dates)]
    else:
        last_actual_date = None
        forecast = forecast_all

    def day_sum(df, col):
        if df.empty:
            return pd.DataFrame(columns=["date", col])
        return df.groupby("date")[col].sum().reset_index()

    def _add_item_lines(col, name_prefix, dash_act, dash_fct, show_leg):
        """recv/use 품목별 실적·계획 선 트레이스 추가 (공통 루프)."""
        for j, item in enumerate(item_list):
            color = ITEM_COLORS[j % len(ITEM_COLORS)]
            if show_actual:
                grp = actual[actual["구매item"] == item].groupby("date")[col].sum().reset_index()
                if not grp.empty:
                    line_kw = dict(color=color, width=2)
                    if dash_act:
                        line_kw["dash"] = dash_act
                    fig.add_trace(go.Scatter(
                        x=grp["date"], y=grp[col],
                        name=f"{name_prefix}({item})", mode="lines+markers",
                        line=line_kw,
                        hovertemplate="%{y:,.0f}<extra></extra>",
                        legendgroup=item, showlegend=show_leg,
                    ))
            if show_forecast:
                grp = forecast[forecast["구매item"] == item].groupby("date")[col].sum().reset_index()
                if not grp.empty:
                    fig.add_trace(go.Scatter(
                        x=grp["date"], y=grp[col],
                        name=f"{name_prefix}({item})-계획", mode="lines+markers",
                        line=dict(color=color, width=2, dash=dash_fct),
                        opacity=FORECAST_ALPHA,
                        hovertemplate="%{y:,.0f}<extra></extra>",
                        legendgroup=item, showlegend=False,
                    ))

    # 품목별 inv 누적 base 계산용 (실적/계획 각각)
    def item_stacked_bars(src_df, col, dates_index, label_suffix, opacity):
        """dates_index: 전체 날짜 목록, 반환: (traces, 최종 누적 Series)"""
        cumbase = pd.Series(0.0, index=dates_index)
        traces = []
        for j, item in enumerate(item_list):
            color = ITEM_COLORS[j % len(ITEM_COLORS)]
            sub = src_df[src_df["구매item"] == item].groupby("date")[col].sum()
            sub = sub.reindex(dates_index, fill_value=0)
            traces.append(go.Bar(
                x=dates_index,
                y=sub.values,
                base=cumbase.values,
                name=f"재고({item}){label_suffix}",
                marker_color=color,
                opacity=opacity,
                yaxis="y2",
                hovertemplate="%{y:,.0f}<extra></extra>",
                legendgroup=item,
                showlegend=(label_suffix == "(실적)" or not show_actual),
            ))
            cumbase = cumbase + sub
        return traces

    fig = go.Figure()
    total_bar_opacity = 0.45 if total_prominent else 0.15

    # ── 재고 막대 (y2) ──────────────────────────────────────────
    if show_inv:
        # 총계 바 먼저 (배경)
        if show_actual:
            inv_act = day_sum(actual, "inv")
            fig.add_trace(go.Bar(
                x=inv_act["date"], y=inv_act["inv"],
                name="재고(실적)", marker_color=ACTUAL_COLOR_INV,
                opacity=total_bar_opacity, yaxis="y2",
                hovertemplate="%{y:,.0f}<extra></extra>",
                legendrank=3,
            ))
        if show_forecast:
            inv_fct = day_sum(forecast, "inv")
            fig.add_trace(go.Bar(
                x=inv_fct["date"], y=inv_fct["inv"],
                name="재고(계획)", marker_color=FORECAST_INV,
                opacity=total_bar_opacity * 0.7, yaxis="y2",
                hovertemplate="%{y:,.0f}<extra></extra>",
                legendrank=6,
            ))

        # 품목별 스택 바 (총계 바 위에 overlay)
        if item_list:
            if show_actual and not actual.empty:
                dates_act = sorted(actual["date"].unique())
                for tr in item_stacked_bars(actual, "inv", dates_act, "(실적)", 0.85):
                    fig.add_trace(tr)
            if show_forecast and not forecast.empty:
                dates_fct = sorted(forecast["date"].unique())
                for tr in item_stacked_bars(forecast, "inv", dates_fct, "(계획)", 0.55):
                    fig.add_trace(tr)

    # ── 입고 선 ─────────────────────────────────────────────────
    if show_recv:
        if total_prominent:
            if show_actual:
                recv_act = day_sum(actual, "recv_qty")
                fig.add_trace(go.Scatter(
                    x=recv_act["date"], y=recv_act["recv_qty"],
                    name="입고(실적)", mode="lines+markers",
                    line=dict(color=ACTUAL_COLOR_RECV, width=2),
                    hovertemplate="%{y:,.0f}<extra></extra>",
                    legendrank=1,
                ))
            if show_forecast:
                recv_fct = day_sum(forecast, "recv_qty")
                fig.add_trace(go.Scatter(
                    x=recv_fct["date"], y=recv_fct["recv_qty"],
                    name="입고(계획)", mode="lines+markers",
                    line=dict(color=ACTUAL_COLOR_RECV, width=2, dash="dot"),
                    opacity=FORECAST_ALPHA,
                    hovertemplate="%{y:,.0f}<extra></extra>",
                    legendrank=4,
                ))
        _add_item_lines("recv_qty", "입고", dash_act=None, dash_fct="dot", show_leg=not show_inv)

    # ── 사용 선 ─────────────────────────────────────────────────
    if show_use:
        if total_prominent:
            if show_actual:
                use_act = day_sum(actual, "use_qty")
                fig.add_trace(go.Scatter(
                    x=use_act["date"], y=use_act["use_qty"],
                    name="사용(실적)", mode="lines+markers",
                    line=dict(color=ACTUAL_COLOR_USE, width=2),
                    hovertemplate="%{y:,.0f}<extra></extra>",
                    legendrank=2,
                ))
            if show_forecast:
                use_fct = day_sum(forecast, "use_qty")
                fig.add_trace(go.Scatter(
                    x=use_fct["date"], y=use_fct["use_qty"],
                    name="사용(계획)", mode="lines+markers",
                    line=dict(color=ACTUAL_COLOR_USE, width=2, dash="dot"),
                    opacity=FORECAST_ALPHA,
                    hovertemplate="%{y:,.0f}<extra></extra>",
                    legendrank=5,
                ))
        _add_item_lines("use_qty", "사용", dash_act="dash", dash_fct="dashdot", show_leg=False)

    # ── 실적↔계획 경계선 ────────────────────────────────────────
    if show_actual and show_forecast and not actual.empty and not forecast_all.empty and last_actual_date is not None:
        boundary = str(last_actual_date)
        fig.add_shape(
            type="line", x0=boundary, x1=boundary, y0=0, y1=1,
            xref="x", yref="paper",
            line=dict(dash="dash", color="gray", width=1.5),
        )
        fig.add_annotation(
            x=boundary, y=1, xref="x", yref="paper",
            text="실적↔계획", showarrow=False,
            yanchor="bottom", font=dict(color="gray", size=11),
        )

    fig.update_layout(
        barmode="overlay",
        xaxis_title="날짜",
        yaxis=dict(title="입고/사용량", tickformat=",.0f", gridcolor="#E2E8F0"),
        yaxis2=dict(
            title="재고량", overlaying="y", side="right",
            showgrid=False, tickformat=",.0f",
        ),
        legend=dict(
            orientation="h",
            entrywidthmode="fraction", entrywidth=0.27,
            yanchor="bottom", y=1.02, xanchor="right", x=1,
        ),
        hovermode="x unified",
        plot_bgcolor="#FAFAFA",
        paper_bgcolor="#FFFFFF",
    )
    return fig


def make_supplier_bar(supplier_df: pd.DataFrame) -> go.Figure:
    """공급사별 입고량 가로 막대 차트 (단순 집계용).

    supplier_df 컬럼: 공급사명, recv_qty (최소 요구)
    """
    agg = (
        supplier_df.groupby("공급사명")["recv_qty"]
        .sum()
        .sort_values(ascending=True)
        .reset_index()
    )
    fig = go.Figure(go.Bar(
        x=agg["recv_qty"], y=agg["공급사명"],
        orientation="h",
        marker_color=ACTUAL_COLOR_RECV,
        hovertemplate="%{x:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        xaxis=dict(title="입고량", tickformat=",.0f"),
        yaxis_title="공급사",
        hovermode="y unified",
    )
    return fig


def _week_start(d) -> datetime.date:
    """날짜 d가 속한 주의 일요일을 반환."""
    if isinstance(d, datetime.datetime):
        d = d.date()
    elif not isinstance(d, datetime.date):
        d = pd.Timestamp(d).date()
    return d - datetime.timedelta(days=(d.weekday() + 1) % 7)


def _week_label(ws: datetime.date) -> str:
    """주 레이블: M/D(일)~M/D(토)"""
    we = ws + datetime.timedelta(days=6)
    return f"{ws.month}/{ws.day}(일)~{we.month}/{we.day}(토)"


def make_receipt_detail_bar(
    filtered: pd.DataFrame,
    single_item: bool,
    by_date: bool = False,
    by_week: bool = False,
    supplier_limit: int | None = 10,
    collapse_supplier: bool = False,
) -> go.Figure:
    """입고 상세 스택 막대 차트 (세로형).

    by_date=False, by_week=False : X축=공급사, 스택=ITEM 또는 등급
    by_date=True                 : X축=[일자, 공급사], 스택=ITEM 또는 등급
    by_week=True                 : X축=주차(일~토 합산), 스택=ITEM 또는 등급
    collapse_supplier=True       : 모든 공급사를 '합계' 하나로 묶어 표시
    supplier_limit               : None=전체, 정수=상위 N개 공급사만 표시
    filtered 컬럼                : 공급사, 구매item, 등급, 입하량(net), 날짜
    """
    split_col = "등급" if single_item else "구매item"
    split_label = "등급" if single_item else "ITEM"

    filtered = filtered.copy()

    if collapse_supplier:
        # 모든 공급사를 '합계'로 대체 → 하나의 막대로 합산
        filtered["공급사"] = "합계"
        supplier_order = ["합계"]
    else:
        # 공급사 정렬 순서 (합계 내림차순)
        supplier_agg = (
            filtered.groupby("공급사")["입하량(net)"]
            .sum()
            .sort_values(ascending=False)
        )
        if supplier_limit is not None:
            supplier_agg = supplier_agg.head(supplier_limit)
        supplier_order = supplier_agg.index.tolist()
        filtered = filtered[filtered["공급사"].isin(supplier_order)]
    categories = sorted(filtered[split_col].dropna().unique())
    colors = BRAND_COLORS

    fig = go.Figure()

    if by_week:
        # 주차 컬럼 추가
        filtered["week_start"] = filtered["날짜"].apply(_week_start)
        sorted_weeks = sorted(filtered["week_start"].unique())
        x_labels = [_week_label(w) for w in sorted_weeks]

        for i, cat in enumerate(categories):
            sub = filtered[filtered[split_col] == cat]
            agg = (
                sub.groupby("week_start")["입하량(net)"]
                .sum()
                .reindex(sorted_weeks, fill_value=0)
            )
            fig.add_trace(go.Bar(
                x=x_labels,
                y=agg.values,
                name=f"{split_label}: {cat}",
                marker_color=colors[i % len(colors)],
                hovertemplate="%{x}<br>%{y:,.0f}<extra></extra>",
            ))
        xaxis_title = "주차"
        n_bars = len(sorted_weeks)

    elif by_date:
        sorted_dates = sorted(filtered["날짜"].dropna().unique())
        # 전체 (날짜, 공급사) 조합 - 날짜 오름차순, 공급사는 합계 순서 유지
        all_keys = [(d, s) for d in sorted_dates for s in supplier_order]
        x_dates = [f"{k[0].month}.{k[0].day}" for k in all_keys]
        x_suppliers = [k[1] for k in all_keys]

        for i, cat in enumerate(categories):
            sub = filtered[filtered[split_col] == cat]
            agg = (
                sub.groupby(["날짜", "공급사"])["입하량(net)"]
                .sum()
                .reindex(pd.MultiIndex.from_tuples(all_keys), fill_value=0)
            )
            fig.add_trace(go.Bar(
                x=[x_dates, x_suppliers],
                y=agg.values,
                name=f"{split_label}: {cat}",
                marker_color=colors[i % len(colors)],
                hovertemplate="%{y:,.0f}<extra></extra>",
            ))
        xaxis_title = "일자 / 공급사"
        n_bars = len(supplier_order) * len(sorted_dates)

    else:
        for i, cat in enumerate(categories):
            sub = filtered[filtered[split_col] == cat]
            agg = sub.groupby("공급사")["입하량(net)"].sum().reindex(supplier_order, fill_value=0)
            fig.add_trace(go.Bar(
                x=agg.index, y=agg.values,
                name=f"{split_label}: {cat}",
                marker_color=colors[i % len(colors)],
                hovertemplate="%{y:,.0f}<extra></extra>",
            ))
        xaxis_title = "공급사"
        n_bars = len(supplier_order)

    # 막대 수에 따라 레이블 각도 결정: 여유 있으면 수평, 좁으면 수직
    tick_angle = 0 if n_bars <= 8 else -45

    fig.update_layout(
        barmode="stack",
        xaxis=dict(
            title=xaxis_title,
            tickangle=tick_angle,
            automargin=True,
        ),
        yaxis=dict(title="입고량", tickformat=",.0f", gridcolor="#E2E8F0"),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=0.9),
        plot_bgcolor="#FAFAFA",
        paper_bgcolor="#FFFFFF",
    )
    return fig


def make_multi_month_bar(
    daily: pd.DataFrame,
    months: list,
    metric: str = "입고",
) -> go.Figure:
    """멀티 월 나란히 비교 그룹 막대 차트.

    months: pd.Period 리스트 (예: [Period('2026-01'), Period('2026-02')])
    metric: "입고" → recv_qty 합산, "사용" → use_qty 합산, "재고" → 마지막 inv
    """
    if not months or daily.empty:
        return go.Figure().update_layout(title="데이터 없음")

    col_map = {"입고": "recv_qty", "사용": "use_qty", "재고": "inv"}
    col = col_map.get(metric, "recv_qty")

    daily = daily.copy()
    daily["month"] = pd.to_datetime(daily["date"]).dt.to_period("M")

    sites = sorted(daily["사소구분"].dropna().unique())
    site_colors = {
        "포항소": ACTUAL_COLOR_RECV,
        "광양소": ACTUAL_COLOR_USE,
    }

    fig = go.Figure()
    month_labels = [str(m) for m in months]

    for site in sites:
        site_df = daily[daily["사소구분"] == site]
        values = []
        for m in months:
            m_df = site_df[site_df["month"] == m]
            if metric == "재고":
                val = float(
                    m_df.sort_values("date")
                    .groupby(["사소구분", "구매item"])["inv"].last().sum()
                ) if not m_df.empty else 0.0
            else:
                val = float(m_df[col].sum()) if not m_df.empty else 0.0
            values.append(val)

        fig.add_trace(go.Bar(
            name=site,
            x=month_labels,
            y=values,
            marker_color=site_colors.get(site, BRAND_COLORS[len(fig.data) % len(BRAND_COLORS)]),
            hovertemplate="%{x}<br>%{y:,.0f}<extra></extra>",
        ))

    fig.update_layout(
        barmode="group",
        xaxis_title="월",
        yaxis=dict(title=f"{metric}량", tickformat=",.0f", gridcolor="#E2E8F0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        plot_bgcolor="#FAFAFA",
        paper_bgcolor="#FFFFFF",
    )
    return fig


def make_comparison_bar(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    label_a: str = "A기간",
    label_b: str = "B기간",
    group_col: str = "구분",
) -> go.Figure:
    """A기간 vs B기간 나란히 비교 막대 차트.

    df_a, df_b: 각 기간 filtered receipt DataFrame.
                필수 컬럼: group_col, 입하량(net)
    """
    def _agg(df: pd.DataFrame) -> pd.Series:
        if df.empty or group_col not in df.columns:
            return pd.Series(dtype=float)
        return df.groupby(group_col)["입하량(net)"].sum().sort_values(ascending=False)

    agg_a = _agg(df_a)
    agg_b = _agg(df_b)
    all_cats = list(dict.fromkeys(list(agg_a.index) + list(agg_b.index)))

    vals_a = [float(agg_a.get(c, 0.0)) for c in all_cats]
    vals_b = [float(agg_b.get(c, 0.0)) for c in all_cats]

    pct_texts = []
    for a, b in zip(vals_a, vals_b):
        if b > 0:
            pct = (a - b) / b * 100
            pct_texts.append(f"{'+' if pct >= 0 else ''}{pct:.0f}%")
        else:
            pct_texts.append("")

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name=label_a,
        x=all_cats,
        y=vals_a,
        marker_color=ACTUAL_COLOR_RECV,
        hovertemplate="%{x}<br>%{y:,.0f}<extra></extra>",
        text=pct_texts,
        textposition="outside",
        textfont=dict(size=11),
    ))
    fig.add_trace(go.Bar(
        name=label_b,
        x=all_cats,
        y=vals_b,
        marker_color="#94A3B8",
        hovertemplate="%{x}<br>%{y:,.0f}<extra></extra>",
    ))

    fig.update_layout(
        barmode="group",
        xaxis_title=group_col,
        yaxis=dict(title="입고량", tickformat=",.0f", gridcolor="#E2E8F0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        plot_bgcolor="#FAFAFA",
        paper_bgcolor="#FFFFFF",
    )
    return fig


def make_gubun_signal_bar(
    by_result: dict,
    label_current: str = "당기",
    label_prev: str = "전기",
    exclude_groups: list | None = None,
) -> go.Figure:
    """구분별 당기/전기 입고량 비교 그룹 막대 차트.

    by_result: build_gubun_signal()의 by_group / by_grade / by_grade_group.
               {key: {"current": float, "prev": float, "pct": float}}
    """
    exclude = set(exclude_groups or [])

    def _label(k) -> str:
        return " × ".join(k) if isinstance(k, tuple) else k

    items = [
        (k, v) for k, v in by_result.items()
        if _label(k).split(" × ")[-1] not in exclude
    ]
    items.sort(key=lambda x: x[1]["current"], reverse=True)

    if not items:
        return go.Figure().update_layout(title="데이터 없음")

    labels = [_label(k) for k, _ in items]
    vals_cur  = [v["current"] for _, v in items]
    vals_prev = [v["prev"] for _, v in items]
    pct_vals  = [v["pct"] for _, v in items]

    pct_texts = [
        f"{'+' if p >= 0 else ''}{p:.1f}%"
        for p in pct_vals
    ]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name=label_current,
        x=labels, y=vals_cur,
        marker_color=ACTUAL_COLOR_RECV,
        hovertemplate="%{x}<br>%{y:,.0f}<extra></extra>",
        text=pct_texts,
        textposition="outside",
    ))
    fig.add_trace(go.Bar(
        name=label_prev,
        x=labels, y=vals_prev,
        marker_color="#94A3B8",
        hovertemplate="%{x}<br>%{y:,.0f}<extra></extra>",
    ))

    fig.update_layout(
        barmode="group",
        xaxis=dict(tickangle=-30, automargin=True),
        yaxis=dict(title="일평균 입고량(t)", tickformat=",.1f", gridcolor="#E2E8F0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        plot_bgcolor="#FAFAFA",
        paper_bgcolor="#FFFFFF",
    )
    return fig
