"""ui/tokens.py — 设计令牌（全站颜色 / 字号 / 间距 / 圆角 / 阴影统一来源）

所有页面引用 token，不要硬编码值。修改一处即可全站生效。
"""

# ── 颜色 ────────────────────────────────────────────────────────────────────────
# A股惯例：涨红跌绿
COLOR_UP        = "#E63946"   # 涨
COLOR_DOWN      = "#2A9D8F"   # 跌
COLOR_FLAT      = "#6B7280"   # 平

# 品牌主色
COLOR_PRIMARY   = "#1E90FF"
COLOR_ACCENT    = "#FF3333"

# 中性灰阶
COLOR_TEXT_PRIMARY   = "#111827"
COLOR_TEXT_SECONDARY = "#374151"
COLOR_TEXT_MUTED     = "#6B7280"
COLOR_TEXT_DISABLED  = "#9CA3AF"

COLOR_BG          = "#FFFFFF"
COLOR_BG_SUBTLE   = "#F9FAFB"
COLOR_BG_HOVER    = "#F3F4F6"
COLOR_BORDER      = "#E5E7EB"
COLOR_BORDER_STRONG = "#D1D5DB"

# 状态色
COLOR_SUCCESS = "#10B981"
COLOR_WARN    = "#F59E0B"
COLOR_DANGER  = "#EF4444"
COLOR_INFO    = "#3B82F6"


# ── 字号 ────────────────────────────────────────────────────────────────────────

FONT_SIZE_BASE = "14px"
FONT_SIZE_XS   = "0.72rem"
FONT_SIZE_SM   = "0.8rem"
FONT_SIZE_MD   = "0.9rem"
FONT_SIZE_LG   = "1rem"
FONT_SIZE_XL   = "1.1rem"
FONT_SIZE_H3   = "1rem"
FONT_SIZE_H2   = "1.2rem"
FONT_SIZE_H1   = "1.4rem"


# ── 间距 ────────────────────────────────────────────────────────────────────────

SPACE_0   = "0"
SPACE_1   = "0.2rem"
SPACE_2   = "0.3rem"
SPACE_3   = "0.5rem"
SPACE_4   = "0.75rem"
SPACE_5   = "1rem"
SPACE_6   = "1.5rem"
SPACE_8   = "2rem"


# ── 圆角 ────────────────────────────────────────────────────────────────────────

RADIUS_SM = "4px"
RADIUS_MD = "6px"
RADIUS_LG = "8px"
RADIUS_XL = "12px"


# ── 阴影 ────────────────────────────────────────────────────────────────────────

SHADOW_SM = "0 1px 2px rgba(0,0,0,0.05)"
SHADOW_MD = "0 2px 4px rgba(0,0,0,0.06)"
SHADOW_LG = "0 4px 12px rgba(0,0,0,0.08)"
