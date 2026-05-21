"""strategies/chart.py — Plotly K线图渲染（A股配色·专业版）

技术指标面板（均可选）：
  MACD / RSI / KDJ / OBV（叠加成交量）
  Bollinger Bands（叠加主图）
  支撑/压力位（主图水平虚线）
  均线多头/空头排列标记
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ═══════════════════════════════════════════════════════════════════
#  配色体系
# ═══════════════════════════════════════════════════════════════════
_UP   = "#FF3333"  # 涨（红）
_DOWN = "#33AA33"  # 跌（绿）
_MA   = {"MA5": "#FFB800", "MA10": "#FF6600", "MA20": "#9900CC", "MA60": "#0088FF"}

# 网格线 — 低对比度，不与数据竞争
_GRID_COLOR = "#F2F2F2"

# Bollinger
_BB_FILL   = "rgba(100,149,237,0.08)"   # 淡蓝填充
_BB_LINE   = "rgba(100,149,237,0.35)"   # 淡蓝虚线

# RSI
_RSI_LINE       = "#9966CC"
_RSI_OVERBOUGHT = "#FF3333"  # 70 超买线
_RSI_OVERSOLD   = "#33AA33"  # 30 超卖线

# KDJ
_KDJ_K = "#0088FF"
_KDJ_D = "#FFB800"
_KDJ_J = "#CC33AA"

# OBV
_OBV_LINE = "#3366CC"

# 支撑/压力
_SR_SUPPORT    = "#33AA33"
_SR_RESISTANCE = "#FF3333"


# ═══════════════════════════════════════════════════════════════════
#  辅助计算函数
# ═══════════════════════════════════════════════════════════════════

def _ema(s: pd.Series, n: int) -> pd.Series:
    """指数移动平均（国内软件惯例：adjust=False）"""
    return s.ewm(span=n, adjust=False).mean()


def _calc_bollinger(close: pd.Series, period: int = 20, num_std: float = 2.0):
    """
    计算 Bollinger Bands (布林带)。

    返回：(upper, middle, lower) 三个 Series。
    middle = MA20, upper/lower = middle ± num_std * σ
    """
    middle = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def _calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """计算 RSI 指标，返回 0-100 的 Series。"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    return 100 - (100 / (1 + rs))


def _calc_kdj(high: pd.Series, low: pd.Series, close: pd.Series,
              n: int = 9, m1: int = 3, m2: int = 3):
    """
    计算 KDJ 指标。

    返回：(K, D, J) 三个 Series，范围 0-100。
    """
    low_n = low.rolling(window=n, min_periods=1).min()
    high_n = high.rolling(window=n, min_periods=1).max()
    rsv = (close - low_n) / (high_n - low_n + 1e-9) * 100
    k = rsv.ewm(com=m1 - 1, adjust=False).mean()
    d = k.ewm(com=m2 - 1, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


def _calc_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """
    计算 OBV (能量潮)。

    规则：收盘 > 前收 → 累加成交量；收盘 < 前收 → 累减成交量；
         收盘 = 前收 → OBV 不变。
    """
    direction = np.sign(close.diff().fillna(0))
    obv = (direction * volume).cumsum()
    obv.iloc[0] = 0
    return obv


def _calc_sr_levels(df: pd.DataFrame, lookback: int = 90,
                    n_levels: int = 5) -> tuple[list[float], list[float]]:
    """
    基于局部极值计算支撑/压力位。

    参数：
        lookback: 回溯K线根数
        n_levels: 最多返回的支撑/压力数量

    返回：(supports, resistances)
    """
    if len(df) < 20:
        return [], []

    recent = df.tail(min(lookback, len(df))).reset_index(drop=True)
    highs = recent["high"].values
    lows = recent["low"].values

    window = max(3, len(recent) // 15)

    supports = []
    resistances = []

    for i in range(window, len(recent) - window):
        # 局部最高 → 压力位
        if highs[i] == max(highs[i - window: i + window + 1]):
            resistances.append(highs[i])
        # 局部最低 → 支撑位
        if lows[i] == min(lows[i - window: i + window + 1]):
            supports.append(lows[i])

    # 去重 + 合并相近价位（1.5% 以内视为同一区域）
    def _dedup(levels: list[float], eps_pct: float = 1.5) -> list[float]:
        if not levels:
            return []
        levels = sorted(set(round(v, 2) for v in levels))
        merged = [levels[0]]
        for v in levels[1:]:
            if (v - merged[-1]) / merged[-1] * 100 > eps_pct:
                merged.append(v)
            else:
                merged[-1] = round((merged[-1] + v) / 2, 2)
        return merged

    supports = _dedup(supports)
    resistances = _dedup(resistances)

    current = recent["close"].iloc[-1]

    # 支撑位必须在当前价下方，压力位必须在当前价上方
    supports = [s for s in supports if s < current]
    resistances = [r for r in resistances if r > current]

    # 按距离当前价排序（最近的优先）
    supports.sort(key=lambda x: current - x)
    resistances.sort(key=lambda x: x - current)

    return supports[:n_levels], resistances[:n_levels]


def _ma_bullish_ranges(dates: pd.Series, ma5, ma10, ma20, ma60) -> list:
    """返回 MA5>MA10>MA20>MA60 成立的连续日期区间 [(x0, x1), ...]"""
    valid = ma5.notna() & ma10.notna() & ma20.notna() & ma60.notna()
    bull = valid & (ma5 > ma10) & (ma10 > ma20) & (ma20 > ma60)
    ranges, in_r, x0 = [], False, None
    for i, (b, d) in enumerate(zip(bull, dates)):
        if b and not in_r:
            in_r, x0 = True, d
        elif not b and in_r:
            in_r = False
            ranges.append((x0, dates.iloc[i - 1]))
    if in_r and x0 is not None:
        ranges.append((x0, dates.iloc[-1]))
    return ranges


def _ma_bearish_ranges(dates: pd.Series, ma5, ma10, ma20, ma60) -> list:
    """返回 MA5<MA10<MA20<MA60 成立的连续日期区间 [(x0, x1), ...]"""
    valid = ma5.notna() & ma10.notna() & ma20.notna() & ma60.notna()
    bear = valid & (ma5 < ma10) & (ma10 < ma20) & (ma20 < ma60)
    ranges, in_r, x0 = [], False, None
    for i, (b, d) in enumerate(zip(bear, dates)):
        if b and not in_r:
            in_r, x0 = True, d
        elif not b and in_r:
            in_r = False
            ranges.append((x0, dates.iloc[i - 1]))
    if in_r and x0 is not None:
        ranges.append((x0, dates.iloc[-1]))
    return ranges


# ═══════════════════════════════════════════════════════════════════
#  买卖点信号（MACD 金叉/死叉 + 顶/底背离）
# ═══════════════════════════════════════════════════════════════════

def _find_local_extrema(s: np.ndarray, window: int = 5):
    """返回 (low_idx_list, high_idx_list)，严格局部极值（左右 window 范围内最低/最高）"""
    n = len(s)
    lows, highs = [], []
    for i in range(window, n - window):
        seg = s[i - window:i + window + 1]
        v = s[i]
        if v == seg.min() and (seg == v).sum() == 1:
            lows.append(i)
        elif v == seg.max() and (seg == v).sum() == 1:
            highs.append(i)
    return lows, highs


def detect_buy_sell_signals(close: pd.Series, dif: pd.Series, dea: pd.Series,
                            lookback_days: int = 120,
                            divergence_window: int = 5,
                            divergence_max_gap: int = 30):
    """检测 MACD 金叉/死叉 + 顶/底背离。

    返回 {idx: {"side": "buy"|"sell", "labels": [...]}}（同侧 3 根内的信号合并）。
    """
    n = len(close)
    if n < 30:
        return {}
    c = close.values.astype(float)
    d = dif.values.astype(float)
    de = dea.values.astype(float)

    raw_buy, raw_sell = {}, {}
    start = max(1, n - lookback_days)
    for i in range(start, n):
        if np.isnan(d[i]) or np.isnan(de[i]) or np.isnan(d[i - 1]) or np.isnan(de[i - 1]):
            continue
        prev_diff = d[i - 1] - de[i - 1]
        cur_diff  = d[i]     - de[i]
        if prev_diff <= 0 and cur_diff > 0:
            lbl = "0轴下金叉" if d[i] < 0 else "金叉"
            raw_buy.setdefault(i, []).append(lbl)
        elif prev_diff >= 0 and cur_diff < 0:
            lbl = "0轴上死叉" if d[i] > 0 else "死叉"
            raw_sell.setdefault(i, []).append(lbl)

    # 底背离：价格创近期新低，DIF 反而抬高（且 DIF 仍在零轴下方更可靠）
    lows, highs = _find_local_extrema(c, window=divergence_window)
    lows = [i for i in lows if i >= start]
    highs = [i for i in highs if i >= start]

    for j in range(1, len(lows)):
        i2, i1 = lows[j], lows[j - 1]
        if i2 - i1 > divergence_max_gap or i2 - i1 < 3:
            continue
        if c[i2] < c[i1] and d[i2] > d[i1] and d[i2] < 0:
            raw_buy.setdefault(i2, []).append("底背离")

    for j in range(1, len(highs)):
        i2, i1 = highs[j], highs[j - 1]
        if i2 - i1 > divergence_max_gap or i2 - i1 < 3:
            continue
        if c[i2] > c[i1] and d[i2] < d[i1] and d[i2] > 0:
            raw_sell.setdefault(i2, []).append("顶背离")

    def _merge(raw: dict, side: str):
        if not raw:
            return {}
        idxs = sorted(raw.keys())
        out = {}
        cur_anchor = idxs[0]
        cur_labels = list(raw[cur_anchor])
        for k in idxs[1:]:
            if k - cur_anchor <= 3:
                for lb in raw[k]:
                    if lb not in cur_labels:
                        cur_labels.append(lb)
            else:
                out[cur_anchor] = {"side": side, "labels": cur_labels}
                cur_anchor = k
                cur_labels = list(raw[k])
        out[cur_anchor] = {"side": side, "labels": cur_labels}
        return out

    merged = {}
    merged.update(_merge(raw_buy, "buy"))
    merged.update(_merge(raw_sell, "sell"))
    return merged


# ═══════════════════════════════════════════════════════════════════
#  周期转换
# ═══════════════════════════════════════════════════════════════════

def resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """日K → 周K"""
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.set_index("date")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if "amount" in d.columns:
        agg["amount"] = "sum"
    w = d.resample("W").agg(agg).dropna(subset=["close"])
    w["pct_change"] = w["close"].pct_change() * 100
    return w.reset_index()


def resample_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """日K → 月K"""
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.set_index("date")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if "amount" in d.columns:
        agg["amount"] = "sum"
    try:
        m = d.resample("ME").agg(agg).dropna(subset=["close"])
    except ValueError:
        m = d.resample("M").agg(agg).dropna(subset=["close"])
    m["pct_change"] = m["close"].pct_change() * 100
    return m.reset_index()


# ═══════════════════════════════════════════════════════════════════
#  主函数
# ═══════════════════════════════════════════════════════════════════

def build_kline_chart(df: pd.DataFrame, title: str = "", show_macd: bool = True,
                      period: str = "D", show_ma_periods: list = None,
                      show_ma_arrangement: bool = True,
                      show_bollinger: bool = False,
                      show_rsi: bool = False,
                      show_sr_levels: bool = False,
                      show_kdj: bool = False,
                      show_obv: bool = False,
                      show_ma_arc_fit: bool = False,
                      arc_fit_window: int = 60,
                      show_buy_sell: bool = False,
                      buy_sell_lookback: int = 120,
                      user_shapes: list = None,
                      initial_xrange: list = None) -> go.Figure:
    """
    绘制 K 线图（多面板、多技术指标）。

    参数（* 为新增）：
        df                   — 含 date, open, high, low, close, volume
        title                — 图表标题
        show_macd            — 显示 MACD 面板
        period               — "D"=日, "W"=周, "M"=月
        show_ma_periods      — 要显示的均线列表，None=全部 [5,10,20,60]
        show_ma_arrangement  — 显示多头/空头排列区域标记
      * show_bollinger       — 叠加 Bollinger Bands 到主图
      * show_rsi             — 显示 RSI(14) 子面板
      * show_sr_levels       — 标注支撑/压力位水平线
      * show_kdj             — 显示 KDJ 子面板
      * show_obv             — OBV 能量潮叠加在成交量面板
    """
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]
    dates  = df["date"]

    # ── 均线计算 ─────────────────────────────────────────────────
    _ma_show = set(show_ma_periods) if show_ma_periods is not None else {5, 10, 20, 60}
    _ma_all  = {
        5:  close.rolling(5).mean(),
        10: close.rolling(10).mean(),
        20: close.rolling(20).mean(),
        60: close.rolling(60).mean(),
    }
    _ma_lbl     = {5: "MA5", 10: "MA10", 20: "MA20", 60: "MA60"}
    _ma_computed = {_ma_lbl[n]: _ma_all[n] for n in [5, 10, 20, 60] if n in _ma_show}

    # ── MACD ─────────────────────────────────────────────────────
    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    dif   = ema12 - ema26
    dea   = _ema(dif, 9)
    hist  = (dif - dea) * 2

    # ── Bollinger ────────────────────────────────────────────────
    if show_bollinger:
        bb_upper, bb_middle, bb_lower = _calc_bollinger(close)

    # ── RSI ──────────────────────────────────────────────────────
    if show_rsi:
        rsi_series = _calc_rsi(close)

    # ── KDJ ──────────────────────────────────────────────────────
    if show_kdj:
        kdj_k, kdj_d, kdj_j = _calc_kdj(high, low, close)

    # ── OBV ──────────────────────────────────────────────────────
    if show_obv:
        obv_series = _calc_obv(close, volume)

    # ── 支撑/压力位 ──────────────────────────────────────────────
    if show_sr_levels:
        sr_supports, sr_resistances = _calc_sr_levels(df)

    # ═════════════════════════════════════════════════════════════
    #  子图布局
    # ═════════════════════════════════════════════════════════════
    # Row 1 = K 线 + MA,  Row 2 = 成交量 (+OBV)
    # 后续行 = MACD / RSI / KDJ（按顺序）
    extra_panels: list[str] = []
    if show_macd:
        extra_panels.append("macd")
    if show_rsi:
        extra_panels.append("rsi")
    if show_kdj:
        extra_panels.append("kdj")

    n_extra   = len(extra_panels)
    n_rows    = 2 + n_extra
    row_of    = {name: 3 + i for i, name in enumerate(extra_panels)}  # 面板名 → 行号

    _height_lookup = {
        2: [0.74, 0.26],
        3: [0.64, 0.18, 0.18],
        4: [0.56, 0.14, 0.15, 0.15],
        5: [0.50, 0.11, 0.13, 0.13, 0.13],
    }
    heights = _height_lookup[n_rows]

    # specs: 成交量行若叠加 OBV 则启用 secondary_y
    specs = [[{"secondary_y": False}] for _ in range(n_rows)]
    if show_obv:
        specs[1] = [{"secondary_y": True}]

    fig = make_subplots(
        rows=n_rows, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=heights,
        specs=specs,
    )

    # ═════════════════════════════════════════════════════════════
    #  Row 1 — 主图：K线 + MA + Bollinger + 支撑/压力位
    # ═════════════════════════════════════════════════════════════

    # 涨跌幅序列（用于 hover）
    pct_change = close.pct_change() * 100

    # customdata: [pct_change, MA5, MA10, MA20, MA60]
    cd_ma5  = _ma_all[5]  if 5  in _ma_show else pd.Series([np.nan] * len(df), index=df.index)
    cd_ma10 = _ma_all[10] if 10 in _ma_show else pd.Series([np.nan] * len(df), index=df.index)
    cd_ma20 = _ma_all[20] if 20 in _ma_show else pd.Series([np.nan] * len(df), index=df.index)
    cd_ma60 = _ma_all[60] if 60 in _ma_show else pd.Series([np.nan] * len(df), index=df.index)

    # 构建 hover 模板（仅显示启用的均线）
    _hover_lines = [
        "日期: %{x|%Y-%m-%d}",
        "开盘: %{open:.2f}",
        "最高: %{high:.2f}",
        "最低: %{low:.2f}",
        "收盘: %{close:.2f}",
        "涨跌幅: %{customdata[0]:.2f}%",
    ]
    _ma_cd_idx = {5: 1, 10: 2, 20: 3, 60: 4}
    for p in [5, 10, 20, 60]:
        if p in _ma_show:
            _hover_lines.append(f"{_ma_lbl[p]}: %{{customdata[{_ma_cd_idx[p]}]:.2f}}")

    customdata = np.column_stack([
        pct_change.fillna(np.nan).values,
        cd_ma5.fillna(np.nan).values,
        cd_ma10.fillna(np.nan).values,
        cd_ma20.fillna(np.nan).values,
        cd_ma60.fillna(np.nan).values,
    ])

    fig.add_trace(go.Candlestick(
        x=dates,
        open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="K线",
        increasing=dict(line=dict(color=_UP,   width=1), fillcolor=_UP),
        decreasing=dict(line=dict(color=_DOWN, width=1), fillcolor=_DOWN),
        customdata=customdata,
        hovertemplate="<br>".join(_hover_lines) + "<extra></extra>",
        showlegend=True,
    ), row=1, col=1)

    # 均线
    for label, ma_series in _ma_computed.items():
        fig.add_trace(go.Scatter(
            x=dates, y=ma_series, name=label,
            line=dict(color=_MA[label], width=1.2), mode="lines",
            hovertemplate=f"{label}: %{{y:.2f}}<extra></extra>",
            legendgroup="ma",
        ), row=1, col=1)

    # 圆弧底部标注：MA10 在末段窗口内的实际最低点（不再做二次拟合，避免脱离真实均线）
    if show_ma_arc_fit and arc_fit_window > 5 and "MA10" in _ma_computed:
        W = int(arc_fit_window)
        ma10_full = _ma_computed["MA10"].values
        if len(ma10_full) >= W:
            y_win = ma10_full[-W:].astype(float)
            if not np.isnan(y_win).any():
                idx_min_local = int(np.argmin(y_win))
                bot_date = dates.iloc[-W:].iloc[idx_min_local]
                bot_y = float(y_win[idx_min_local])
                fig.add_trace(go.Scatter(
                    x=[bot_date], y=[bot_y],
                    mode="markers+text",
                    marker=dict(symbol="diamond", color="#FF8800", size=11,
                                line=dict(color="#FFFFFF", width=1)),
                    text=["底"], textposition="bottom center",
                    textfont=dict(color="#FF8800", size=10),
                    name="圆弧底",
                    hovertemplate=f"圆弧底 MA10: {bot_y:.2f}<extra></extra>",
                    legendgroup="ma_arc",
                    showlegend=True,
                ), row=1, col=1)

    # Bollinger Bands
    if show_bollinger:
        # 填充带（先添加，在底层）
        fig.add_trace(go.Scatter(
            x=dates, y=bb_upper, mode="lines",
            line=dict(width=0), showlegend=False,
            hoverinfo="skip",
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=dates, y=bb_lower, mode="lines",
            line=dict(width=0), showlegend=False,
            fill="tonexty", fillcolor=_BB_FILL,
            hoverinfo="skip",
        ), row=1, col=1)

        # 轨道线（细虚线）
        for bb_y, bb_name in [(bb_upper, "布林上轨"), (bb_middle, "布林中轨"), (bb_lower, "布林下轨")]:
            is_mid = "中" in bb_name
            fig.add_trace(go.Scatter(
                x=dates, y=bb_y, name=bb_name,
                line=dict(color=_BB_LINE, width=1.0,
                          dash="dash" if not is_mid else "dot"),
                hovertemplate=f"{bb_name}: %{{y:.2f}}<extra></extra>",
                legendgroup="bollinger",
                showlegend=True,
            ), row=1, col=1)

    # 支撑/压力位
    if show_sr_levels:
        for s_val in sr_supports:
            fig.add_hline(
                y=s_val, line=dict(color=_SR_SUPPORT, dash="dash", width=1),
                row=1, col=1, opacity=0.55,
                annotation_text=f" 支撑 {s_val:.2f}",
                annotation_position="right",
                annotation_font=dict(size=8, color=_SR_SUPPORT),
            )
        for r_val in sr_resistances:
            fig.add_hline(
                y=r_val, line=dict(color=_SR_RESISTANCE, dash="dash", width=1),
                row=1, col=1, opacity=0.55,
                annotation_text=f" 压力 {r_val:.2f}",
                annotation_position="right",
                annotation_font=dict(size=8, color=_SR_RESISTANCE),
            )

    # 买卖点标注（MACD 金叉/死叉 + 顶/底背离）
    if show_buy_sell:
        signals = detect_buy_sell_signals(close, dif, dea, lookback_days=int(buy_sell_lookback))
        if signals:
            price_span = float(np.nanmax(high.values) - np.nanmin(low.values)) or 1.0
            offset = max(price_span * 0.012, 0.01)
            buy_x, buy_y, buy_text, buy_hover = [], [], [], []
            sell_x, sell_y, sell_text, sell_hover = [], [], [], []
            for idx, info in signals.items():
                if idx < 0 or idx >= len(dates):
                    continue
                labels = info["labels"]
                tag = "+".join(labels)
                if info["side"] == "buy":
                    buy_x.append(dates.iloc[idx])
                    buy_y.append(low.iloc[idx] - offset)
                    buy_text.append("买")
                    buy_hover.append(f"买点 {dates.iloc[idx]}<br>价: {close.iloc[idx]:.2f}<br>{tag}")
                else:
                    sell_x.append(dates.iloc[idx])
                    sell_y.append(high.iloc[idx] + offset)
                    sell_text.append("卖")
                    sell_hover.append(f"卖点 {dates.iloc[idx]}<br>价: {close.iloc[idx]:.2f}<br>{tag}")
            if buy_x:
                fig.add_trace(go.Scatter(
                    x=buy_x, y=buy_y,
                    mode="markers+text",
                    marker=dict(symbol="triangle-up", size=13, color=_UP,
                                line=dict(color="#FFFFFF", width=1)),
                    text=buy_text, textposition="bottom center",
                    textfont=dict(size=9, color=_UP),
                    name="买点",
                    hovertext=buy_hover,
                    hovertemplate="%{hovertext}<extra></extra>",
                    legendgroup="signals",
                ), row=1, col=1)
            if sell_x:
                fig.add_trace(go.Scatter(
                    x=sell_x, y=sell_y,
                    mode="markers+text",
                    marker=dict(symbol="triangle-down", size=13, color=_DOWN,
                                line=dict(color="#FFFFFF", width=1)),
                    text=sell_text, textposition="top center",
                    textfont=dict(size=9, color=_DOWN),
                    name="卖点",
                    hovertext=sell_hover,
                    hovertemplate="%{hovertext}<extra></extra>",
                    legendgroup="signals",
                ), row=1, col=1)

    # ═════════════════════════════════════════════════════════════
    #  Row 2 — 成交量（+ OBV overlay）
    # ═════════════════════════════════════════════════════════════

    vol_colors = [_UP if c >= o else _DOWN
                  for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(
        x=dates, y=volume,
        name="成交量", marker_color=vol_colors, showlegend=True,
        hovertemplate="成交量: %{y:,.0f}<extra></extra>",
    ), row=2, col=1)

    if show_obv:
        fig.add_trace(go.Scatter(
            x=dates, y=obv_series, name="OBV",
            line=dict(color=_OBV_LINE, width=1.3),
            hovertemplate="OBV: %{y:,.0f}<extra></extra>",
        ), row=2, col=1, secondary_y=True)

    # ═════════════════════════════════════════════════════════════
    #  Row 3+ — MACD / RSI / KDJ
    # ═════════════════════════════════════════════════════════════

    if show_macd:
        r = row_of["macd"]
        fig.add_trace(go.Scatter(
            x=dates, y=dif, name="DIF",
            line=dict(color="#FFB800", width=1),
            hovertemplate="DIF: %{y:.3f}<extra></extra>",
        ), row=r, col=1)
        fig.add_trace(go.Scatter(
            x=dates, y=dea, name="DEA",
            line=dict(color="#9900CC", width=1),
            hovertemplate="DEA: %{y:.3f}<extra></extra>",
        ), row=r, col=1)
        hclr = [_UP if v >= 0 else _DOWN for v in hist.fillna(0)]
        fig.add_trace(go.Bar(
            x=dates, y=hist, name="MACD柱",
            marker_color=hclr, showlegend=False,
            hovertemplate="MACD柱: %{y:.3f}<extra></extra>",
        ), row=r, col=1)

    if show_rsi:
        r = row_of["rsi"]
        fig.add_trace(go.Scatter(
            x=dates, y=rsi_series, name="RSI(14)",
            line=dict(color=_RSI_LINE, width=1.3),
            hovertemplate="RSI: %{y:.1f}<extra></extra>",
        ), row=r, col=1)
        # 超买/超卖参考线
        fig.add_hline(
            y=70, line=dict(color=_RSI_OVERBOUGHT, dash="dash", width=0.8),
            row=r, col=1, opacity=0.5,
            annotation_text="超买 70", annotation_position="right",
            annotation_font=dict(size=8, color=_RSI_OVERBOUGHT),
        )
        fig.add_hline(
            y=30, line=dict(color=_RSI_OVERSOLD, dash="dash", width=0.8),
            row=r, col=1, opacity=0.5,
            annotation_text="超卖 30", annotation_position="right",
            annotation_font=dict(size=8, color=_RSI_OVERSOLD),
        )

    if show_kdj:
        r = row_of["kdj"]
        fig.add_trace(go.Scatter(
            x=dates, y=kdj_k, name="K",
            line=dict(color=_KDJ_K, width=1.2),
            hovertemplate="K: %{y:.2f}<extra></extra>",
        ), row=r, col=1)
        fig.add_trace(go.Scatter(
            x=dates, y=kdj_d, name="D",
            line=dict(color=_KDJ_D, width=1.2),
            hovertemplate="D: %{y:.2f}<extra></extra>",
        ), row=r, col=1)
        fig.add_trace(go.Scatter(
            x=dates, y=kdj_j, name="J",
            line=dict(color=_KDJ_J, width=1.2),
            hovertemplate="J: %{y:.2f}<extra></extra>",
        ), row=r, col=1)
        # KDJ 参考线
        for ref_y in [20, 50, 80]:
            fig.add_hline(
                y=ref_y, line=dict(color="#CCCCCC", dash="dot", width=0.5),
                row=r, col=1, opacity=0.4,
            )

    # ═════════════════════════════════════════════════════════════
    #  Layout — 全图通用设置
    # ═════════════════════════════════════════════════════════════

    fig.update_layout(
        title=dict(text=title, font=dict(size=12)),
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        height=max(520, 180 + n_rows * 140),  # 动态高度：主图更高以贴近同花顺陡峭比例
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=9),
            itemclick="toggle",       # 单击切换显示
            itemdoubleclick="toggleothers",  # 双击仅显示当前
        ),
        margin=dict(l=50, r=15, t=50, b=15),
        hovermode="x unified",
        dragmode="pan",
        newshape=dict(
            line=dict(color="#FF6600", width=2),
            opacity=0.8,
            drawdirection="diagonal",
        ),
        spikedistance=-1,
        hoverdistance=-1,
    )

    # ── Y 轴配置 ─────────────────────────────────────────────────
    # Row 1 (主图)：紧贴价格高低范围（仅 3% 留白），避免 autorange 默认留白压扁K线
    _pmin = float(low.min())
    _pmax = float(high.max())
    if show_bollinger:
        _pmin = min(_pmin, float(bb_lower.min()))
        _pmax = max(_pmax, float(bb_upper.max()))
    _pad = (_pmax - _pmin) * 0.03 or _pmax * 0.01
    fig.update_yaxes(
        showgrid=True, gridcolor=_GRID_COLOR, gridwidth=0.8,
        zeroline=False, range=[_pmin - _pad, _pmax + _pad],
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikecolor="#999999", spikethickness=1, spikedash="dot",
        title_text="价格",
        row=1, col=1,
    )
    # Row 2 (成交量)
    fig.update_yaxes(
        showgrid=True, gridcolor=_GRID_COLOR, gridwidth=0.8,
        autorange=True, title_text="成交量",
        row=2, col=1,
    )
    if show_obv:
        fig.update_yaxes(
            title_text="OBV", row=2, col=1, secondary_y=True,
            showgrid=False,
        )

    # MACD / RSI / KDJ 行
    for i, pname in enumerate(extra_panels):
        r = 3 + i
        cfg: dict = dict(
            showgrid=True, gridcolor=_GRID_COLOR, gridwidth=0.8,
            autorange=True,
        )
        if pname == "rsi":
            cfg["range"] = [0, 100]
            cfg["title_text"] = "RSI"
        elif pname == "kdj":
            cfg["range"] = [0, 100]
            cfg["title_text"] = "KDJ"
        elif pname == "macd":
            cfg["title_text"] = "MACD"
        fig.update_yaxes(cfg, row=r, col=1)

    # ── X 轴配置 ─────────────────────────────────────────────────
    xaxis_extra = {}
    if period == "D":
        # 删除节假日/停牌等无蜡烛日期，保证K线连续：
        # 用完整日历范围减去实际交易日，得到需折断的空档（含周末），一次覆盖。
        _d = pd.to_datetime(dates).dt.normalize()
        present = set(_d)
        full = pd.date_range(_d.min(), _d.max(), freq="D")
        missing = [d.strftime("%Y-%m-%d") for d in full if d not in present]
        if missing:
            xaxis_extra["rangebreaks"] = [{"values": missing}]

    for i in range(1, n_rows + 1):
        fig.update_xaxes(
            showgrid=True, gridcolor=_GRID_COLOR, gridwidth=0.8,
            showline=True, linecolor="#CCCCCC",
            showspikes=True, spikemode="across", spikesnap="cursor",
            spikecolor="#999999", spikethickness=1, spikedash="solid",
            **xaxis_extra,
            row=i, col=1,
        )

    # ═════════════════════════════════════════════════════════════
    #  均线排列标记（多头 + 空头）
    # ═════════════════════════════════════════════════════════════

    if show_ma_arrangement and len(df) >= 62:
        # 多头排列绿色标记
        bull_ranges = _ma_bullish_ranges(
            dates, _ma_all[5], _ma_all[10], _ma_all[20], _ma_all[60])
        for x0, x1 in bull_ranges:
            fig.add_vrect(
                x0=x0, x1=x1,
                fillcolor="rgba(50,200,80,0.07)",
                line_width=0,
                layer="below",
            )

        # 空头排列红色标记
        bear_ranges = _ma_bearish_ranges(
            dates, _ma_all[5], _ma_all[10], _ma_all[20], _ma_all[60])
        for x0, x1 in bear_ranges:
            fig.add_vrect(
                x0=x0, x1=x1,
                fillcolor="rgba(255,50,50,0.07)",
                line_width=0,
                layer="below",
            )

        # 当前排列状态标注
        last_valid = _ma_all[60].iloc[-1]
        if pd.notna(last_valid):
            m5  = float(_ma_all[5].iloc[-1])
            m10 = float(_ma_all[10].iloc[-1])
            m20 = float(_ma_all[20].iloc[-1])
            m60 = float(_ma_all[60].iloc[-1])

            is_bull = m5 > m10 > m20 > m60
            is_bear = m5 < m10 < m20 < m60

            if is_bull:
                ann_text, ann_color = "多头排列 ▲", "#00AA44"
            elif is_bear:
                ann_text, ann_color = "空头排列 ▼", "#DD3333"
            else:
                ann_text, ann_color = "均线交织 —", "#999999"

            fig.add_annotation(
                text=ann_text,
                xref="paper", yref="paper",
                x=0.01, y=0.985,
                xanchor="left", yanchor="top",
                showarrow=False,
                font=dict(color=ann_color, size=10, family="Arial"),
                bgcolor="rgba(255,255,255,0.85)",
                bordercolor=ann_color,
                borderwidth=1,
                borderpad=3,
            )

    # ── 用户画线（持久化） ─────────────────────────────────────────
    if isinstance(user_shapes, list):
        for s in user_shapes:
            s_copy = dict(s)
            s_copy.setdefault("name", "user_drawn")
            fig.add_shape(s_copy)

    # ── 默认缩放范围 ─────────────────────────────────────────────
    if initial_xrange:
        for i in range(1, n_rows + 1):
            fig.update_xaxes(range=initial_xrange, row=i, col=1)

    return fig
