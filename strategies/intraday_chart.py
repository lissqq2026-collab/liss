"""strategies/intraday_chart.py — A股分时图（同花顺风格）

主图：现价折线 + 均价线 + 昨收基线 + 红/绿半透明填充
副图：成交量柱（按涨跌染色）
X 轴：仅显示 9:30–11:30、13:00–15:00 两段（rangebreaks 隔断午休）
Y 轴：左侧价格、右侧涨跌幅 (基于昨收)
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

_UP   = "#FF3333"
_DOWN = "#33AA33"
_PRICE_LINE = "#FFB800"
_AVG_LINE   = "#1E90FF"
_BASE_LINE  = "#AAAAAA"
_GRID_COLOR = "#F0F0F0"
_FILL_UP    = "rgba(255,51,51,0.12)"
_FILL_DOWN  = "rgba(51,170,51,0.12)"
_VOL_UP     = "rgba(255,51,51,0.55)"
_VOL_DOWN   = "rgba(51,170,51,0.55)"


def _calc_vwap(df: pd.DataFrame) -> pd.Series:
    """累计均价线 = 累计成交额 / 累计成交量。
    新浪 1 分钟无 amount 字段时用 close*volume 近似。
    """
    vol = pd.to_numeric(df["volume"], errors="coerce")
    if "amount" in df.columns and df["amount"].notna().any():
        amt = pd.to_numeric(df["amount"], errors="coerce")
    else:
        close = pd.to_numeric(df["close"], errors="coerce")
        amt = close * vol
    cum_amt = amt.cumsum()
    cum_vol = vol.cumsum().replace(0, pd.NA)
    return (cum_amt / cum_vol).astype(float)


def build_intraday_chart(
    df: pd.DataFrame,
    title: str,
    prev_close: Optional[float] = None,
    height: int = 340,
) -> go.Figure:
    """绘制单日分时图（同花顺风格）。

    df 列：datetime, open, high, low, close, volume[, amount]
    prev_close：昨收价。若为 None，用首根 K 线 open 兜底。
    """
    if df is None or df.empty:
        fig = go.Figure()
        fig.update_layout(title=f"{title} · 暂无分时数据", height=height,
                          plot_bgcolor="white", paper_bgcolor="white")
        return fig

    df = df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"])
    base = float(prev_close) if prev_close else float(df["open"].iloc[0])
    df["vwap"] = _calc_vwap(df)
    df["pct"] = (df["close"] - base) / base * 100.0

    # 拆分高于 / 低于昨收，用于双色填充
    df["close_above"] = df["close"].where(df["close"] >= base)
    df["close_below"] = df["close"].where(df["close"] < base)

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.03, row_heights=[0.73, 0.27],
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]],
    )

    # ── 填充基准线（隐藏） ──
    base_trace = go.Scatter(
        x=df["datetime"], y=[base] * len(df),
        mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip",
    )
    fig.add_trace(base_trace, row=1, col=1)

    # 高于昨收填充（红）
    fig.add_trace(go.Scatter(
        x=df["datetime"], y=df["close_above"],
        mode="lines", line=dict(width=0), showlegend=False,
        fill="tonexty", fillcolor=_FILL_UP, connectgaps=False, hoverinfo="skip",
    ), row=1, col=1)

    # 第二条基准线（为低于昨收填充做锚点）
    base_trace2 = go.Scatter(
        x=df["datetime"], y=[base] * len(df),
        mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip",
    )
    fig.add_trace(base_trace2, row=1, col=1)

    # 低于昨收填充（绿）
    fig.add_trace(go.Scatter(
        x=df["datetime"], y=df["close_below"],
        mode="lines", line=dict(width=0), showlegend=False,
        fill="tonexty", fillcolor=_FILL_DOWN, connectgaps=False, hoverinfo="skip",
    ), row=1, col=1)

    # ── 昨收可见虚线 ──
    fig.add_hline(
        y=base, line=dict(color=_BASE_LINE, width=1.2, dash="dash"),
        row=1, col=1,
        annotation_text=f"昨收 {base:.2f}",
        annotation_position="top left",
        annotation_font=dict(size=9, color=_BASE_LINE),
    )

    # ── 均价线 ──
    fig.add_trace(go.Scatter(
        x=df["datetime"], y=df["vwap"], mode="lines",
        name="均价", line=dict(color=_AVG_LINE, width=1.2, dash="dot"),
        hovertemplate="%{x|%H:%M}<br>均价: %{y:.2f}<extra></extra>",
    ), row=1, col=1)

    # ── 现价线（最上层，含涨跌幅 + 均价联动 hover） ──
    df["hover_text"] = (
        df["datetime"].dt.strftime("%H:%M") + "<br>"
        + "价: " + df["close"].round(2).astype(str)
        + "  涨幅: " + df["pct"].round(2).astype(str) + "%<br>"
        + "均价: " + df["vwap"].round(2).astype(str)
    )
    fig.add_trace(go.Scatter(
        x=df["datetime"], y=df["close"], mode="lines",
        name="现价", line=dict(color=_PRICE_LINE, width=2),
        text=df["hover_text"], hoverinfo="text",
        hovertemplate="%{text}<extra></extra>",
    ), row=1, col=1)

    # ── 副图：量柱（联动 hover 含成交额估算） ──
    vol_colors = [
        _VOL_UP if c >= o else _VOL_DOWN
        for c, o in zip(df["close"], df["open"])
    ]
    df["vol_hover"] = (
        "量: " + (df["volume"] / 100).round(0).astype(int).astype(str) + "手"
    )
    fig.add_trace(go.Bar(
        x=df["datetime"], y=df["volume"], name="成交量",
        marker=dict(color=vol_colors), showlegend=False,
        text=df["vol_hover"], hoverinfo="text",
        hovertemplate="%{text}<extra></extra>",
    ), row=2, col=1)

    # ── X 轴：隔断午休 + 30分钟刻度 ──
    rangebreaks = [
        dict(bounds=[11.5, 13], pattern="hour"),
        dict(bounds=[15, 9.5], pattern="hour"),
    ]
    fig.update_xaxes(rangebreaks=rangebreaks, showgrid=True,
                     gridcolor=_GRID_COLOR, tickformat="%H:%M",
                     dtick=1800000, showspikes=True, spikemode="across",
                     spikethickness=1, spikecolor="rgba(0,0,0,0.25)",
                     spikedash="solid", spikesnap="cursor",
                     row=1, col=1)
    fig.update_xaxes(rangebreaks=rangebreaks, showgrid=True,
                     gridcolor=_GRID_COLOR, tickformat="%H:%M",
                     dtick=1800000, showspikes=True, spikemode="across",
                     spikethickness=1, spikecolor="rgba(0,0,0,0.25)",
                     spikedash="solid", spikesnap="cursor",
                     row=2, col=1)

    # ── Y 轴双轴：0 轴居中，上下对称扩展（同花顺风格） ──
    last_close = float(df["close"].iloc[-1])
    last_pct = (last_close - base) / base * 100.0
    dev_high = df["high"].max() - base
    dev_low  = base - df["low"].min()
    max_dev  = max(dev_high, dev_low, base * 0.005) * 1.08
    y_max = base + max_dev
    y_min = base - max_dev
    pct_range = max_dev / base * 100.0

    fig.update_yaxes(
        range=[y_min, y_max], showgrid=True, gridcolor=_GRID_COLOR,
        tickformat=".2f", zeroline=False, row=1, col=1, secondary_y=False,
    )
    # 右侧涨跌幅轴（对称范围，不可见 trace 用于锚定副轴）
    fig.add_trace(go.Scatter(
        x=df["datetime"], y=df["pct"],
        mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip",
    ), row=1, col=1, secondary_y=True)
    fig.update_yaxes(
        range=[-pct_range, pct_range], showgrid=False,
        tickformat=".2f", ticksuffix="%", title=dict(text="涨跌幅"),
        row=1, col=1, secondary_y=True,
    )
    fig.update_yaxes(showgrid=True, gridcolor=_GRID_COLOR, zeroline=False, row=2, col=1)

    # ── 布局 ──
    change_color = _UP if last_pct >= 0 else _DOWN
    fig.update_layout(
        title=dict(
            text=f"{title}  "
                 f"<span style='color:{change_color}'>{last_close:.2f}  {last_pct:+.2f}%</span>",
            font=dict(size=12),
        ),
        height=height,
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=40, r=50, t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.0,
                    xanchor="right", x=1.0, bgcolor="rgba(255,255,255,0.7)"),
        hovermode="x unified",
        hoverdistance=100,
        spikedistance=200,
        bargap=0.0,
    )

    return fig
