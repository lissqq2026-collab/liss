"""ui/graph_screen/scanner.py — 图形选股扫描：股票池过滤 + 并发形态匹配"""
import streamlit as st
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from data.db import manager as db
from strategies.patterns import CATALOG, arc_flow_score
from ui.common import empty_state, cached_get_all_codes
from ui.graph_screen.filters import board_match, is_index


def resolve_results(config: dict):
    """根据侧边栏配置返回扫描结果列表；未触发扫描时复用缓存或展示空态。

    可能调用 st.stop()（空库 / 未选形态 / 首次未扫描）。
    """
    scan_btn       = config["scan_btn"]
    selected_ids   = config["selected_ids"]
    board_filter   = config["board_filter"]
    match_mode     = config["match_mode"]
    min_amount     = config["min_amount"]
    min_amount_wan = config["min_amount_wan"]

    if not scan_btn:
        if "pattern_results" not in st.session_state:
            empty_state(
                "🔎", "选择形态开始扫描",
                "在左侧选择股票池、成交额门槛与一个或多个K线形态条件，点击「开始图形选股」自动扫描全库。",
                hint="💡 需先在「K线查看」页面完成批量下载，才能使用本功能",
            )
            st.stop()
        return st.session_state["pattern_results"]

    # ── 执行扫描 ─────────────────────────────────────────────────────────────
    if not selected_ids:
        st.warning("请至少勾选一个形态条件后再开始扫描。")
        st.stop()

    all_codes = cached_get_all_codes()
    if not all_codes:
        st.warning("本地数据库为空，请先在「K线查看」页面下载数据。")
        st.stop()

    # 板块过滤 + 排除指数类
    codes_list = [
        s for s in all_codes
        if board_match(s["code"], board_filter)
        and not is_index(s["code"], s.get("name", ""))
    ]
    total = len(codes_list)

    selected_patterns = {item["id"]: item for item in CATALOG if item["id"] in selected_ids}
    selected_names_map = {pid: selected_patterns[pid]["name"] for pid in selected_ids}
    require_all = (match_mode == "满足全部所选条件")

    results = []
    done_count = 0

    board_label = "、".join(board_filter) if board_filter else "全部板块"
    _scan_status = st.status(
        f"正在扫描 **{board_label}** 共 **{total}** 只股票…"
        f"（{match_mode} | 最低 {min_amount_wan:,}万元）",
    )
    # ── Step1：批量预加载（核心提速） ────────────────────────────────────
    all_daily = db.get_all_daily_bulk([s["code"] for s in codes_list])

    # ── Step2：并发形态匹配（全内存，无IO） ──────────────────────────────
    def _scan_one(stock_item):
        code = stock_item["code"]
        name = stock_item.get("name", code)
        try:
            df_daily = all_daily.get(code)
            if df_daily is None or len(df_daily) < 20:
                return None
            df_daily.attrs["code"] = code  # 供形态函数按板块区分涨跌幅上限

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

            try:
                flow_score = float(arc_flow_score(df_daily))
            except Exception:
                flow_score = 0.0

            return {
                "code":     code,
                "name":     name,
                "price":    last_close,
                "pct_chg":  last_pct,
                "成交额(万)": last_amt_wan,
                "命中数":   hit_count,
                "流畅度":   round(flow_score, 3),
                "命中形态": "、".join(hit_names),
            }
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=24) as executor:
        futures = {executor.submit(_scan_one, s): s for s in codes_list}
        for future in as_completed(futures):
            done_count += 1
            if done_count % 50 == 0 or done_count == total:
                _scan_status.update(label=f"已扫描 {done_count}/{total}，命中 {len(results)} 只…")
            item = future.result()
            if item is not None:
                results.append(item)

    _scan_status.update(label=f"扫描完成！共命中 {len(results)} 只股票。", state="complete")

    st.session_state["pattern_results"] = results
    st.session_state["_last_arc_selected"] = "arc_up" in selected_ids
    return results
