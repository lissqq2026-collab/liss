"""
pages/2_图形选股.py
A股图形选股页面 — 基于本地数据库，对全部已下载股票进行K线形态扫描
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd

st.set_page_config(layout="wide", page_title="图形选股")


# ── 缓存包装 ──────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def _cached_get_all_codes():
    from data.db import manager as db
    return db.get_all_codes()


# ── 侧边栏 ───────────────────────────────────────────────────────────────────

from strategies.patterns import CATALOG

with st.sidebar:
    st.title("图形选股")

    st.markdown("#### 选择形态")
    selected_ids = []
    for item in CATALOG:
        checked = st.checkbox(
            f"**{item['name']}**  \n{item['desc']}",
            key=f"pattern_{item['id']}",
            value=False,
        )
        if checked:
            selected_ids.append(item["id"])

    st.divider()

    match_mode = st.radio(
        "匹配模式",
        options=["满足任一所选条件", "满足全部所选条件"],
        index=0,
    )

    scan_btn = st.button("开始图形选股", type="primary", use_container_width=True)


# ── 主区域 ───────────────────────────────────────────────────────────────────

st.title("图形选股")

if not scan_btn:
    st.info("请在左侧勾选形态条件，然后点击「开始图形选股」。")
    st.stop()

# 验证至少勾选了一个形态
if not selected_ids:
    st.warning("请至少勾选一个形态条件后再开始扫描。")
    st.stop()

# 获取已选形态的 fn 映射
selected_patterns = {item["id"]: item for item in CATALOG if item["id"] in selected_ids}
selected_names = {pid: selected_patterns[pid]["name"] for pid in selected_ids}

# 获取本地数据库中所有股票
codes_list = _cached_get_all_codes()
if not codes_list:
    st.warning("本地数据库为空，请先在「K线查看」页面下载数据。")
    st.stop()

total = len(codes_list)
st.info(f"本地数据库中共有 {total} 只股票，开始扫描…（匹配模式：{match_mode}）")

# ── 扫描逻辑 ─────────────────────────────────────────────────────────────────

from data.db import manager as db

progress_bar = st.progress(0)
status_text = st.empty()

results = []  # list of dict: {code, name, hit_count, hit_patterns}

require_all = (match_mode == "满足全部所选条件")

for i, stock_item in enumerate(codes_list):
    code = stock_item["code"]
    name = stock_item.get("name", code)

    status_text.text(f"[{i+1}/{total}] 扫描：{code}  {name}")
    progress_bar.progress((i + 1) / total)

    try:
        df_daily = db.get_daily(code)
        if df_daily is None or len(df_daily) < 20:
            # 数据不足，跳过
            continue

        hit_names = []
        for pid in selected_ids:
            fn = selected_patterns[pid]["fn"]
            try:
                matched = fn(df_daily)
            except Exception:
                matched = False
            if matched:
                hit_names.append(selected_names[pid])

        hit_count = len(hit_names)

        if require_all:
            if hit_count == len(selected_ids):
                results.append({
                    "code":     code,
                    "name":     name,
                    "命中数":   hit_count,
                    "命中形态": "、".join(hit_names),
                })
        else:
            if hit_count > 0:
                results.append({
                    "code":     code,
                    "name":     name,
                    "命中数":   hit_count,
                    "命中形态": "、".join(hit_names),
                })

    except Exception:
        # 单只股票异常不中断整体流程
        continue

status_text.text(f"扫描完成！共命中 {len(results)} 只股票。")
progress_bar.progress(1.0)

# ── 结果展示 ─────────────────────────────────────────────────────────────────

if not results:
    st.warning("未找到符合条件的股票。请尝试更换形态或改用「满足任一所选条件」模式。")
    st.stop()

df_result = pd.DataFrame(results).sort_values("命中数", ascending=False).reset_index(drop=True)

st.success(f"共命中 {len(df_result)} 只股票（按命中数降序）")
st.dataframe(
    df_result,
    use_container_width=True,
    column_config={
        "code":   st.column_config.TextColumn("代码"),
        "name":   st.column_config.TextColumn("名称"),
        "命中数": st.column_config.NumberColumn("命中数", format="%d"),
        "命中形态": st.column_config.TextColumn("命中形态"),
    },
)

# ── 查看K线 ───────────────────────────────────────────────────────────────────

st.divider()
st.subheader("查看命中股票K线")

option_labels = [f"{r['code']}  {r['name']}（命中{r['命中数']}）" for r in results]
selected_label = st.selectbox("选择股票查看K线", options=option_labels)

if selected_label:
    from strategies.chart import build_kline_chart

    # 解析选中的代码
    sel_code = selected_label.split()[0].strip()
    sel_name_raw = selected_label.split()[1] if len(selected_label.split()) > 1 else sel_code
    # 去掉括号部分
    sel_name = sel_name_raw.split("（")[0]

    df_kline = db.get_daily(sel_code)

    if df_kline is None or df_kline.empty:
        st.warning(f"无法读取 {sel_code} 的K线数据。")
    else:
        show_macd_detail = st.checkbox("显示MACD", value=True, key="detail_macd")
        fig = build_kline_chart(
            df_kline,
            title=f"{sel_code}  {sel_name}  日K",
            show_macd=show_macd_detail,
        )
        st.plotly_chart(fig, use_container_width=True)
