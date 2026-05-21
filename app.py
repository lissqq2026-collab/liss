"""app.py — A股选股工具 Streamlit 前端（选股 + 图表 双 Tab）"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

st.set_page_config(layout="wide", page_title="A股选股工具")

from ui.common import inject_compact_css
inject_compact_css()

from ui.sidebar import render_sidebar
from ui.pipeline import run_screening_pipeline
from ui.results import render_results
from ui.updater_panel import trigger_auto_update_once
from ui.kline_panel import render_kline_panel

# ── 页首触发后台增量更新（同会话幂等）──────────────────────────────────────────
trigger_auto_update_once()

# ── 侧边栏：参数 + 数据维护（已整合至 render_sidebar）────────────────────────
config = render_sidebar()

# ── 主区域：双 Tab ─────────────────────────────────────────────────────────────
st.title("A 股选股工具")

tab_screen, tab_chart = st.tabs(["🔍 选股流水线", "📈 图表"])

with tab_screen:
    if config["run_btn"]:
        results = run_screening_pipeline(config)
    elif "screen_results" in st.session_state:
        st.caption("ℹ️ 当前显示上一次筛选结果。修改参数后请重新点击「开始筛选」")
        results = st.session_state["screen_results"]
    else:
        results = None
        st.markdown("#### 欢迎使用 A股三阶段选股工具")
        c1, c2, c3 = st.columns(3)
        with c1:
            with st.container(border=True):
                st.markdown("**第一阶段：基本面**")
                st.caption("市值、PE/PB 范围过滤，快速缩小股票池")
        with c2:
            with st.container(border=True):
                st.markdown("**第二阶段：技术面**")
                st.caption("均线、MACD、KDJ、量价、RSI 多信号共振筛选")
        with c3:
            with st.container(border=True):
                st.markdown("**第三阶段：北向资金**")
                st.caption("沪深港通持股变动验证主力资金方向")
        st.info("在左侧设置筛选参数后点击「开始筛选」即可开始。", icon="👈")

    if results is not None:
        render_results(results, config)

with tab_chart:
    # 支持从选股结果跳转：kline_jump_code / intra_jump_code
    default_code = st.session_state.pop("kline_jump_code", None) or \
                   st.session_state.pop("intra_jump_code", None)
    render_kline_panel(default_code=default_code, key_prefix="main_chart")
