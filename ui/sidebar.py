"""ui/sidebar.py — 侧边栏：数据源 + 快速筛选 / 高级参数 / 数据维护 + CTA"""
import streamlit as st

from ui.updater_panel import render_updater_panel


def render_sidebar() -> dict:
    """渲染侧边栏全部控件，返回配置 dict。"""
    with st.sidebar:
        st.markdown("### 🔍 A 股选股工具")

        # ── 数据源（顶层，常驻可见）──
        data_source = st.radio(
            "数据源",
            options=["AKShare（免费，无需配置）", "Tushare Pro（需 Token）", "Baostock（免费，历史数据更准确）"],
            index=0,
        )

        tushare_token = ""
        if "Tushare" in data_source:
            tushare_token = st.text_input(
                "Tushare Token", type="password",
                placeholder="请输入 Tushare Pro Token",
                help="在 tushare.pro 注册后获取，免费账户有120积分",
            )
            if not tushare_token:
                st.warning("请输入 Token 后再运行筛选。")

        _source_info = {
            "AKShare": "✅ 实时行情 ✅ 历史K线 ✅ 北向资金",
            "Tushare": "✅ 实时行情 ✅ 历史K线 ✅ 北向资金流向 ❌ 个股持仓（需高积分）",
            "Baostock": "⚠️ 实时（降级AKShare）✅ 历史K线 ⚠️ 北向（降级AKShare）",
        }
        for _k, _info in _source_info.items():
            if _k in data_source:
                st.caption(_info)
                break

        st.markdown("---")

        # ── ⚡ 快速筛选（默认展开）──
        with st.expander("⚡ 快速筛选", expanded=True):
            _mv_presets = {"小盘 (20-200亿)": (20.0, 200.0), "中盘 (200-1000亿)": (200.0, 1000.0),
                           "大盘 (1000-10000亿)": (1000.0, 10000.0), "全部": (1.0, 100000.0)}
            _mv_sel = st.selectbox("市值快选", list(_mv_presets.keys()), key="mv_preset_sel")
            _mv_min_default, _mv_max_default = _mv_presets[_mv_sel]
            if "_mv_min_val" not in st.session_state or "_mv_preset_applied" not in st.session_state:
                st.session_state["_mv_min_val"] = _mv_min_default
                st.session_state["_mv_max_val"] = _mv_max_default
                st.session_state["_mv_preset_applied"] = _mv_sel
            elif st.session_state.get("_mv_preset_applied") != _mv_sel:
                st.session_state["_mv_min_val"] = _mv_min_default
                st.session_state["_mv_max_val"] = _mv_max_default
                st.session_state["_mv_preset_applied"] = _mv_sel
                st.session_state.pop("mv_min", None)
                st.session_state.pop("mv_max", None)
                st.rerun()

            st.caption("核心技术信号")
            check_ma_bullish = st.checkbox("日线均线多头排列（MA5>MA10>MA20>MA60）", True, key="chk_ma")
            check_macd_golden_cross = st.checkbox("MACD 金叉（DIF 上穿 DEA）", True, key="chk_macd_gc")
            check_kdj_oversold_rec = st.checkbox("KDJ 超卖回升", True, key="chk_kdj_os")
            check_vol_price = st.checkbox("放量上涨（量 ≥ 均量 × N）", True, key="chk_vol")

        # ── 🔬 高级参数（默认折叠）──
        with st.expander("🔬 高级参数", expanded=False):
            st.caption("基本面")
            _c1, _c2 = st.columns(2)
            pe_min = _c1.slider("PE 最小值", 0, 100, 0, 1, key="pe_min")
            pe_max = _c2.slider("PE 最大值", 1, 200, 100, 1, key="pe_max")
            pb_max = st.number_input("PB 上限", 0.1, 20.0, 5.0, 0.1, key="pb_max")

            _c3, _c4 = st.columns(2)
            mv_min = _c3.number_input("市值下限（亿）", 1.0, 10000.0,
                                      st.session_state.get("_mv_min_val", 20.0), 1.0, key="mv_min")
            mv_max = _c4.number_input("市值上限（亿）", 1.0, 100000.0,
                                      st.session_state.get("_mv_max_val", 1000.0), 10.0, key="mv_max")
            roe_min = st.slider("ROE 最低（%，0=不过滤）", 0, 50, 0, 1, key="roe_min",
                                help="ROE ≈ PB/PE×100，为近似估算值")

            st.markdown("---")
            st.caption("均线 / MACD 进阶")
            check_price_above_ma20 = st.checkbox("收盘价在 MA20 上方", key="chk_price_ma20")
            check_weekly_ma_bullish = st.checkbox("周线均线多头排列（WMA5>WMA10>WMA20）", key="chk_wma")
            check_macd_above_zero = st.checkbox("DIF 和 DEA 均在零轴上方", key="chk_macd_zero")
            check_macd_hist_expand = st.checkbox("MACD 红柱连续 3 日扩大", key="chk_macd_hist")

            st.markdown("---")
            st.caption("KDJ / 量价 / RSI / 动量")
            check_kdj_golden_cross = st.checkbox("KDJ 金叉（K 上穿 D）", key="chk_kdj_gc")
            kdj_k_oversold = 30
            if check_kdj_oversold_rec or check_kdj_golden_cross:
                kdj_k_oversold = st.slider("KDJ 超卖阈值（K <）", 5, 40, 30, key="kdj_k")

            volume_amplify_ratio = 2.0
            if check_vol_price:
                volume_amplify_ratio = st.slider("放量倍数", 1.0, 5.0, 2.0, 0.1, key="vol_ratio")

            check_rsi_oversold_rec = st.checkbox("RSI 超卖回升", key="chk_rsi")
            rsi_oversold = 25
            if check_rsi_oversold_rec:
                rsi_oversold = st.slider("RSI 超卖阈值（RSI <）", 10, 50, 25, key="rsi_thresh")

            check_momentum = st.checkbox("N 日涨幅为正", key="chk_mom")
            momentum_days = 5
            if check_momentum:
                momentum_days = st.slider("动量周期（日）", 1, 60, 5, key="mom_days")

            st.markdown("---")
            st.caption("资金流向")
            min_consecutive_days = st.slider("连续净流入天数", 1, 20, 5, key="cf_days")
            markets = st.multiselect("市场", ["沪股通", "深股通"], ["沪股通", "深股通"], key="cf_markets")

        # ── 🛠️ 数据维护（默认折叠）──
        with st.expander("🛠️ 数据维护", expanded=False):
            render_updater_panel()

        # ── 信号汇总 + 最少满足条件 ──
        _enabled_signal_count = sum([
            check_ma_bullish, check_price_above_ma20, check_weekly_ma_bullish,
            check_macd_golden_cross, check_macd_above_zero, check_macd_hist_expand,
            check_kdj_oversold_rec, check_kdj_golden_cross,
            check_vol_price, check_rsi_oversold_rec, check_momentum,
        ])
        st.caption(f"✅ 共启用 **{_enabled_signal_count} / 11** 个技术信号")
        min_signals = st.number_input(
            "最少满足条件数量", 1, 11, 2, 1, key="min_sigs",
            help="已启用条件中至少满足 N 个才通过",
        )

        # ── 主 CTA ──
        st.divider()
        st.caption("准备就绪后点击下方按钮启动三阶段筛选")
        run_btn = st.button("🚀 开始筛选", type="primary", use_container_width=True)

    return {
        "data_source": data_source, "tushare_token": tushare_token,
        "pe_min": pe_min, "pe_max": pe_max, "pb_max": pb_max,
        "mv_min": mv_min, "mv_max": mv_max, "roe_min": roe_min,
        "check_ma_bullish": check_ma_bullish,
        "check_price_above_ma20": check_price_above_ma20,
        "check_weekly_ma_bullish": check_weekly_ma_bullish,
        "check_macd_golden_cross": check_macd_golden_cross,
        "check_macd_above_zero": check_macd_above_zero,
        "check_macd_hist_expand": check_macd_hist_expand,
        "check_kdj_oversold_rec": check_kdj_oversold_rec,
        "kdj_k_oversold": kdj_k_oversold,
        "check_kdj_golden_cross": check_kdj_golden_cross,
        "check_vol_price": check_vol_price,
        "volume_amplify_ratio": volume_amplify_ratio,
        "check_rsi_oversold_rec": check_rsi_oversold_rec,
        "rsi_oversold": rsi_oversold,
        "check_momentum": check_momentum,
        "momentum_days": momentum_days,
        "min_signals": min_signals,
        "min_consecutive_days": min_consecutive_days,
        "markets": markets,
        "run_btn": run_btn,
    }
