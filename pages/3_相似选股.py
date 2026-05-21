"""
pages/3_相似选股.py
A股相似K线选股页面 — 基于本地数据库，对全部已下载股票进行相似K线匹配
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import datetime
import plotly.graph_objects as go

st.set_page_config(layout="wide", page_title="相似选股")

from ui.common import inject_compact_css, empty_state, cached_get_all_codes
inject_compact_css()


# ── 日期默认值 ────────────────────────────────────────────────────────────────

today = datetime.date.today()
default_start = today - datetime.timedelta(days=60)


# ── 侧边栏 ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 🔍 相似选股")
    st.markdown("---")

    # 股票代码列表
    all_codes_meta = cached_get_all_codes()
    if all_codes_meta:
        code_options = [f"{item['code']} - {item['name']}" for item in all_codes_meta]
    else:
        code_options = []

    # 模板股票选择
    st.markdown("**模板股票**")
    st.caption("建议覆盖 30–60 个交易日以保证匹配稳定")
    template_option = st.selectbox(
        "选择模板股票",
        options=code_options if code_options else ["（数据库为空）"],
        index=0,
        label_visibility="collapsed",
        help="选择你想要找相似走势的基准股票",
        key="sim_template",
    )

    # 模板区间
    st.markdown("**模板区间**")
    col_date1, col_date2 = st.columns(2)
    with col_date1:
        date_start = st.date_input(
            "开始",
            value=default_start,
            max_value=today,
            key="sim_date_start",
        )
    with col_date2:
        date_end = st.date_input(
            "结束",
            value=today,
            max_value=today,
            key="sim_date_end",
        )

    st.markdown("---")

    # 相似度阈值
    st.markdown("**匹配参数**")
    min_similarity = st.slider(
        "相似度阈值",
        min_value=0.50,
        max_value=1.00,
        value=0.70,
        step=0.05,
        format="%.2f",
        help="综合相似度必须达到此阈值才纳入结果，越高越严格",
        key="sim_min_similarity",
    )

    top_n = st.slider(
        "结果数量 top_n",
        min_value=3,
        max_value=10,
        value=5,
        step=1,
        help="最多返回前N名相似股票",
        key="sim_top_n",
    )

    st.markdown("---")

    search_btn = st.button(
        "开始相似匹配",
        type="primary",
        use_container_width=True,
    )

    st.markdown("---")
    st.caption("数据来自本地数据库")


# ── 主区域 ───────────────────────────────────────────────────────────────────

st.title("相似K线选股")

if not search_btn:
    empty_state(
        "🔍",
        "相似K线选股",
        "在左侧选择模板股票与特征区间，扫描全市场找出走势最相似的股票。",
        hint="💡 需先在「K线查看」页面完成批量下载，才能使用本功能",
    )
    with st.expander("算法说明", expanded=False):
        st.markdown(
            "- **价格相似度（权重 70%）**：归一化收益率序列的 Pearson 相关系数\n"
            "- **量能相似度（权重 30%）**：相对均量序列的 Pearson 相关系数\n"
            "- 适合捕捉处于相同趋势阶段、潜在共振机会的同步票\n"
            "- 提高**相似度阈值**可让筛选更严格"
        )
    st.stop()


# ── 按钮点击后执行 ────────────────────────────────────────────────────────────

# 校验
if not code_options or template_option == "（数据库为空）":
    st.warning("本地数据库为空，请先在「K线查看」页面下载数据。")
    st.stop()

if date_start >= date_end:
    st.error("开始日期必须早于结束日期，请重新选择区间。")
    st.stop()

# 提取模板代码
template_code = template_option.split(" - ")[0].strip()

# 显示模板K线预览
from data.db import manager as db
from strategies.chart import build_kline_chart

st.markdown("### 模板K线预览")
df_template_preview = db.get_daily(
    template_code,
    start=date_start.isoformat(),
    end=date_end.isoformat(),
)

if df_template_preview is None or df_template_preview.empty:
    st.warning(f"无法获取 {template_code} 在所选区间的K线数据，请检查日期范围或先下载数据。")
    st.stop()

template_name = template_option.split(" - ")[1].strip() if " - " in template_option else template_code
fig_tmpl = build_kline_chart(
    df_template_preview,
    title=f"{template_code}  {template_name}  模板区间 {date_start} ~ {date_end}",
    show_macd=False,
    show_ma_periods=[5, 10, 20],
)
st.plotly_chart(fig_tmpl, use_container_width=True, key="sim_tmpl", config={
    "scrollZoom": True,
    "displayModeBar": True,
})

st.markdown("---")
st.markdown("### 相似匹配结果")

# 执行匹配
from strategies.similarity import find_similar_stocks

st.caption("通常需 10–60 秒，取决于本地股票池大小")
with st.spinner("正在匹配全市场K线，请稍候…"):
    results = find_similar_stocks(
        template_code=template_code,
        date_start=date_start.isoformat(),
        date_end=date_end.isoformat(),
        top_n=top_n,
        min_similarity=min_similarity,
        price_weight=0.7,
        exclude_self=True,
    )

# 无结果处理
if not results:
    threshold_pct = int(min_similarity * 100)
    st.warning(
        f"未找到相似度 ≥ {threshold_pct}% 的股票，建议降低阈值后重新匹配。\n\n"
        f"当前参数：模板={template_code}，区间={date_start}~{date_end}，"
        f"阈值={min_similarity:.0%}，top_n={top_n}"
    )
    st.stop()

st.success(f"共找到 {len(results)} 只相似股票（相似度阈值：{min_similarity:.0%}）")

# ── 结果展示：叠加对比 + 逐条详情 ────────────────────────────────────────────

tab_overlay, tab_detail = st.tabs(["📊 叠加对比", "📋 逐条详情"])

with tab_overlay:
    # 全部候选归一化曲线 + 模板叠加于一张图
    indices = list(range(1, len(results[0]["template_norm"]) + 1))
    fig_all = go.Figure()
    fig_all.add_trace(go.Scatter(
        x=indices,
        y=results[0]["template_norm"],
        name=f"模板({template_code})",
        line=dict(color="#FF3333", width=3),
    ))
    _palette = ["#1E90FF", "#FF8C00", "#9C27B0", "#00B894", "#E84393",
                "#0984E3", "#FDCB6E", "#6C5CE7", "#00CEC9", "#D63031"]
    for i, result in enumerate(results):
        fig_all.add_trace(go.Scatter(
            x=indices,
            y=result["candidate_norm"],
            name=f"{result['name']}({result['code']}) {result['similarity']:.0%}",
            line=dict(color=_palette[i % len(_palette)], width=1.5),
        ))
    fig_all.update_layout(
        title="全部候选 vs 模板 — 归一化累计收益率",
        xaxis_title="K线序号",
        yaxis_title="累计收益率",
        height=480,
        margin=dict(t=50, b=20),
        template="plotly_white",
        legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.01),
        hovermode="x unified",
    )
    st.plotly_chart(fig_all, use_container_width=True, key="sim_overlay")
    st.caption("模板（红，加粗）与各候选股归一化走势叠加，曲线越贴合越相似。")

with tab_detail:
    for rank, result in enumerate(results, start=1):
        code     = result["code"]
        name     = result["name"]
        sim      = result["similarity"]
        price_s  = result["price_sim"]
        vol_s    = result["vol_sim"]
        df_cand  = result["df_candidate"]
        tmpl_norm = result["template_norm"]
        cand_norm = result["candidate_norm"]

        with st.expander(f"{rank}. {name}（{code}） — 相似度 {sim:.1%}", expanded=(rank == 1)):
            # 两列布局：左-归一化走势对比，右-候选K线图
            col_left, col_right = st.columns(2)

            with col_left:
                # 归一化走势对比图
                indices = list(range(1, len(tmpl_norm) + 1))
                fig_norm = go.Figure()
                fig_norm.add_trace(go.Scatter(
                    x=indices,
                    y=tmpl_norm,
                    name=f"模板({template_code})",
                    line=dict(color="#FF3333", width=2),
                ))
                fig_norm.add_trace(go.Scatter(
                    x=indices,
                    y=cand_norm,
                    name=f"{name}({code})",
                    line=dict(color="#1E90FF", width=2),
                ))
                fig_norm.update_layout(
                    title="归一化走势对比",
                    xaxis_title="K线序号",
                    yaxis_title="累计收益率",
                    height=300,
                    margin=dict(t=40, b=20),
                    template="plotly_white",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                st.plotly_chart(fig_norm, use_container_width=True, key=f"norm_{code}")

            with col_right:
                # 候选股K线图
                fig_cand = build_kline_chart(
                    df_cand,
                    title=f"{code}  {name}  最近{len(df_cand)}根K线",
                    show_macd=False,
                    show_ma_periods=[5, 10, 20],
                )
                # 调小高度以适应并列布局
                fig_cand.update_layout(height=300, margin=dict(t=40, b=20, l=50, r=10))
                st.plotly_chart(fig_cand, use_container_width=True, key=f"cand_{code}")

            # 指标行（2列）
            metric_col1, metric_col2 = st.columns(2)
            with metric_col1:
                st.metric(
                    label="价格相似度",
                    value=f"{price_s:.1%}",
                    help="价格归一化序列的 Pearson 相关系数",
                )
            with metric_col2:
                if vol_s == -1.0:
                    st.metric(
                        label="量能相似度",
                        value="量能数据不足",
                        help="量能数据缺失或无效，综合相似度仅基于价格维度计算",
                    )
                else:
                    st.metric(
                        label="量能相似度",
                        value=f"{vol_s:.1%}",
                        help="量能归一化序列的 Pearson 相关系数",
                    )

            # 加入自选股按钮
            already_in = db.is_in_watchlist(code)
            if already_in:
                st.button(
                    f"✅ 已在自选股",
                    key=f"watchlist_{code}",
                    disabled=True,
                    use_container_width=False,
                )
            else:
                if st.button(
                    f"⭐ 加入自选股  {code} {name}",
                    key=f"watchlist_{code}",
                    type="primary",
                    use_container_width=False,
                ):
                    success = db.add_to_watchlist(code, name)
                    if success:
                        st.toast(f"已加入自选股：{code} {name}", icon="⭐")
                        st.rerun()
                    else:
                        st.toast(f"加入失败，请稍后重试", icon="❌")
