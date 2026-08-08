"""Centralized brand theme derived from the Aarogyasampada 360° logo.

Primary source: deep forest → mid → lime green leaf gradient.
Partner navy/red are reserved for partner logo context only — not UI chrome.
"""

from __future__ import annotations

# Hex tokens (shared with frontend/css/theme.css)
PRIMARY = "#0C7848"
PRIMARY_DARK = "#085C38"
PRIMARY_SOFT = "#3CA854"
ACCENT = "#90C03C"
ACCENT_SOFT = "#D8E484"
BACKGROUND = "#F3F8F4"
SURFACE = "#FFFFFF"
TEXT_PRIMARY = "#123528"
TEXT_SECONDARY = "#4A6356"
BORDER = "#C5D9CB"
SUCCESS = "#0C7848"
ERROR = "#B42318"

# RGB tuples for Pillow pass rendering
PRIMARY_RGB = (12, 120, 72)
PRIMARY_DARK_RGB = (8, 92, 56)
PRIMARY_SOFT_RGB = (60, 168, 84)
ACCENT_RGB = (144, 192, 60)
ACCENT_SOFT_RGB = (216, 228, 132)
BACKGROUND_RGB = (243, 248, 244)
SURFACE_RGB = (255, 255, 255)
TEXT_PRIMARY_RGB = (18, 53, 40)
TEXT_SECONDARY_RGB = (74, 99, 86)
BORDER_RGB = (197, 217, 203)
WHITE_RGB = (255, 255, 255)

# Layout tokens
RADIUS_LG = 24
RADIUS_MD = 16
RADIUS_SM = 12
