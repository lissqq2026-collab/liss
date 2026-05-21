"""
pages/2_图形选股.py
A股图形选股页面 — 基于本地数据库，对全部已下载股票进行K线形态扫描
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

st.set_page_config(layout="wide", page_title="图形选股")

# 主容器留出顶部间距以避开 Streamlit Header，并适度收窄左右内边距
st.markdown("""
<style>
section[data-testid="stMain"] .block-container{
    padding-top: 3.5rem !important;
    padding-left: 1.2rem !important;
    padding-right: 1.2rem !important;
    max-width: 100% !important;
}
[data-testid="stPlotlyChart"] {
    width: 100% !important;
}
/* 画线桥接 textarea —— 可以 display:none，因为是 Python→JS 单向读取 */
div[class*="st-key-_draw_bridge_"] {
    display: none !important;
    height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
}
/* 行选中桥接 input —— 必须保持可聚焦才能触发 onBlur 提交，
   所以只视觉隐藏 + 移出视野，不能 display:none */
div[class*="st-key-row_sel_bridge"] {
    position: absolute !important;
    left: -9999px !important;
    top: -9999px !important;
    width: 1px !important;
    height: 1px !important;
    opacity: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    pointer-events: none !important;
    z-index: -1 !important;
}
</style>
""", unsafe_allow_html=True)

from ui.common import inject_compact_css
from ui.graph_screen.sidebar import render_sidebar
from ui.graph_screen.scanner import resolve_results
from ui.graph_screen import results_table, kline_panel

inject_compact_css()

config = render_sidebar()

st.title("图形选股")

results = resolve_results(config)
ctx = results_table.prepare(results, config)

left_col, right_col = st.columns([5, 7], gap="small")
with left_col:
    results_table.render_table(ctx)
with right_col:
    kline_panel.render(ctx)

kline_panel.render_keyboard_handler()
