"""Biond Plotly theme: palette, template registration, modebar config."""

from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio

TEAL = "#2E86A0"
LIME = "#B5CC18"  # fills only -- fails contrast as text on white, never used for text
SLATE = "#6B7C85"
INK = "#333333"
PAPER = "#F7F9FA"
CARD = "#FFFFFF"
AMBER = "#E8A33D"
GRIDLINE = "#E8EDEF"

PALETTE = [TEAL, LIME, SLATE, AMBER, "#7FB3C4", "#8FA332"]

# Okabe-Ito: designed to stay distinguishable under the common forms of color
# blindness (protanopia/deuteranopia/tritanopia).
_COLORBLIND_SAFE = [
    "#E69F00", "#56B4E9", "#009E73", "#F0E442", "#054971", "#D52700",
]

PALETTES: dict[str, list[str]] = {
    "Default": PALETTE,
    "Colorblind-safe": _COLORBLIND_SAFE,
}

LOGO_PATH = Path(__file__).resolve().parent / "biond_logo.png"

PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": [
        "zoom", "pan", "select", "lasso2d", "zoomIn", "zoomOut",
        "autoScale", "hoverClosestCartesian", "hoverCompareCartesian",
        "toggleSpikelines",
    ],
    # leaves toImage + resetViews (resetScale2d / resetViews) on the modebar
}

_AXIS = dict(
    showgrid=False,
    zeroline=False,
    linecolor=SLATE,
    tickfont=dict(color=SLATE),
    title=dict(font=dict(color=SLATE)),
)
_YAXIS = {**_AXIS, "showgrid": True, "gridcolor": GRIDLINE, "linecolor": "rgba(0,0,0,0)"}


def _build_template(palette_name: str) -> go.layout.Template:
    template = go.layout.Template()
    template.layout = go.Layout(
        font=dict(family="sans-serif", color=INK, size=13),
        paper_bgcolor=PAPER,
        plot_bgcolor=CARD,
        colorway=PALETTES.get(palette_name, PALETTE),
        xaxis=_AXIS,
        yaxis=_YAXIS,
        margin=dict(l=40, r=20, t=40, b=40),
        hoverlabel=dict(bgcolor=INK, font=dict(color="white", size=13)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    template.data.bar = [go.Bar(marker=dict(cornerradius=4))]
    template.data.scatter = [go.Scatter(line=dict(shape="spline"))]
    template.data.pie = [go.Pie(hole=0.55, marker=dict(line=dict(color=CARD, width=2)))]
    return template


def register(palette_name: str = "Default") -> None:
    """Register the "biond" template and make it the default. Call once at app start
    (or again after the user picks a different `palette_name`).
    """
    pio.templates["biond"] = _build_template(palette_name)
    pio.templates.default = "biond"


def primary_color() -> str:
    """The active palette's lead color, for single-hue scales (e.g. the activity
    heatmap) that should track the user's palette choice rather than a fixed color.
    """
    if "biond" not in pio.templates:
        return TEAL
    return pio.templates["biond"].layout.colorway[0]
