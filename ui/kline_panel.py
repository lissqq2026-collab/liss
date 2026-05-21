"""ui/kline_panel.py — 分时 + K线综合面板（搜索 + 4个子tab）。

设计：
  - 顶部：股票搜索框（pypinyin 模糊匹配）+ 时间范围 + MA 工具栏
  - 子tab：分时 / 日K / 周K / 月K（分时默认展示）
  - 分时：新浪 1 分钟接口 → build_intraday_chart
  - 日/周/月：本地 DB → resample → build_kline_chart
"""
from __future__ import annotations

import datetime
from typing import Optional

import streamlit as st

from data.db import manager as db
from data.sources import sina_intraday
from strategies.chart import build_kline_chart, resample_weekly, resample_monthly
from strategies.intraday_chart import build_intraday_chart
from ui.stock_search import stock_search
from ui.plotly_autoscale import inject_y_autoscale

_PLOTLY_CFG = {
    "scrollZoom": True,
    "displayModeBar": True,
    "modeBarButtonsToAdd": ["drawline", "eraseshape"],
    "modeBarButtonsToRemove": ["select2d", "lasso2d"],
}

_RANGE_MAP = {
    "近3月": 90,
    "近6月": 180,
    "近1年": 365,
    "近3年": 1095,
    "全部":  None,
}


def _resolve_name(code: str) -> str:
    """从本地 DB 取股票名；找不到则返回 code 本身。"""
    for r in (db.get_all_codes() or []):
        if r.get("code") == code:
            return r.get("name") or code
    return code


def _render_kline_tab(code: str, name: str, period_label: str, period_code: str,
                       start_date: str, show_macd: bool, show_ma_periods: list[int],
                       key_suffix: str) -> None:
    df_raw = db.get_daily(code, start=start_date)
    if df_raw is None or df_raw.empty:
        st.warning(f"本地数据库中暂无 {code} 的K线数据，请等待后台更新完成后刷新。")
        return

    if period_code == "W":
        df_plot = resample_weekly(df_raw)
    elif period_code == "M":
        df_plot = resample_monthly(df_raw)
    else:
        df_plot = df_raw.copy()

    if df_plot.empty:
        st.warning("当前时间范围内无K线数据，请切换更大范围。")
        return

    fig = build_kline_chart(
        df_plot,
        title=f"{code}  {name}  {period_label}",
        show_macd=show_macd, period=period_code,
        show_ma_periods=show_ma_periods,
    )
    st.plotly_chart(fig, use_container_width=True,
                     config=_PLOTLY_CFG, key=f"kl_chart_{key_suffix}_{code}")

    last = df_plot.iloc[-1]
    close = float(last["close"]); op = float(last["open"])
    hi = float(last["high"]); lo = float(last["low"])
    pct = float(last.get("pct_change", 0) or 0)
    vol = float(last.get("volume", 0) or 0)
    arrow = "▲" if pct >= 0 else "▼"

    st.markdown("---")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("收盘价", f"{close:.2f}", f"{arrow} {abs(pct):.2f}%",
               delta_color="normal" if pct >= 0 else "inverse")
    m2.metric("开盘",   f"{op:.2f}")
    m3.metric("最高",   f"{hi:.2f}")
    m4.metric("最低",   f"{lo:.2f}")
    m5.metric("成交量(手)", f"{vol/100:,.0f}" if vol else "—")


def _render_intraday_tab(code: str, name: str) -> None:
    col_a, col_b = st.columns([1, 9])
    with col_a:
        if st.button("🔄 刷新", key=f"intra_refresh_{code}"):
            st.cache_data.clear()
            st.rerun()
    with col_b:
        st.caption("数据：新浪 1 分钟分时（缓存 60s）· 仅交易时段实时刷新")

    with st.spinner(f"正在加载 {code} 的分时数据…"):
        df = sina_intraday.get_intraday_1min(code)
        prev_close = sina_intraday.get_prev_close(code)

    if df is None or df.empty:
        st.warning(f"暂无 {code} 的分时数据（可能非交易时段、停牌、或新浪接口异常）。")
        return

    fig = build_intraday_chart(
        df, title=f"{code}  {name}  分时",
        prev_close=prev_close,
    )
    st.plotly_chart(fig, use_container_width=True,
                     config={"displayModeBar": False},
                     key=f"intra_chart_{code}")


def render_kline_panel(default_code: Optional[str] = None,
                        key_prefix: str = "klp") -> None:
    """渲染 分时 / K线 面板。默认展示分时图，可切换到日K/周K/月K。"""
    code = stock_search(key=f"{key_prefix}_search", default=default_code)
    if not code:
        st.info("请在上方搜索框选择股票（支持代码 / 名称 / 拼音 / 简拼）。")
        return

    name = _resolve_name(code)

    # K线工具栏（仅对日K/周K/月K生效）
    c1, c2, c3 = st.columns([2, 2, 6])
    with c1:
        range_label = st.selectbox("时间范围",
                                     list(_RANGE_MAP.keys()), index=2,
                                     key=f"{key_prefix}_range")
    with c2:
        show_macd = st.checkbox("MACD", value=True, key=f"{key_prefix}_macd")
    with c3:
        cols = st.columns(4)
        ma5  = cols[0].checkbox("MA5",  value=True,  key=f"{key_prefix}_ma5")
        ma10 = cols[1].checkbox("MA10", value=True,  key=f"{key_prefix}_ma10")
        ma20 = cols[2].checkbox("MA20", value=True,  key=f"{key_prefix}_ma20")
        ma60 = cols[3].checkbox("MA60", value=False, key=f"{key_prefix}_ma60")
    show_ma_periods = [p for p, s in [(5, ma5), (10, ma10), (20, ma20), (60, ma60)] if s]

    days = _RANGE_MAP[range_label]
    today = datetime.date.today()
    start_date = "1990-01-01" if days is None else \
                  (today - datetime.timedelta(days=days)).isoformat()

    # 分时默认在前，选中股票即展示分时图
    t_intra, t_day, t_week, t_month = st.tabs(["分时", "日K", "周K", "月K"])
    with t_intra:
        _render_intraday_tab(code, name)
    with t_day:
        _render_kline_tab(code, name, "日K", "D", start_date,
                           show_macd, show_ma_periods, "d")
    with t_week:
        _render_kline_tab(code, name, "周K", "W", start_date,
                           show_macd, show_ma_periods, "w")
    with t_month:
        _render_kline_tab(code, name, "月K", "M", start_date,
                           show_macd, show_ma_periods, "m")

    # 同花顺式 Y 轴自适应：缩放/平移时主图 Y 轴跟随可见窗口高低点
    inject_y_autoscale()
