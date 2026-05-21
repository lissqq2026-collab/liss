"""ui/pipeline.py — 三阶段筛选流水线执行"""
import streamlit as st
import pandas as pd

from ui.common import cached_get_all_a_stock_realtime, cached_technical_screen, cached_capital_flow_screen


def run_screening_pipeline(config: dict) -> dict:
    """执行三阶段筛选，显示进度 UI，返回 results dict。"""
    data_source    = config["data_source"]
    tushare_token  = config["tushare_token"]

    # ── 配置数据源 ──────────────────────────────────────────────────────────
    if "Tushare" in data_source:
        if not tushare_token:
            st.error("请先在左侧输入 Tushare Token。")
            st.stop()
        from data.fetcher import set_data_source
        set_data_source("tushare", {"token": tushare_token})
        source_key = "tushare"
    elif "Baostock" in data_source:
        from data.fetcher import set_data_source
        set_data_source("baostock")
        source_key = "baostock"
    else:
        from data.fetcher import set_data_source
        set_data_source("akshare")
        source_key = "akshare"

    # ── 进度容器 ────────────────────────────────────────────────────────────
    _prog = st.container(border=True)
    with _prog:
        st.markdown("**🔍 正在筛选…**")
        _s1 = st.status("阶段 1／3　基本面筛选", expanded=True)
        _s2 = st.status("阶段 2／3　技术面筛选", expanded=False)
        _s3 = st.status("阶段 3／3　北向资金筛选", expanded=False)

    try:
        # ── 阶段1：基本面筛选 ───────────────────────────────────────────────
        with _s1:
            from strategies.fundamental import screen as fundamental_screen

            st.write("正在拉取全市场实时行情…")
            df_all = cached_get_all_a_stock_realtime(source_key)
            if df_all.empty:
                st.error("实时行情获取失败，请检查网络后重试。")
                st.stop()

            st.write("正在按基本面参数筛选…")
            fundamental_params = {
                "pe_min": config["pe_min"],
                "pe_max": config["pe_max"],
                "pb_max": config["pb_max"],
                "total_mv_min": config["mv_min"],
                "total_mv_max": config["mv_max"],
                "roe_min": config["roe_min"],
            }
            df_fundamental = fundamental_screen(df_all, fundamental_params)
            n_fundamental = len(df_fundamental)
        _s1.update(label=f"✅ 阶段 1／3　基本面筛选　→ {n_fundamental} 只", state="complete", expanded=False)

        # ── 阶段2：技术面筛选 ───────────────────────────────────────────────
        with _s2:
            _s2.update(state="running", expanded=True)
            if df_fundamental.empty:
                df_stage2 = pd.DataFrame()
                n_technical = 0
                st.write("基本面无结果，跳过技术面筛选。")
            else:
                codes_fundamental = df_fundamental["code"].tolist()
                technical_params = {
                    "ma_periods": [5, 10, 20, 60],
                    "macd_fast": 12,
                    "macd_slow": 26,
                    "macd_signal": 9,
                    "kdj_k_oversold": config["kdj_k_oversold"],
                    "volume_amplify_ratio": config["volume_amplify_ratio"],
                    "volume_ma_period": 20,
                    "rsi_period": 14,
                    "rsi_oversold": config["rsi_oversold"],
                    "momentum_days": config["momentum_days"],
                    "history_days": 150,
                    "min_signals": int(config["min_signals"]),
                    "check_ma_bullish": config["check_ma_bullish"],
                    "check_price_above_ma20": config["check_price_above_ma20"],
                    "check_weekly_ma_bullish": config["check_weekly_ma_bullish"],
                    "check_macd_golden_cross": config["check_macd_golden_cross"],
                    "check_macd_above_zero": config["check_macd_above_zero"],
                    "check_macd_hist_expand": config["check_macd_hist_expand"],
                    "check_kdj_oversold_rec": config["check_kdj_oversold_rec"],
                    "check_kdj_golden_cross": config["check_kdj_golden_cross"],
                    "check_vol_price": config["check_vol_price"],
                    "check_rsi_oversold_rec": config["check_rsi_oversold_rec"],
                    "check_momentum": config["check_momentum"],
                }
                params_hashable = tuple(sorted(
                    (k, tuple(v) if isinstance(v, list) else v)
                    for k, v in technical_params.items()
                ))
                st.write(f"正在对 {n_fundamental} 只股票进行技术指标计算…")
                _tech_cache_key = ("tech_screen", tuple(codes_fundamental), params_hashable, source_key)
                _is_cached = (st.session_state.get("_tech_cache", {}).get("key") == _tech_cache_key)
                if _is_cached:
                    _prog_bar = None
                else:
                    _prog_bar = st.progress(0, text=f"技术指标计算中…  0 / {n_fundamental}")

                def _tech_progress(frac):
                    if _prog_bar:
                        done = int(frac * n_fundamental)
                        _prog_bar.progress(frac, text=f"技术指标计算中…  {done} / {n_fundamental}")

                df_technical = cached_technical_screen(
                    tuple(codes_fundamental),
                    params_hashable,
                    source_key,
                    progress_cb=_tech_progress,
                )
                if _prog_bar:
                    _prog_bar.empty()

                if df_technical.empty:
                    df_stage2 = pd.DataFrame()
                    n_technical = 0
                else:
                    codes_technical = df_technical["code"].tolist()
                    df_stage2 = df_fundamental[df_fundamental["code"].isin(codes_technical)].copy()
                    df_stage2 = df_stage2.merge(df_technical, on="code", how="left")
                    _sort_keys = ["signal_count"] + (["amount"] if "amount" in df_stage2.columns else [])
                    df_stage2 = df_stage2.sort_values(_sort_keys, ascending=False).reset_index(drop=True)
                    n_technical = len(df_stage2)
        _s2.update(label=f"✅ 阶段 2／3　技术面筛选　→ {n_technical} 只", state="complete", expanded=False)

        # ── 阶段3：北向资金筛选 ─────────────────────────────────────────────
        with _s3:
            _s3.update(state="running", expanded=True)
            capital_params = {
                "min_consecutive_days": config["min_consecutive_days"],
                "min_total_increase": 0,
                "markets": config["markets"],
            }
            _capital_params_key = tuple(sorted(
                (k, tuple(v) if isinstance(v, list) else v)
                for k, v in capital_params.items()
            ))
            _capital_cache_key = ("capital_flow", _capital_params_key, source_key)
            _cf_cached = st.session_state.get("_capital_cache", {}).get("key") == _capital_cache_key

            _cf_prog_bar = None
            if _cf_cached:
                st.write("北向资金数据已缓存，直接复用")
            else:
                st.write("正在分析北向资金持仓，候选较多时最长等待 3 分钟…")
                _cf_prog_bar = st.progress(0, text="北向资金分析中…")

            def _cf_progress(frac):
                if _cf_prog_bar:
                    _cf_prog_bar.progress(min(frac, 1.0), text=f"北向资金分析中…  {int(frac * 100)}%")

            df_capital, _cf_meta = cached_capital_flow_screen(
                _capital_params_key,
                source_key,
                progress_cb=None if _cf_cached else _cf_progress,
            )
            if _cf_prog_bar:
                _cf_prog_bar.empty()
        _s3.update(label=f"✅ 阶段 3／3　北向资金筛选　→ {len(df_capital)} 只", state="complete", expanded=False)

        # ── 三重共振 ────────────────────────────────────────────────────────
        if not df_stage2.empty and not df_capital.empty:
            triple_codes = set(df_stage2["code"].tolist()) & set(df_capital["code"].tolist())
            df_triple = df_stage2[df_stage2["code"].isin(triple_codes)].reset_index(drop=True)
        else:
            df_triple = pd.DataFrame()
        n_triple = len(df_triple)

        # 筛选完成，移除进度容器
        _prog.empty()

    except Exception as e:
        _prog.empty()
        st.error(f"筛选过程出错：{e}")
        st.stop()

    results = {
        "df_stage2":     df_stage2,
        "df_triple":     df_triple,
        "df_capital":    df_capital,
        "_cf_meta":      _cf_meta,
        "n_fundamental": n_fundamental,
        "n_technical":   n_technical,
        "n_triple":      n_triple,
    }
    st.session_state["screen_results"] = results
    return results
