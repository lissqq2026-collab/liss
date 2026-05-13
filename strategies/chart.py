"""strategies/chart.py — Plotly K线图渲染（A股配色）"""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

_UP   = "#FF3333"  # 涨（红）
_DOWN = "#33AA33"  # 跌（绿）
_MA   = {"MA5": "#FFB800", "MA10": "#FF6600", "MA20": "#9900CC", "MA60": "#0088FF"}


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


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
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


def build_kline_chart(df: pd.DataFrame, title: str = "", show_macd: bool = True,
                      period: str = "D", show_ma_periods: list = None,
                      show_ma_arrangement: bool = True) -> go.Figure:
    """
    绘制K线图（含均线、成交量、可选MACD面板）。
    df 必须含列：date, open, high, low, close, volume
    period: "D"=日K, "W"=周K, "M"=月K — 日K才排除周末空白
    show_ma_periods: 要显示的均线周期列表，如 [5, 10, 20]；None=全部显示
    """
    close = df["close"]
    _ma_show = set(show_ma_periods) if show_ma_periods is not None else {5, 10, 20, 60}
    _ma5_s  = close.rolling(5).mean()
    _ma10_s = close.rolling(10).mean()
    _ma20_s = close.rolling(20).mean()
    _ma60_s = close.rolling(60).mean()
    _ma_all = {5: _ma5_s, 10: _ma10_s, 20: _ma20_s, 60: _ma60_s}
    _ma_lbl = {5: "MA5", 10: "MA10", 20: "MA20", 60: "MA60"}
    _ma_computed = {_ma_lbl[n]: _ma_all[n] for n in [5, 10, 20, 60] if n in _ma_show}

    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    dif   = ema12 - ema26
    dea   = _ema(dif, 9)
    hist  = (dif - dea) * 2

    rows    = 3 if show_macd else 2
    heights = [0.60, 0.20, 0.20] if show_macd else [0.70, 0.30]

    fig = make_subplots(
        rows=rows, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=heights,
    )

    # ── 主图：K线 ─────────────────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=df["date"],
        open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="K线",
        increasing=dict(line=dict(color=_UP,   width=1), fillcolor=_UP),
        decreasing=dict(line=dict(color=_DOWN, width=1), fillcolor=_DOWN),
    ), row=1, col=1)

    for label, ma_series in _ma_computed.items():
        fig.add_trace(go.Scatter(
            x=df["date"], y=ma_series, name=label,
            line=dict(color=_MA[label], width=1.2), mode="lines",
        ), row=1, col=1)

    # ── 成交量 ────────────────────────────────────────────────────────────────
    vol_colors = [_UP if c >= o else _DOWN
                  for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(
        x=df["date"], y=df["volume"],
        name="成交量", marker_color=vol_colors, showlegend=False,
    ), row=2, col=1)

    # ── MACD ─────────────────────────────────────────────────────────────────
    if show_macd:
        fig.add_trace(go.Scatter(x=df["date"], y=dif, name="DIF",
                                  line=dict(color="#FFB800", width=1)), row=3, col=1)
        fig.add_trace(go.Scatter(x=df["date"], y=dea, name="DEA",
                                  line=dict(color="#9900CC", width=1)), row=3, col=1)
        hclr = [_UP if v >= 0 else _DOWN for v in hist.fillna(0)]
        fig.add_trace(go.Bar(x=df["date"], y=hist, name="MACD柱",
                              marker_color=hclr, showlegend=False), row=3, col=1)

    fig.update_layout(
        title=dict(text=title, font=dict(size=14)),
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        height=680,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=60, r=20, t=60, b=20),
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
    # 主图 y 轴：加深网格、关闭零线
    fig.update_yaxes(
        showgrid=True, gridcolor="#E0E0E0", gridwidth=1,
        zeroline=False, autorange=True,
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikecolor="#999999", spikethickness=1, spikedash="dot",
        row=1, col=1,
    )
    for i in range(2, rows + 1):
        fig.update_yaxes(
            showgrid=True, gridcolor="#E0E0E0", gridwidth=1,
            autorange=True,
            row=i, col=1,
        )
    xaxis_extra = {}
    if period == "D":
        xaxis_extra["rangebreaks"] = [{"bounds": ["sat", "mon"]}]
    for i in range(1, rows + 1):
        fig.update_xaxes(
            showgrid=True, gridcolor="#E0E0E0", gridwidth=1,
            showline=True, linecolor="#CCCCCC",
            showspikes=True, spikemode="across", spikesnap="cursor",
            spikecolor="#999999", spikethickness=1, spikedash="solid",
            **xaxis_extra,
            row=i, col=1,
        )

    # ── 多头排列标志 ──────────────────────────────────────────────────────────────
    if show_ma_arrangement and len(df) >= 62:
        bull_ranges = _ma_bullish_ranges(df["date"], _ma5_s, _ma10_s, _ma20_s, _ma60_s)
        for x0, x1 in bull_ranges:
            fig.add_vrect(
                x0=x0, x1=x1,
                fillcolor="rgba(50,200,80,0.07)",
                line_width=0,
                layer="below",
            )
        last_valid = _ma60_s.iloc[-1]
        if pd.notna(last_valid):
            cur_bull = bool(
                _ma5_s.iloc[-1] > _ma10_s.iloc[-1] > _ma20_s.iloc[-1] > _ma60_s.iloc[-1]
            )
            ann_text  = "多头排列 ▲" if cur_bull else "非多头排列 ▼"
            ann_color = "#00AA44" if cur_bull else "#999999"
            fig.add_annotation(
                text=ann_text,
                xref="paper", yref="paper",
                x=0.01, y=0.985,
                xanchor="left", yanchor="top",
                showarrow=False,
                font=dict(color=ann_color, size=11, family="Arial"),
                bgcolor="rgba(255,255,255,0.85)",
                bordercolor=ann_color,
                borderwidth=1,
                borderpad=3,
            )

    return fig
