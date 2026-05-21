"""ui/graph_screen/sidebar.py — 图形选股侧边栏：股票池 / 形态选择 / 匹配排序"""
import streamlit as st

from strategies.patterns import CATALOG
from ui.graph_screen.filters import group_catalog


def render_sidebar() -> dict:
    """渲染图形选股侧边栏全部控件，返回配置 dict。"""
    _groups = group_catalog(CATALOG)

    with st.sidebar:
        st.markdown("### 🔎 图形选股")
        st.caption("基于K线形态的量化筛选")

        # 启用数徽章：统计已激活的快速筛选项（板块 + 成交额门槛 + 已选形态数）
        _board_n   = len(st.session_state.get("pg_board_filter", []))
        _amount_on = st.session_state.get("pg_min_amount", 5000) > 0
        _pattern_n = sum(
            len(st.session_state.get(f"pattern_group_{g}", []))
            for g in _groups
        )
        _badge_n = _board_n + (1 if _amount_on else 0) + _pattern_n

        st.markdown("---")

        # ── 快速筛选 ─────────────────────────────────────────────────────────
        st.markdown(f"**🎯 快速筛选**　`已启用 {_badge_n}`")
        board_filter = st.multiselect(
            "板块筛选",
            options=["科创板", "创业板", "沪深主板", "北交所"],
            default=[],
            placeholder="默认：全部板块",
            help="不选则扫描全部板块；多选取并集",
            key="pg_board_filter",
        )

        min_amount_wan = st.number_input(
            "最低日成交额（万元）",
            min_value=0, max_value=200000, value=5000, step=1000,
            help="过滤低流动性股票，建议≥5000万",
            key="pg_min_amount",
        )
        min_amount = min_amount_wan * 10000  # 转换为元

        st.markdown(f"**形态条件**　`已选 {_pattern_n}`")
        selected_ids = []
        for group_name, items in _groups.items():
            _opts = {item["name"]: item["id"] for item in items}
            _g_n = len(st.session_state.get(f"pattern_group_{group_name}", []))
            _g_label = f"{group_name}（{_g_n}）" if _g_n else group_name
            _selected_names = st.multiselect(
                _g_label,
                options=list(_opts.keys()),
                default=[],
                placeholder=f"选择{group_name}形态…",
                key=f"pattern_group_{group_name}",
            )
            for _n in _selected_names:
                selected_ids.append(_opts[_n])

        st.markdown("---")

        # ── 高级筛选 ─────────────────────────────────────────────────────────
        with st.expander("⚙️ 高级筛选", expanded=False):
            match_mode = st.radio(
                "匹配模式",
                options=["满足任一所选条件", "满足全部所选条件"],
                index=0,
                key="pg_match_mode",
            )

            sort_by = st.selectbox(
                "结果排序",
                options=["流畅度降序", "命中数降序"],
                index=0,
                key="pg_sort_by",
                help="流畅度：基于MA10曲线几何分析——转角平滑、曲率一致、弧形圆润者高分（0~1）",
            )

        st.caption(f"已选 {len(selected_ids)} 个形态")
        scan_btn = st.button("开始图形选股", type="primary", width="stretch")

        st.markdown("---")
        st.caption("数据来自本地数据库")

    return {
        "board_filter":   board_filter,
        "min_amount":     min_amount,
        "min_amount_wan": min_amount_wan,
        "selected_ids":   selected_ids,
        "match_mode":     match_mode,
        "sort_by":        sort_by,
        "scan_btn":       scan_btn,
    }
