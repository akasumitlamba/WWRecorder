"""Shared opaque notification surfaces; statuses never depend on desktop color."""
SURFACE='#151923'
BORDER='#424B5D'
TEXT='#F0F2F5'
MUTED='#B9C1CE'
ACCENT='#FF7382'
SUCCESS='#53D3A0'

def toast_style(accent=SUCCESS):
    return f"QLabel {{background:{SURFACE};color:{TEXT};border:1px solid {BORDER};border-left:3px solid {accent};border-radius:8px;font:600 12px 'Segoe UI';padding:9px 16px;}}"
