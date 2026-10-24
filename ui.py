"""
Sistema di design in stile Apple (modalità scura), condiviso da tutte le pagine.
Colori, tipografia e componenti seguono le Human Interface Guidelines di iOS:
sfondo nero, gruppi su grigio #1c1c1e, testo secondario attenuato, accento blu.
"""
import html as _html

import pandas as pd
import streamlit as st

# ── Colori di sistema iOS (modalità scura) ───────────────────────────────────
BLUE, GREEN, RED, ORANGE, YELLOW = "#0a84ff", "#30d158", "#ff453a", "#ff9f0a", "#ffd60a"
LABEL, LABEL2, LABEL3 = "#ffffff", "rgba(235,235,245,0.6)", "rgba(235,235,245,0.3)"
BG, GROUP, GROUP2, SEPARATOR = "#000000", "#1c1c1e", "#2c2c2e", "rgba(84,84,88,0.6)"

CSS = f"""
<style>
:root {{ color-scheme: dark; }}
html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"], .main {{
  background: {BG} !important; color: {LABEL};
}}
* {{ font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "Inter",
     "Helvetica Neue", Arial, sans-serif; -webkit-font-smoothing: antialiased; }}
[data-testid="stHeader"], [data-testid="stSidebar"], [data-testid="stToolbar"],
footer, #MainMenu, .stDeployButton {{ display: none !important; }}
.block-container {{ padding: 20px 16px 80px !important; max-width: 860px; margin: auto; }}
p, li, label, span {{ color: inherit; }}

/* Tipografia */
.ios-large-title {{ font-size: 34px; font-weight: 700; letter-spacing: 0.37px; line-height: 41px; margin: 8px 0 2px; }}
.ios-subtitle {{ font-size: 17px; color: {LABEL2}; line-height: 22px; margin-bottom: 18px; }}
.ios-section {{ font-size: 22px; font-weight: 700; letter-spacing: 0.35px; margin: 28px 0 4px; }}
.ios-footnote {{ font-size: 13px; color: {LABEL2}; line-height: 18px; margin: 2px 0 10px; }}
.ios-caption {{ font-size: 12px; color: {LABEL3}; }}

/* Campi di testo */
[data-testid="stTextInput"] label, [data-testid="stWidgetLabel"] p {{
  font-size: 13px !important; color: {LABEL2} !important; font-weight: 400 !important;
}}
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="select"] > div {{
  background: {GROUP} !important; border: none !important; border-radius: 12px !important;
}}
[data-baseweb="input"] input {{ color: {LABEL} !important; font-size: 17px !important; padding: 12px 14px !important; }}
[data-baseweb="input"] input::placeholder {{ color: {LABEL3} !important; }}
[data-baseweb="select"] * {{ color: {LABEL} !important; }}
[data-baseweb="popover"] ul, [data-baseweb="menu"] {{ background: {GROUP2} !important; }}

/* Pulsanti */
[data-testid="stBaseButton-primary"] {{
  background: {BLUE} !important; color: #fff !important; border: none !important;
  border-radius: 12px !important; min-height: 50px; font-size: 17px !important; font-weight: 600 !important;
}}
[data-testid="stBaseButton-primary"]:hover {{ filter: brightness(1.1); }}
[data-testid="stBaseButton-secondary"] {{
  background: {GROUP} !important; color: {BLUE} !important; border: none !important;
  border-radius: 10px !important; font-weight: 500 !important;
}}
[data-testid="stBaseButton-tertiary"] {{ color: {BLUE} !important; }}

/* Pillole (selezione multipla) */
[data-testid="stBaseButton-pills"] {{
  background: {GROUP} !important; color: {LABEL} !important; border: 1px solid {GROUP2} !important;
  border-radius: 18px !important; font-size: 15px !important;
}}
[data-testid="stBaseButton-pillsActive"] {{
  background: {BLUE} !important; color: #fff !important; border: 1px solid {BLUE} !important;
  border-radius: 18px !important; font-size: 15px !important;
}}

/* Controllo segmentato */
[data-testid="stBaseButton-segmented_control"] {{
  background: {GROUP} !important; color: {LABEL} !important; border: none !important; font-size: 15px !important;
}}
[data-testid="stBaseButton-segmented_controlActive"] {{
  background: #636366 !important; color: #fff !important; border: none !important;
  font-size: 15px !important; font-weight: 600 !important;
}}

/* Schede (pagina principale) come controllo segmentato */
[data-testid="stTabs"] [role="tablist"] {{ background: {GROUP}; border-radius: 10px; padding: 3px; gap: 2px; border: none; }}
[data-testid="stTabs"] [role="tab"] {{ border-radius: 8px; padding: 6px 14px; color: {LABEL2}; border: none !important; }}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {{ background: #636366; color: #fff; }}
[data-testid="stTabs"] [data-baseweb="tab-highlight"], [data-testid="stTabs"] [data-baseweb="tab-border"] {{ display: none; }}

/* Espandi/chiudi come righe di un elenco iOS */
[data-testid="stExpander"] details {{ background: {GROUP}; border: none !important; border-radius: 14px; }}
[data-testid="stExpander"] summary {{ padding: 14px 16px; font-size: 16px; }}
[data-testid="stExpander"] summary:hover {{ color: {LABEL}; }}

/* Contenitori con bordo come gruppi */
[data-testid="stVerticalBlockBorderWrapper"] {{ border-color: {GROUP2} !important; border-radius: 16px !important; }}

/* Avvisi, barra di avanzamento, tabelle */
[data-testid="stAlert"] {{ background: {GROUP} !important; border-radius: 12px !important; border: none !important; }}
[data-testid="stProgress"] > div > div > div > div {{ background: {BLUE} !important; }}
[data-testid="stDataFrame"] {{ border-radius: 12px; overflow: hidden; }}

/* Componenti propri */
.ios-card {{ background: {GROUP}; border-radius: 16px; padding: 16px 18px; margin-bottom: 10px; }}
.ios-tile {{ background: {GROUP}; border-radius: 14px; padding: 14px 16px; margin-bottom: 10px; min-height: 92px; }}
.ios-tile-label {{ font-size: 13px; color: {LABEL2}; margin-bottom: 4px; }}
.ios-tile-value {{ font-size: 22px; font-weight: 600; letter-spacing: 0.35px; line-height: 28px; }}
.ios-tile-sub {{ font-size: 12px; color: {LABEL3}; margin-top: 3px; line-height: 16px; }}
.ios-badge {{ display: inline-block; border-radius: 999px; padding: 4px 12px; font-size: 13px; font-weight: 600; }}
.ios-chip {{ display: inline-block; background: {GROUP2}; border-radius: 6px; padding: 2px 8px;
             font-size: 13px; font-weight: 600; color: {LABEL2}; margin-right: 6px; }}
.ios-list {{ background: {GROUP}; border-radius: 14px; overflow: hidden; margin-bottom: 10px; }}
.ios-row {{ padding: 12px 16px; font-size: 15px; line-height: 20px; border-bottom: 0.5px solid {SEPARATOR}; }}
.ios-row:last-child {{ border-bottom: none; }}
.ios-row .sub {{ display: block; font-size: 13px; color: {LABEL2}; margin-top: 2px; }}
.ios-dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 8px; vertical-align: middle; }}
.ios-score {{ padding: 12px 16px; border-bottom: 0.5px solid {SEPARATOR}; }}
.ios-score:last-child {{ border-bottom: none; }}
.ios-score-top {{ display: flex; justify-content: space-between; font-size: 15px; }}
.ios-score-top .w {{ color: {LABEL3}; font-size: 13px; margin-left: 6px; }}
.ios-track {{ height: 4px; background: {GROUP2}; border-radius: 2px; margin-top: 8px; }}
.ios-fill {{ height: 4px; border-radius: 2px; }}
.ios-table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
.ios-table th {{ text-align: right; font-weight: 500; color: {LABEL2}; font-size: 12px; padding: 10px 12px;
                 border-bottom: 0.5px solid {SEPARATOR}; white-space: nowrap; }}
.ios-table td {{ text-align: right; padding: 10px 12px; border-bottom: 0.5px solid {SEPARATOR}; white-space: nowrap; }}
.ios-table th:first-child, .ios-table td:first-child {{ text-align: left; }}
.ios-table tr:last-child td {{ border-bottom: none; }}
.ios-scroll {{ overflow-x: auto; background: {GROUP}; border-radius: 14px; margin-bottom: 10px; }}
.ios-hero-price {{ font-size: 40px; font-weight: 700; letter-spacing: 0.4px; line-height: 46px; }}
.ios-hero-cur {{ font-size: 17px; color: {LABEL2}; font-weight: 500; }}
.ios-callout {{ background: {GROUP}; border-radius: 16px; padding: 16px 18px; font-size: 17px; line-height: 24px; margin: 6px 0 12px; }}

/* Compatibilità con le classi della pagina principale */
.metric-card {{ background: {GROUP}; border-radius: 14px; padding: 14px 16px; margin-bottom: 10px; }}
.metric-label {{ font-size: 13px; color: {LABEL2}; margin-bottom: 4px; }}
.metric-value {{ font-size: 20px; font-weight: 600; color: {LABEL}; }}
.metric-value.green {{ color: {GREEN}; }} .metric-value.red {{ color: {RED}; }}
.metric-value.blue {{ color: {BLUE}; }} .metric-value.orange {{ color: {ORANGE}; }}
.section-header {{ font-size: 22px; font-weight: 700; margin: 26px 0 10px; color: {LABEL}; }}
.price-main {{ font-size: 40px; font-weight: 700; line-height: 46px; }}
.company-name {{ font-size: 15px; color: {LABEL2}; margin-bottom: 4px; }}
.ticker-badge {{ display: inline-block; background: {GROUP2}; border-radius: 6px; padding: 2px 8px;
                 font-size: 13px; font-weight: 600; color: {LABEL2}; margin-right: 6px; }}
</style>
"""


def apply_style():
    st.markdown(CSS, unsafe_allow_html=True)


def esc(text) -> str:
    return _html.escape(str(text if text is not None else ""))


def large_title(title: str, subtitle: str = ""):
    st.markdown(f"<div class='ios-large-title'>{esc(title)}</div>"
                + (f"<div class='ios-subtitle'>{esc(subtitle)}</div>" if subtitle else ""),
                unsafe_allow_html=True)


def section(title: str, footnote: str = ""):
    st.markdown(f"<div class='ios-section'>{esc(title)}</div>"
                + (f"<div class='ios-footnote'>{esc(footnote)}</div>" if footnote else ""),
                unsafe_allow_html=True)


def footnote(text: str):
    st.markdown(f"<div class='ios-footnote'>{esc(text)}</div>", unsafe_allow_html=True)


def badge(text: str, color: str) -> str:
    return (f"<span class='ios-badge' style='background:{color}26;color:{color}'>{esc(text)}</span>")


def tile(label: str, value: str, sub: str = "", color: str = LABEL) -> str:
    return (f"<div class='ios-tile'><div class='ios-tile-label'>{esc(label)}</div>"
            f"<div class='ios-tile-value' style='color:{color}'>{esc(value)}</div>"
            + (f"<div class='ios-tile-sub'>{esc(sub)}</div>" if sub else "") + "</div>")


def tiles(items, per_row: int = 3):
    """items = [(label, value, sub, color)] disposti in righe da per_row."""
    for start in range(0, len(items), per_row):
        cols = st.columns(per_row)
        for col, item in zip(cols, items[start:start + per_row]):
            col.markdown(tile(*item), unsafe_allow_html=True)


def list_rows(rows):
    """rows = [(testo, sottotesto, colore del pallino o None)]."""
    body = "".join(
        f"<div class='ios-row'>"
        + (f"<span class='ios-dot' style='background:{dot}'></span>" if dot else "")
        + f"{esc(text)}" + (f"<span class='sub'>{esc(sub)}</span>" if sub else "") + "</div>"
        for text, sub, dot in rows)
    st.markdown(f"<div class='ios-list'>{body}</div>", unsafe_allow_html=True)


def score_color(score) -> str:
    if score is None:
        return LABEL3
    return GREEN if score >= 65 else ORANGE if score >= 50 else RED


def score_rows(rows):
    """rows = [(nome, peso %, punteggio o None, nota)]."""
    body = ""
    for name, weight, score, note in rows:
        value = "n.d." if score is None else f"{score:.0f}"
        width = 0 if score is None else max(0, min(100, score))
        body += (f"<div class='ios-score'><div class='ios-score-top'><span>{esc(name)}"
                 f"<span class='w'>{weight}%</span></span><span style='color:{score_color(score)};font-weight:600'>"
                 f"{value}</span></div><div class='ios-track'><div class='ios-fill' style='width:{width}%;"
                 f"background:{score_color(score)}'></div></div>"
                 f"<div class='ios-tile-sub' style='margin-top:6px'>{esc(note)}</div></div>")
    st.markdown(f"<div class='ios-list'>{body}</div>", unsafe_allow_html=True)


def html_table(df: pd.DataFrame, formats: dict | None = None, colors: dict | None = None, index: bool = False):
    """Tabella in stile iOS che non dipende dal tema di Streamlit.
    formats = {colonna: funzione valore → testo}; colors = {colonna: funzione valore → colore}."""
    formats, colors = formats or {}, colors or {}
    data = df.reset_index() if index else df
    head = "".join(f"<th>{esc(c)}</th>" for c in data.columns)
    body = ""
    for _, row in data.iterrows():
        cells = ""
        for c in data.columns:
            v = row[c]
            text = formats[c](v) if c in formats else ("—" if pd.isna(v) else v)
            style = f" style='color:{colors[c](v)}'" if c in colors and not pd.isna(v) else ""
            cells += f"<td{style}>{esc(text)}</td>"
        body += f"<tr>{cells}</tr>"
    st.markdown(f"<div class='ios-scroll'><table class='ios-table'><thead><tr>{head}</tr></thead>"
                f"<tbody>{body}</tbody></table></div>", unsafe_allow_html=True)
