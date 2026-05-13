"""
pages/1_K线查看.py
K线查看页面 — 本地数据库浏览 + 后台智能增量更新
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import datetime

st.set_page_config(layout="wide", page_title="K线查看")

from data import auto_updater
from data.db import manager as db
from strategies.chart import build_kline_chart, resample_weekly, resample_monthly

# ── 页面加载时自动触发一次增量更新 ───────────────────────────────────────────
if "kl_auto_triggered" not in st.session_state:
    st.session_state["kl_auto_triggered"] = True
    auto_updater.start_update()          # 已在运行或今日已完成时自动跳过


# ── 侧边栏：更新状态 + 操作按钮 ──────────────────────────────────────────────

@st.cache_data(ttl=10)
def _db_code_count() -> int:
    codes = db.get_all_codes()
    return len(codes) if codes else 0


with st.sidebar:
    st.title("📈 K线查看")
    st.caption("本地数据库 · 后台智能增量更新")
    st.markdown("---")

    # 状态面板
    state = auto_updater.get_state()
    status = state["status"]

    _icon_map = {
        "idle":    "⏸️",
        "running": "🔄",
        "done":    "✅",
        "error":   "❌",
    }
    st.markdown(f"#### {_icon_map.get(status, '⏸️')} 数据更新状态")

    if status == "running":
        total    = state["total"] or 1
        progress = state["progress"]
        st.progress(progress / total, text=state["message"])
        st.caption(
            f"已更新 **{state['updated']}**  |  "
            f"失败 **{state['failed']}**  |  "
            f"跳过 **{state['skipped']}**"
        )
        st.info("后台更新中，不影响正常使用，刷新页面可查看最新进度。")
    else:
        st.caption(state["message"])
        if state["last_run"]:
            st.caption(f"上次更新：{state['last_run']}")
        if status == "error" and state["error"]:
            st.error(f"错误详情：{state['error']}")

    st.markdown("---")

    # 本地数据库信息
    local_count = _db_code_count()
    st.metric("本地库存量", f"{local_count} 只股票")

    st.markdown("---")

    # 手动触发按钮
    col_inc, col_full = st.columns(2)
    with col_inc:
        if st.button("增量更新", use_container_width=True,
                     disabled=(status == "running")):
            started = auto_updater.start_update(force=False)
            if started:
                st.toast("增量更新已启动", icon="🔄")
            else:
                st.toast("数据已是最新，无需更新", icon="✅")
            st.rerun()
    with col_full:
        if st.button("强制全量", use_container_width=True,
                     disabled=(status == "running")):
            started = auto_updater.start_update(force=True)
            if started:
                st.toast("强制全量更新已启动", icon="🔄")
            st.rerun()

    st.markdown("---")
    st.caption("数据来源：baostock / AKShare")


# ── 主区域 ───────────────────────────────────────────────────────────────────

st.title("K线查看")

# 股票列表（从本地DB读取）
_all_codes = db.get_all_codes() or []

if not _all_codes:
    with st.container(border=True):
        st.markdown(
            """
            <div style="text-align: center; padding: 2.5rem 1rem;">
                <div style="font-size: 4rem; margin-bottom: 1rem;">📭</div>
                <h3 style="color: #374151;">本地数据库为空</h3>
                <p style="color: #6B7280;">
                    后台正在下载全市场数据，请稍候片刻后刷新页面。<br>
                    首次运行约需 10–30 分钟（视网络情况而定）。
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.stop()

# 构建选项列表
_options = ["请选择股票"] + [
    f"{s['code']}  {s.get('name', s['code'])}" for s in _all_codes
]

# ── 控件行 ────────────────────────────────────────────────────────────────────

_c1, _c2, _c3, _c4 = st.columns([3, 2, 2, 1])
with _c1:
    sel = st.selectbox("选择股票", options=_options, key="kl_view_sel",
                       label_visibility="collapsed",
                       placeholder="请选择或搜索股票…")
with _c2:
    period_label = st.selectbox("周期", ["日K", "周K", "月K"], index=0,
                                key="kl_view_period")
with _c3:
    range_label = st.selectbox(
        "时间范围",
        ["近3月", "近6月", "近1年", "近3年", "全部"],
        index=2, key="kl_view_range",
    )
with _c4:
    show_macd = st.checkbox("MACD", value=True, key="kl_view_macd")

# MA均线选择行
_ma_row = st.columns([1, 1, 1, 1, 6])
_kl_ma5  = _ma_row[0].checkbox("MA5",  value=True,  key="kl_ma5")
_kl_ma10 = _ma_row[1].checkbox("MA10", value=True,  key="kl_ma10")
_kl_ma20 = _ma_row[2].checkbox("MA20", value=True,  key="kl_ma20")
_kl_ma60 = _ma_row[3].checkbox("MA60", value=False, key="kl_ma60")
show_ma_periods = [p for p, s in [(5, _kl_ma5), (10, _kl_ma10), (20, _kl_ma20), (60, _kl_ma60)] if s]

# ── 空态占位 ──────────────────────────────────────────────────────────────────

if not sel or sel == "请选择股票":
    with st.container(border=True):
        st.markdown(
            """
            <div style="text-align: center; padding: 2.5rem 1rem;">
                <div style="font-size: 4rem; margin-bottom: 1rem;">🔍</div>
                <h3 style="color: #374151;">请在上方选择股票</h3>
                <p style="color: #6B7280;">
                    从下拉框选择或直接键入股票代码/名称进行搜索。
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.stop()

# ── 解析选中股票 ──────────────────────────────────────────────────────────────

parts    = sel.split()
sel_code = parts[0].strip()
sel_name = parts[1] if len(parts) > 1 else sel_code

# 计算起始日期
_today = datetime.date.today()
_range_map = {
    "近3月": (_today - datetime.timedelta(days=90)).isoformat(),
    "近6月": (_today - datetime.timedelta(days=180)).isoformat(),
    "近1年": (_today - datetime.timedelta(days=365)).isoformat(),
    "近3年": (_today - datetime.timedelta(days=1095)).isoformat(),
    "全部":  "1990-01-01",
}
start_date = _range_map[range_label]

df_raw = db.get_daily(sel_code, start=start_date)

if df_raw is None or df_raw.empty:
    st.warning(f"本地数据库中暂无 {sel_code} 的K线数据，请等待后台更新完成后刷新。")
    st.stop()

# 周期聚合
_period_map = {"日K": "D", "周K": "W", "月K": "M"}
period_code = _period_map[period_label]

if period_code == "W":
    df_plot = resample_weekly(df_raw)
elif period_code == "M":
    df_plot = resample_monthly(df_raw)
else:
    df_plot = df_raw.copy()

if df_plot.empty:
    st.warning("当前时间范围内无K线数据，请切换更大范围。")
    st.stop()

# ── 绘制K线图 ─────────────────────────────────────────────────────────────────

fig = build_kline_chart(
    df_plot,
    title=f"{sel_code}  {sel_name}  {period_label}",
    show_macd=show_macd,
    period=period_code,
    show_ma_periods=show_ma_periods,
)

st.plotly_chart(fig, use_container_width=True, config={
    "scrollZoom":           True,
    "displayModeBar":       True,
    "modeBarButtonsToAdd":  ["drawline", "eraseshape"],
    "modeBarButtonsToRemove": ["select2d", "lasso2d"],
})

# ── 基本信息卡片 ──────────────────────────────────────────────────────────────

last_row = df_plot.iloc[-1]
prev_row = df_plot.iloc[-2] if len(df_plot) >= 2 else last_row

_close  = float(last_row["close"])
_open   = float(last_row["open"])
_high   = float(last_row["high"])
_low    = float(last_row["low"])
_pct    = float(last_row.get("pct_change", 0) or 0)
_vol    = float(last_row.get("volume", 0) or 0)

_color = "#FF3333" if _pct >= 0 else "#33AA33"
_arrow = "▲" if _pct >= 0 else "▼"

st.markdown("---")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("收盘价",  f"{_close:.2f}",  f"{_arrow} {abs(_pct):.2f}%",
          delta_color="normal" if _pct >= 0 else "inverse")
m2.metric("今日开盘", f"{_open:.2f}")
m3.metric("今日最高", f"{_high:.2f}")
m4.metric("今日最低", f"{_low:.2f}")
m5.metric("成交量(手)", f"{_vol/100:,.0f}" if _vol else "—")
