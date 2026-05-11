"""strategies/chart.py — Plotly K线图渲染（A股配色）"""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

_UP   = "#FF3333"  # 涨（红）
_DOWN = "#33AA33"  # 跌（绿）
_MA   = {"MA5": "#FFB800", "MA10": "#FF6600", "MA20": "#9900CC", "MA60": "#0088FF"}


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
                      period: str = "D") -> go.Figure:
    """
    绘制K线图（含均线、成交量、可选MACD面板）。
    df 必须含列：date, open, high, low, close, volume
    period: "D"=日K, "W"=周K, "M"=月K — 日K才排除周末空白
    """
    close = df["close"]
    ma5  = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()

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

    for (ma_series, label) in [(ma5, "MA5"), (ma10, "MA10"), (ma20, "MA20"), (ma60, "MA60")]:
        fig.add_trace(go.Scatter(
            x=df["date"], y=ma_series, name=label,
            line=dict(color=_MA[label], width=1), mode="lines",
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
        dragmode="zoom",
    )
    # 主图 y 轴：加深网格、关闭零线
    fig.update_yaxes(
        showgrid=True, gridcolor="#E0E0E0", gridwidth=1,
        zeroline=False, autorange=True,
        row=1, col=1,
    )
    # 子图 y 轴：加深网格、自动伸缩
    for i in range(2, rows + 1):
        fig.update_yaxes(
            showgrid=True, gridcolor="#E0E0E0", gridwidth=1,
            autorange=True,
            row=i, col=1,
        )
    # 所有 x 轴：加深网格、显示轴线；日K才排除周末空白
    xaxis_extra = {}
    if period == "D":
        xaxis_extra["rangebreaks"] = [{"bounds": ["sat", "mon"]}]
    for i in range(1, rows + 1):
        fig.update_xaxes(
            showgrid=True, gridcolor="#E0E0E0", gridwidth=1,
            showline=True, linecolor="#CCCCCC",
            **xaxis_extra,
            row=i, col=1,
        )

    return fig
