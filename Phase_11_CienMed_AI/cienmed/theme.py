"""Cien HealthFlow visual theme — matches the Power BI dashboard / cover art.

Deep navy background, electric-blue accents, rounded dark cards with thin blue borders,
green = good / up, red = bad / down.
"""
import plotly.graph_objects as go
import plotly.io as pio

C = {
    "bg": "#07111F",          # page background (deep navy)
    "bg2": "#0B1A2E",         # sidebar / gradients
    "card": "#0F2038",        # card surface
    "border": "#1D3B63",      # thin card border
    "blue": "#2F8CFF",        # primary electric blue
    "cyan": "#38BDF8",        # glow / highlights
    "text": "#E6EEF8",
    "muted": "#8DA2BF",
    "green": "#34D399",
    "red": "#F87171",
    "amber": "#F5B83D",
}
SERIES = ["#2F8CFF", "#38BDF8", "#34D399", "#1E5BB8", "#F5B83D", "#A78BFA", "#F87171"]

# Heart + pulse line logo (same idea as the Cien HealthFlow mark)
LOGO_SVG = """<svg viewBox="0 0 64 56" width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#38BDF8"/><stop offset="1" stop-color="#2F8CFF"/></linearGradient></defs>
<path d="M32 52 C18 41 4 31 4 17 C4 8 11 2 19 2 C25 2 29 5 32 9 C35 5 39 2 45 2 C53 2 60 8 60 17
C60 31 46 41 32 52Z" fill="none" stroke="url(#g)" stroke-width="3.5" stroke-linejoin="round"/>
<polyline points="10,27 22,27 26,18 31,36 36,22 40,27 54,27" fill="none" stroke="url(#g)"
stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/></svg>"""


def register_plotly_template() -> None:
    """Dark, transparent Plotly template so charts sit inside the navy cards."""
    pio.templates["cienflow"] = go.layout.Template(
        layout=dict(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color=C["text"], family="Inter, Segoe UI, sans-serif", size=12),
            title=dict(font=dict(size=15, color=C["text"]), x=0.01),
            colorway=SERIES,
            xaxis=dict(gridcolor="rgba(141,162,191,0.12)", linecolor=C["border"], zeroline=False),
            yaxis=dict(gridcolor="rgba(141,162,191,0.12)", linecolor=C["border"], zeroline=False),
            legend=dict(bgcolor="rgba(0,0,0,0)"),
            hoverlabel=dict(bgcolor=C["card"], bordercolor=C["blue"], font=dict(color=C["text"])),
            margin=dict(l=10, r=10, t=45, b=10),
        )
    )
    pio.templates.default = "cienflow"


CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, .stTextInput, button {{ font-family: 'Inter', 'Segoe UI', sans-serif; }}

/* page background: navy with a soft blue glow, like the cover art */
.stApp {{
  background:
    radial-gradient(1100px 500px at 85% -10%, rgba(47,140,255,0.18), transparent 60%),
    radial-gradient(800px 400px at -10% 110%, rgba(56,189,248,0.10), transparent 60%),
    {C['bg']};
  color: {C['text']};
}}
header[data-testid="stHeader"] {{ background: transparent; }}
section[data-testid="stSidebar"] {{ background: {C['bg2']}; border-right: 1px solid {C['border']}; }}
h1, h2, h3, h4 {{ color: {C['text']}; letter-spacing: -0.01em; }}
p, li, label, .stCaption {{ color: {C['text']}; }}
[data-testid="stCaptionContainer"] {{ color: {C['muted']}; }}

/* brand header */
.cf-brand {{ display:flex; align-items:center; gap:14px; margin: 4px 0 6px; }}
.cf-brand .t1 {{ font-size: 1.9rem; font-weight: 700; color: {C['text']}; line-height: 1.05; }}
.cf-brand .t2 {{ font-size: 1.05rem; color: {C['cyan']}; font-weight: 500; }}
.cf-sub {{ color: {C['muted']}; margin: 0 0 18px; }}
.cf-divider {{ height:1px; background: linear-gradient(90deg, {C['blue']}, transparent); margin: 6px 0 18px; }}

/* cards */
.cf-card {{
  background: linear-gradient(180deg, rgba(15,32,56,0.95), rgba(11,26,46,0.95));
  border: 1px solid {C['border']}; border-radius: 14px; padding: 20px 22px;
  box-shadow: 0 0 0 1px rgba(47,140,255,0.04), 0 10px 30px rgba(0,0,0,0.35);
  height: 100%;
}}
.cf-card h3 {{ margin: 6px 0 6px; font-size: 1.2rem; }}
.cf-card p {{ color: {C['muted']}; margin: 0; font-size: .95rem; }}
.cf-card .icon {{ font-size: 1.6rem; }}
.cf-card:hover {{ border-color: {C['blue']}; box-shadow: 0 0 22px rgba(47,140,255,0.25); }}

.cf-badge {{ display:inline-block; padding: 3px 10px; border-radius: 999px; font-size: .78rem; font-weight: 600;
  background: rgba(47,140,255,0.15); color: {C['cyan']}; border: 1px solid rgba(56,189,248,0.35); }}

/* metric tiles */
[data-testid="stMetric"] {{
  background: {C['card']}; border: 1px solid {C['border']}; border-radius: 12px; padding: 14px 16px;
}}
[data-testid="stMetricLabel"] p {{ color: {C['muted']} !important; font-weight: 500; }}
[data-testid="stMetricValue"] {{ color: {C['text']}; font-weight: 700; font-size: 1.55rem; }}
[data-testid="stMetricValue"] > div {{ overflow: visible; white-space: nowrap; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ background: rgba(15,32,56,0.6); border-color: {C['border']} !important; border-radius: 14px; }}

/* buttons */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
  background: {C['card']}; color: {C['text']}; border: 1px solid {C['border']}; border-radius: 10px;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{ border-color: {C['blue']}; color: {C['cyan']}; }}
.stButton > button[kind="primary"], .stFormSubmitButton > button {{
  background: linear-gradient(90deg, {C['blue']}, #1E6FE0); border: none; color: #fff; font-weight: 600;
}}

/* inputs */
.stTextInput input, .stNumberInput input, .stDateInput input, div[data-baseweb="select"] > div {{
  background: {C['card']} !important; color: {C['text']} !important; border-color: {C['border']} !important;
}}
[data-testid="stForm"] {{ background: {C['card']}; border: 1px solid {C['border']}; border-radius: 14px; }}

/* chat */
[data-testid="stChatMessage"] {{ background: rgba(15,32,56,0.65); border: 1px solid {C['border']}; border-radius: 14px; }}
[data-testid="stChatInput"] textarea {{ background: {C['card']}; color: {C['text']}; }}
[data-testid="stBottomBlockContainer"] {{ background: {C['bg']}; }}

/* tabs */
.stTabs [data-baseweb="tab-list"] {{ gap: 6px; border-bottom: 1px solid {C['border']}; }}
.stTabs [data-baseweb="tab"] {{ color: {C['muted']}; }}
.stTabs [aria-selected="true"] {{ color: {C['cyan']} !important; }}
.stTabs [data-baseweb="tab-highlight"] {{ background: {C['blue']}; }}

/* expanders, tables, alerts */
[data-testid="stExpander"] {{ background: rgba(15,32,56,0.6); border: 1px solid {C['border']}; border-radius: 12px; }}
[data-testid="stDataFrame"] {{ border: 1px solid {C['border']}; border-radius: 10px; }}
code {{ color: {C['cyan']}; }}
</style>
"""