"""
pages/2_图形选股.py
A股图形选股页面 — 基于本地数据库，对全部已下载股票进行K线形态扫描
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(layout="wide", page_title="图形选股")


# ── 缓存包装 ──────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def _cached_get_all_codes():
    from data.db import manager as db
    return db.get_all_codes()


# ── 颜色高亮（A股习惯：涨红跌绿） ────────────────────────────────────────────

def _highlight_pct(val):
    if pd.isna(val):
        return ""
    color = "red" if val > 0 else ("green" if val < 0 else "")
    return f"color: {color}" if color else ""


def _style_result(df: pd.DataFrame):
    styler = df.style
    if "pct_chg" in df.columns:
        styler = styler.map(_highlight_pct, subset=["pct_chg"])
    return styler


# ── 板块过滤辅助 ──────────────────────────────────────────────────────────────

def _board_match(code: str, boards: list) -> bool:
    if not boards:
        return True
    if "科创板" in boards and code.startswith("688"):
        return True
    if "创业板" in boards and (code.startswith("300") or code.startswith("301")):
        return True
    if "北交所" in boards and (code.startswith("8") or code.startswith("430")):
        return True
    if "沪深主板" in boards:
        if not (code.startswith("688") or code.startswith("3")
                or code.startswith("8") or code.startswith("430")):
            return True
    return False


# ── 形态分组辅助 ──────────────────────────────────────────────────────────────

def _group_catalog(catalog: list) -> dict[str, list]:
    trend_ids    = {"three_soldiers", "golden_cross_ma", "ma_convergence",
                    "ma60_breakout", "volume_breakout", "ma_bullish_arrangement",
                    "box_breakout", "ma_smooth_up", "arc_up", "close_above_ma5"}
    reversal_ids = {"morning_star", "hammer", "macd_divergence",
                    "double_bottom", "oversold_bounce"}
    vol_ids      = {"low_vol_consolidation", "low_vol_pullback"}

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

    return {k: v for k, v in groups.items() if v}


# ── 侧边栏 ───────────────────────────────────────────────────────────────────

from strategies.patterns import CATALOG

_groups = _group_catalog(CATALOG)

with st.sidebar:
    st.title("🔎 图形选股")
    st.caption("基于K线形态的量化筛选")

    st.markdown("---")

    # ── 股票池范围 ────────────────────────────────────────────────────────────
    st.markdown("#### 股票池范围")
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
        key="pg_match_mode",
    )

    sort_by = st.selectbox(
        "结果排序",
        options=["成交额降序", "命中数降序", "涨跌幅降序", "涨跌幅升序"],
        index=0,
        key="pg_sort_by",
    )

    scan_btn = st.button("开始图形选股", type="primary", use_container_width=True)

    st.markdown("---")
    st.caption("数据来自本地数据库")


# ── 主区域 ───────────────────────────────────────────────────────────────────

st.title("图形选股")

if not scan_btn:
    if "pattern_results" not in st.session_state:
        with st.container(border=True):
            st.markdown(
                """
                <div style="text-align: center; padding: 2rem 1rem;">
                    <div style="font-size: 4rem; margin-bottom: 1rem;">🔎</div>
                    <h3 style="margin-bottom: 0.5rem; color: #374151;">选择形态开始扫描</h3>
                    <p style="color: #6B7280; font-size: 0.95rem;">
                        在左侧选择股票池范围、成交额门槛，<br>
                        勾选一个或多个K线形态条件，<br>
                        点击「开始图形选股」自动扫描全库。
                    </p>
                    <p style="color: #9CA3AF; font-size: 0.85rem; margin-top: 1rem;">
                        💡 需先在「K线查看」页面完成批量下载，才能使用本功能
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        st.stop()
    results = st.session_state["pattern_results"]

else:
    # ── 执行扫描 ─────────────────────────────────────────────────────────────
    if not selected_ids:
        st.warning("请至少勾选一个形态条件后再开始扫描。")
        st.stop()

    all_codes = _cached_get_all_codes()
    if not all_codes:
        st.warning("本地数据库为空，请先在「K线查看」页面下载数据。")
        st.stop()

    # 板块过滤
    codes_list = [s for s in all_codes if _board_match(s["code"], board_filter)]
    total = len(codes_list)

    selected_patterns = {item["id"]: item for item in CATALOG if item["id"] in selected_ids}
    selected_names_map = {pid: selected_patterns[pid]["name"] for pid in selected_ids}
    require_all = (match_mode == "满足全部所选条件")

    from data.db import manager as _db_scan

    results = []
    done_count = 0

    with st.container(border=True):
        board_label = "、".join(board_filter) if board_filter else "全部板块"
        st.markdown(
            f"正在扫描 **{board_label}** 共 **{total}** 只股票…"
            f"（匹配模式：{match_mode} | 最低成交额：{min_amount_wan:,}万元）"
        )
        progress_bar = st.progress(0)
        status_text  = st.empty()

        # ── Step1：批量预加载（核心提速） ────────────────────────────────────
        status_text.text("正在批量加载K线数据…")
        all_daily = _db_scan.get_all_daily_bulk([s["code"] for s in codes_list])
        status_text.text(f"数据加载完成（{len(all_daily)} 只），开始形态匹配…")

        # ── Step2：并发形态匹配（全内存，无IO） ──────────────────────────────
        def _scan_one(stock_item):
            code = stock_item["code"]
            name = stock_item.get("name", code)
            try:
                df_daily = all_daily.get(code)
                if df_daily is None or len(df_daily) < 20:
                    return None

                # 成交额过滤
                if min_amount > 0 and "amount" in df_daily.columns:
                    last_amt = df_daily["amount"].iloc[-1]
                    if pd.isna(last_amt) or last_amt < min_amount:
                        return None

                hit_names = []
                for pid in selected_ids:
                    fn = selected_patterns[pid]["fn"]
                    try:
                        matched = fn(df_daily)
                    except Exception:
                        matched = False
                    if matched:
                        hit_names.append(selected_names_map[pid])

                hit_count = len(hit_names)
                if require_all and hit_count != len(selected_ids):
                    return None
                if not require_all and hit_count == 0:
                    return None

                last_close = float(df_daily["close"].iloc[-1]) if "close" in df_daily.columns else None
                last_pct   = float(df_daily["pct_change"].iloc[-1]) if "pct_change" in df_daily.columns else None
                last_amt   = df_daily["amount"].iloc[-1] if "amount" in df_daily.columns else None
                last_amt_wan = round(float(last_amt) / 10000, 1) if last_amt is not None and not pd.isna(last_amt) else None

                return {
                    "code":     code,
                    "name":     name,
                    "price":    last_close,
                    "pct_chg":  last_pct,
                    "成交额(万)": last_amt_wan,
                    "命中数":   hit_count,
                    "命中形态": "、".join(hit_names),
                }
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=24) as executor:
            futures = {executor.submit(_scan_one, s): s for s in codes_list}
            for future in as_completed(futures):
                done_count += 1
                progress_bar.progress(done_count / total)
                if done_count % 50 == 0 or done_count == total:
                    status_text.text(f"已扫描 {done_count}/{total}，命中 {len(results)} 只…")
                item = future.result()
                if item is not None:
                    results.append(item)

        status_text.text(f"扫描完成！共命中 {len(results)} 只股票。")
        progress_bar.progress(1.0)

    st.session_state["pattern_results"] = results


# ── 结果展示 ─────────────────────────────────────────────────────────────────

if not results:
    with st.container(border=True):
        st.markdown(
            """
            <div style="text-align: center; padding: 1.5rem 1rem;">
                <div style="font-size: 3rem; margin-bottom: 0.75rem;">📭</div>
                <h4 style="color: #374151;">未找到符合条件的股票</h4>
                <p style="color: #6B7280; font-size: 0.9rem;">
                    请尝试更换形态条件、降低成交额门槛，或将匹配模式改为「满足任一所选条件」后重新扫描。
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.stop()

df_result = pd.DataFrame(results)

# ── 排序 ─────────────────────────────────────────────────────────────────────
_sort_map = {
    "成交额降序": ("成交额(万)", False),
    "命中数降序": ("命中数",    False),
    "涨跌幅降序": ("pct_chg",  False),
    "涨跌幅升序": ("pct_chg",  True),
}
_sort_col, _sort_asc = _sort_map.get(sort_by, ("成交额(万)", False))
if _sort_col in df_result.columns:
    df_result = df_result.sort_values(_sort_col, ascending=_sort_asc, na_position="last")
df_result = df_result.reset_index(drop=True)

_top_row = st.columns([6, 1])
with _top_row[0]:
    st.success(f"共命中 {len(df_result)} 只股票（排序：{sort_by}）| 点击行查看K线↓")
with _top_row[1]:
    csv_bytes = df_result.to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇ 导出CSV", csv_bytes, "图形选股结果.csv", "text/csv", use_container_width=True)

# ── 预建K线选项 ───────────────────────────────────────────────────────────────
_kl_opts = ["请选择股票"] + [
    f"{row['code']}  {row['name']}" for row in df_result.to_dict("records")
]

# ── 自选股状态 ───────────────────────────────────────────────────────────────
from data.db import manager as _db_wl_pat
_wl_codes = {r["code"] for r in _db_wl_pat.get_watchlist()}
df_result["自选"] = df_result["code"].apply(lambda c: "⭐" if c in _wl_codes else "")

# ── 列配置 ────────────────────────────────────────────────────────────────────
_max_hits = int(df_result["命中数"].max()) if not df_result.empty else 1

_COL_CFG = {
    "自选":      st.column_config.TextColumn("自选",       width="small"),
    "code":      st.column_config.TextColumn("代码",       width="small"),
    "name":      st.column_config.TextColumn("名称",       width="small"),
    "price":     st.column_config.NumberColumn("收盘价",   format="%.2f"),
    "pct_chg":   st.column_config.NumberColumn("涨跌幅(%)", format="%+.2f"),
    "成交额(万)": st.column_config.NumberColumn("成交额(万)", format="%.0f"),
    "命中数":    st.column_config.ProgressColumn(
        "命中数", min_value=0, max_value=max(_max_hits, 1), format="%d"
    ),
    "命中形态":  st.column_config.TextColumn("命中形态"),
}

_pat_ev = st.dataframe(
    _style_result(df_result),
    use_container_width=True,
    selection_mode="single-row",
    on_select="rerun",
    column_config=_COL_CFG,
    key="pattern_table",
)

if _pat_ev.selection.rows:
    _sel_idx = _pat_ev.selection.rows[0]
    _sel_row = df_result.iloc[_sel_idx]
    st.session_state["kl_pattern_sel"] = _kl_opts[_sel_idx + 1]
    _in_wl = _sel_row["code"] in _wl_codes
    _wl_c1, _wl_c2 = st.columns([3, 1])
    with _wl_c1:
        st.caption(f"已选：**{_sel_row['code']}** {_sel_row['name']}")
    with _wl_c2:
        if _in_wl:
            if st.button("移出自选股", key="wl_toggle"):
                _db_wl_pat.remove_from_watchlist(_sel_row["code"])
                st.toast(f"已移出自选股：{_sel_row['code']}", icon="🗑️")
                st.rerun()
        else:
            if st.button("加入自选股", type="primary", key="wl_toggle"):
                _db_wl_pat.add_to_watchlist(_sel_row["code"], _sel_row["name"])
                st.toast(f"已加入自选股：{_sel_row['code']}", icon="⭐")
                st.rerun()


# ── K线查看 ───────────────────────────────────────────────────────────────────

st.divider()
st.markdown("### 📈 查看K线详情")

import datetime as _dt_kl_p
from data.db import manager as _db_kl_p
from strategies.chart import build_kline_chart as _build_kl_p

# 有结果时默认展开第一只股票
if "kl_pattern_sel" not in st.session_state and _kl_opts:
    st.session_state["kl_pattern_sel"] = _kl_opts[1] if len(_kl_opts) > 1 else _kl_opts[0]

_kl_sel = st.selectbox("选择股票查看K线", options=_kl_opts, key="kl_pattern_sel")

if _kl_sel and _kl_sel != "请选择股票":
    sel_code = _kl_sel.split()[0].strip()
    sel_name = _kl_sel.split()[1] if len(_kl_sel.split()) > 1 else sel_code

    _c1, _c2, _c3 = st.columns([2, 1, 1])
    with _c1:
        _kl_range_sel = st.selectbox(
            "时间范围", ["近3月", "近6月", "近1年", "近3年", "全部"],
            index=2, key="kl_pattern_range",
        )
    with _c2:
        _show_macd = st.checkbox("显示MACD", value=True, key="kl_pattern_macd")
    with _c3:
        _show_arr = st.checkbox("多头排列标志", value=True, key="kl_pattern_arr")

    _kl_ranges = {
        "近3月": (_dt_kl_p.date.today() - _dt_kl_p.timedelta(days=90)).isoformat(),
        "近6月": (_dt_kl_p.date.today() - _dt_kl_p.timedelta(days=180)).isoformat(),
        "近1年": (_dt_kl_p.date.today() - _dt_kl_p.timedelta(days=365)).isoformat(),
        "近3年": (_dt_kl_p.date.today() - _dt_kl_p.timedelta(days=1095)).isoformat(),
        "全部":  "2016-01-01",
    }

    df_kline = _db_kl_p.get_daily(sel_code, start=_kl_ranges[_kl_range_sel])

    if df_kline is None or df_kline.empty:
        st.warning(f"无法读取 {sel_code} 的K线数据。")
    else:
        fig = _build_kl_p(
            df_kline,
            title=f"{sel_code}  {sel_name}  日K",
            show_macd=_show_macd,
            show_ma_arrangement=_show_arr,
        )
        st.plotly_chart(fig, use_container_width=True, config={
            "scrollZoom": True,
            "displayModeBar": True,
            "modeBarButtonsToAdd": ["drawline", "eraseshape"],
            "modeBarButtonsToRemove": ["select2d", "lasso2d"],
        })
