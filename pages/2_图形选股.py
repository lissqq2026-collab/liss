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


# ── 形态分组辅助 ──────────────────────────────────────────────────────────────

def _group_catalog(catalog: list) -> dict[str, list]:
    """
    按形态 id 语义将 CATALOG 分为三组：
      - 趋势延续：red_three_soldiers / golden_cross_ma / ma_convergence /
                 ma60_breakout / volume_breakout
      - 底部反转：morning_star / hammer / macd_divergence /
                 double_bottom / oversold_bounce
      - 量价特征：low_vol_consolidation（及其余未归类形态）
    分组依据为 id 关键词匹配；无法匹配的条目按索引顺序放入"其他形态"。
    """
    trend_ids    = {"three_soldiers", "golden_cross_ma", "ma_convergence",
                    "ma60_breakout", "volume_breakout"}
    reversal_ids = {"morning_star", "hammer", "macd_divergence",
                    "double_bottom", "oversold_bounce"}
    vol_ids      = {"low_vol_consolidation"}

    groups: dict[str, list] = {
        "趋势延续": [],
        "底部反转": [],
        "量价特征": [],
        "其他形态": [],
    }
    for item in catalog:
        pid = item["id"]
        if pid in trend_ids:
            groups["趋势延续"].append(item)
        elif pid in reversal_ids:
            groups["底部反转"].append(item)
        elif pid in vol_ids:
            groups["量价特征"].append(item)
        else:
            groups["其他形态"].append(item)

    # 移除空分组，保持顺序
    return {k: v for k, v in groups.items() if v}


# ── 侧边栏 ───────────────────────────────────────────────────────────────────

from strategies.patterns import CATALOG

_groups = _group_catalog(CATALOG)

with st.sidebar:
    st.title("🔎 图形选股")
    st.caption("基于K线形态的量化筛选")

    st.markdown("---")
    st.markdown("#### 选择形态")

    selected_ids = []
    for group_name, items in _groups.items():
        st.markdown(f"**{group_name}**")
        for item in items:
            checked = st.checkbox(
                f"{item['name']}  \n{item['desc']}",
                key=f"pattern_{item['id']}",
                value=False,
            )
            if checked:
                selected_ids.append(item["id"])

    st.markdown("---")

    match_mode = st.radio(
        "匹配模式",
        options=["满足任一所选条件", "满足全部所选条件"],
        index=0,
    )

    scan_btn = st.button("开始图形选股", type="primary", use_container_width=True)

    st.markdown("---")
    st.caption("数据来自本地数据库")


# ── 主区域 ───────────────────────────────────────────────────────────────────

st.title("图形选股")

if not scan_btn:
    # 空状态引导卡片
    with st.container(border=True):
        st.markdown(
            """
            <div style="text-align: center; padding: 2rem 1rem;">
                <div style="font-size: 4rem; margin-bottom: 1rem;">🔎</div>
                <h3 style="margin-bottom: 0.5rem; color: #374151;">选择形态开始扫描</h3>
                <p style="color: #6B7280; font-size: 0.95rem;">
                    在左侧勾选一个或多个K线形态条件，<br>
                    选择匹配模式后点击「开始图形选股」，<br>
                    系统将自动扫描本地数据库中的全部股票。
                </p>
                <p style="color: #9CA3AF; font-size: 0.85rem; margin-top: 1rem;">
                    💡 需先在「K线查看」页面完成批量下载，才能使用本功能
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
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

with st.container(border=True):
    st.markdown(f"正在扫描本地数据库中共 **{total}** 只股票…（匹配模式：{match_mode}）")

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
    with st.container(border=True):
        st.markdown(
            """
            <div style="text-align: center; padding: 1.5rem 1rem;">
                <div style="font-size: 3rem; margin-bottom: 0.75rem;">📭</div>
                <h4 style="color: #374151;">未找到符合条件的股票</h4>
                <p style="color: #6B7280; font-size: 0.9rem;">
                    请尝试更换形态条件，或将匹配模式改为「满足任一所选条件」后重新扫描。
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.stop()

df_result = pd.DataFrame(results).sort_values("命中数", ascending=False).reset_index(drop=True)

st.success(f"共命中 {len(df_result)} 只股票（按命中数降序）")

# 结果表格：代码列设窄，命中数显示进度条
st.dataframe(
    df_result,
    use_container_width=True,
    column_config={
        "code":   st.column_config.TextColumn("代码", width="small"),
        "name":   st.column_config.TextColumn("名称", width="small"),
        "命中数": st.column_config.ProgressColumn(
            "命中数",
            min_value=0,
            max_value=len(selected_ids),
            format="%d",
        ),
        "命中形态": st.column_config.TextColumn("命中形态"),
    },
)

# ── 查看K线 ───────────────────────────────────────────────────────────────────

st.divider()
st.markdown("### 📈 查看K线详情")

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
        st.plotly_chart(fig, use_container_width=True, config={
            "scrollZoom": True,
            "displayModeBar": True,
            "modeBarButtonsToAdd": ["drawline", "eraseshape"],
            "modeBarButtonsToRemove": ["select2d", "lasso2d"],
        })
