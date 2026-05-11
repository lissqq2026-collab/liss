"""
pages/1_K线查看.py
A股K线查看页面 — 支持日/周/月周期、多时间范围、MACD显示，附批量下载功能
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datetime
import streamlit as st

st.set_page_config(layout="wide", page_title="K线查看")


# ── 时间范围映射 ──────────────────────────────────────────────────────────────

def _calc_start_date(range_label: str) -> str:
    today = datetime.date.today()
    ranges = {
        "近3月":  (today - datetime.timedelta(days=90)).isoformat(),
        "近6月":  (today - datetime.timedelta(days=180)).isoformat(),
        "近1年":  (today - datetime.timedelta(days=365)).isoformat(),
        "近3年":  (today - datetime.timedelta(days=1095)).isoformat(),
        "全部":   "2016-01-01",
    }
    return ranges[range_label]


# ── 数据更新逻辑 ──────────────────────────────────────────────────────────────

def _update_stock_data(code: str) -> tuple[bool, str]:
    """
    检查本地缓存，按需拉取数据并写库。
    返回 (success: bool, name: str)
    """
    from data.db import manager as db
    from data.fetcher import get_stock_history

    today_str = datetime.date.today().isoformat()
    meta = db.get_meta(code)

    if meta is None:
        # 从未下载过，拉取全量（约2016年至今）
        with st.spinner(f"首次下载 {code} 历史数据，请稍候…"):
            df_new = get_stock_history(code, days=3700)
    elif meta["last_date"] < today_str:
        # 有旧数据，增量更新
        with st.spinner(f"增量更新 {code}（上次更新至 {meta['last_date']}）…"):
            df_new = get_stock_history(code, days=90)
    else:
        # 已是最新，无需请求
        df_new = None

    if df_new is not None:
        if df_new.empty:
            if meta is None:
                return False, code
            # 网络失败但有旧数据，退化使用旧数据
            st.warning("网络获取失败，将使用本地已有数据。")
            name = meta.get("name", code)
            return True, name

        # 取股票名称
        if "name" in df_new.columns:
            name = str(df_new["name"].iloc[-1])
        else:
            name = meta["name"] if (meta and meta.get("name")) else code

        last_date = df_new["date"].max()
        if hasattr(last_date, "strftime"):
            last_date_str = last_date.strftime("%Y-%m-%d")
        else:
            last_date_str = str(last_date)[:10]

        db.upsert_daily(code, df_new)
        db.upsert_meta(code, name, last_date_str)
    else:
        name = meta.get("name", code) if meta else code

    return True, name


# ── 侧边栏 ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("📈 K线查看")
    st.caption("A股K线分析工具")

    st.markdown("---")
    st.markdown("#### 查看设置")

    code_input = st.text_input(
        "股票代码",
        placeholder="如 000001",
        max_chars=6,
    )

    period = st.selectbox(
        "K线周期",
        options=["日K", "周K", "月K"],
    )

    time_range = st.selectbox(
        "时间范围",
        options=["近3月", "近6月", "近1年", "近3年", "全部"],
        index=2,  # 默认"近1年"
    )

    show_macd = st.checkbox("显示MACD", value=True)

    view_btn = st.button("查看K线", type="primary", use_container_width=True)

    st.markdown("---")
    st.markdown("#### 批量下载")

    # ── 批量下载 expander ─────────────────────────────────────────────────────
    with st.expander("批量下载全市场数据"):
        st.caption("将全市场A股历史数据下载到本地数据库（约5000只，耗时较长）")
        st.warning("全市场下载约需30-60分钟，请保持网络连接")
        bulk_btn = st.button("开始批量下载", use_container_width=True)

        if bulk_btn:
            from data.fetcher import get_all_a_stock_realtime, get_stock_history
            from data.db import manager as db

            st.info("正在获取全市场股票列表…")
            df_all = get_all_a_stock_realtime()

            if df_all.empty:
                st.error("获取股票列表失败，请检查网络后重试。")
            else:
                codes_all = df_all["code"].tolist()
                names_map = dict(zip(df_all["code"], df_all.get("name", df_all["code"])))
                total = len(codes_all)
                st.info(f"共获取到 {total} 只股票，开始逐个下载…")

                progress_bar = st.progress(0)
                status_text = st.empty()
                error_count = 0

                for i, c in enumerate(codes_all):
                    status_text.text(f"[{i+1}/{total}] 正在下载：{c} {names_map.get(c, '')}")
                    try:
                        today_str = datetime.date.today().isoformat()
                        meta = db.get_meta(c)
                        if meta is not None and meta.get("last_date") == today_str:
                            # 已是最新，跳过
                            pass
                        else:
                            days = 3700 if meta is None else 90
                            df_hist = get_stock_history(c, days=days)
                            if not df_hist.empty:
                                name_c = str(df_hist["name"].iloc[-1]) if "name" in df_hist.columns else names_map.get(c, c)
                                last_d = df_hist["date"].max()
                                last_d_str = last_d.strftime("%Y-%m-%d") if hasattr(last_d, "strftime") else str(last_d)[:10]
                                db.upsert_daily(c, df_hist)
                                db.upsert_meta(c, name_c, last_d_str)
                    except Exception as exc:
                        error_count += 1
                        # 单只出错不中断
                        pass

                    progress_bar.progress((i + 1) / total)

                status_text.text(f"批量下载完成！成功 {total - error_count} 只，失败 {error_count} 只。")
                st.success("批量下载完毕，可在K线查看或图形选股中使用本地数据。")

    st.markdown("---")
    st.caption("v2.0 · A股分析工具")


# ── 主区域 ───────────────────────────────────────────────────────────────────

st.title("K 线查看")

if not view_btn:
    # 空状态引导卡片
    with st.container(border=True):
        st.markdown(
            """
            <div style="text-align: center; padding: 2rem 1rem;">
                <div style="font-size: 4rem; margin-bottom: 1rem;">🔍</div>
                <h3 style="margin-bottom: 0.5rem; color: #374151;">输入股票代码开始查看</h3>
                <p style="color: #6B7280; font-size: 0.95rem;">
                    在左侧输入6位股票代码，选择K线周期与时间范围，<br>
                    点击「查看K线」即可查看完整K线图与技术指标。
                </p>
                <p style="color: #9CA3AF; font-size: 0.85rem; margin-top: 1rem;">
                    💡 首次查看某只股票会自动从网络拉取历史数据，请稍候片刻
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.stop()

# 验证输入
code_clean = code_input.strip()
if not code_clean:
    st.error("请输入股票代码。")
    st.stop()

if not code_clean.isdigit() or len(code_clean) != 6:
    st.error(f"股票代码格式不正确：「{code_clean}」，请输入6位数字（如 000001）。")
    st.stop()

# 更新本地数据
ok, stock_name = _update_stock_data(code_clean)
if not ok:
    st.error(f"无法获取 {code_clean} 的数据，请确认代码是否正确或网络是否正常。")
    st.stop()

# 读取本地数据（按时间范围）
from data.db import manager as db
from strategies.chart import build_kline_chart, resample_weekly, resample_monthly

start_date = _calc_start_date(time_range)
df_local = db.get_daily(code_clean, start=start_date)

if df_local is None or df_local.empty:
    st.warning(f"本地数据库中 {code_clean} 在 {time_range} 内暂无数据。")
    st.stop()

# 按周期重采样
if period == "周K":
    df_plot = resample_weekly(df_local)
    period_label = "周K"
elif period == "月K":
    df_plot = resample_monthly(df_local)
    period_label = "月K"
else:
    df_plot = df_local.copy()
    period_label = "日K"

if df_plot.empty:
    st.warning("重采样后数据为空，请更换时间范围或周期后重试。")
    st.stop()

# 股票指标卡（放在图表上方）
col1, col2, col3 = st.columns(3)
col1.metric("股票代码", code_clean)
col2.metric("股票名称", stock_name)
col3.metric("数据条数", f"{len(df_plot)} 根K线")

# 绘制图表
chart_title = f"{code_clean}  {stock_name}  {period_label}"
period_code = {"日K": "D", "周K": "W", "月K": "M"}[period]
fig = build_kline_chart(df_plot, title=chart_title, show_macd=show_macd, period=period_code)
st.plotly_chart(fig, use_container_width=True, config={
    "scrollZoom": True,
    "displayModeBar": True,
    "modeBarButtonsToRemove": ["select2d", "lasso2d"],
})
