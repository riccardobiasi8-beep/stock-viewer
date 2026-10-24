"""
Sistema di design in stile Apple (modalità scura), condiviso da tutte le pagine.
Colori, tipografia e componenti seguono le Human Interface Guidelines di iOS:
sfondo nero, gruppi su grigio #1c1c1e, testo secondario attenuato, accento blu.
"""
import html as _html

import pandas as pd
import streamlit as st

# ── Palette in stile Apple (modalità chiara) ──────────────────────────────────
# Accento blu di sistema; verde/rosso/arancio nelle varianti "accessibili" che Apple
# usa per il testo su fondo chiaro: leggibili e meno aggressive dei toni pieni.
BLUE, GREEN, RED, ORANGE, YELLOW = "#007AFF", "#248A3D", "#D70015", "#C93400", "#B25000"
LABEL, LABEL2, LABEL3 = "#1C1C1E", "#6E6E73", "#AEAEB2"
BG, GROUP, GROUP2, SEPARATOR = "#F2F2F7", "#FFFFFF", "#E9E9EB", "#E5E5EA"
BLUE_SOFT = "#E8F1FF"        # selezioni: azzurro tenue invece del blu pieno
CHART_UP, CHART_DOWN = "#34C759", "#FF3B30"

CSS = f"""
<style>
:root {{ color-scheme: light; }}
html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"], .main {{
  background: {BG} !important; color: {LABEL};
}}
* {{ font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "Inter",
     "Helvetica Neue", Arial, sans-serif; -webkit-font-smoothing: antialiased; }}
[data-testid="stHeader"], [data-testid="stSidebar"], [data-testid="stToolbar"],
footer, #MainMenu, .stDeployButton {{ display: none !important; }}
.block-container {{ padding: 24px 18px 80px !important; max-width: 860px; margin: auto; }}
[data-testid="stMarkdownContainer"] p {{ color: {LABEL}; }}

/* Tipografia (scala iOS) */
.ios-large-title {{ font-size: 34px; font-weight: 700; letter-spacing: 0.37px; line-height: 41px; margin: 6px 0 4px; color: {LABEL}; }}
.ios-subtitle {{ font-size: 17px; color: {LABEL2}; line-height: 22px; margin-bottom: 20px; }}
.ios-section {{ font-size: 20px; font-weight: 600; letter-spacing: 0.38px; margin: 30px 0 4px; color: {LABEL}; }}
.ios-footnote {{ font-size: 13px; color: {LABEL2}; line-height: 18px; margin: 2px 0 10px; }}
.ios-caption {{ font-size: 12px; color: {LABEL3}; }}

/* Etichette dei controlli */
[data-testid="stWidgetLabel"] p, [data-testid="stWidgetLabel"] label {{
  font-size: 13px !important; color: {LABEL2} !important; font-weight: 500 !important;
  text-transform: none; letter-spacing: 0;
}}

/* Campi di testo e menu */
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="select"] > div,
[data-testid="stTextInputRootElement"] {{
  background: {GROUP} !important; border: 1px solid {SEPARATOR} !important; border-radius: 12px !important;
}}
[data-baseweb="input"]:focus-within, [data-baseweb="select"] > div:focus-within,
[data-testid="stTextInputRootElement"]:focus-within {{
  border-color: {BLUE} !important; box-shadow: 0 0 0 3px {BLUE_SOFT} !important;
}}
[data-baseweb="input"] input, [data-testid="stTextInputField"] {{
  color: {LABEL} !important; font-size: 17px !important; padding: 12px 14px !important;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "Helvetica Neue", Arial, sans-serif !important; }}
/* Dentro le schede bianche i campi diventano grigio chiaro, come nei moduli di iOS */
[class*="st-key-"][class*="_box"] [data-baseweb="input"], [class*="st-key-"][class*="_box"] [data-baseweb="base-input"],
[class*="st-key-"][class*="_box"] [data-testid="stTextInputRootElement"] {{
  background: {BG} !important; border-color: transparent !important;
}}
[data-baseweb="input"] input::placeholder, [data-testid="stTextInputField"]::placeholder {{ color: {LABEL3} !important; }}
[data-baseweb="select"] * {{ color: {LABEL} !important; }}
[data-testid="stSelectbox"] [role="group"] {{
  background: {GROUP} !important; border: 1px solid {SEPARATOR} !important; border-radius: 12px !important;
}}

/* Pulsanti */
button[kind="primary"], [data-testid="stBaseButton-primary"] {{
  background: {BLUE} !important; color: #fff !important; border: none !important;
  border-radius: 12px !important; min-height: 50px; font-size: 17px !important; font-weight: 600 !important;
  box-shadow: 0 1px 2px rgba(0,0,0,0.08);
}}
button[kind="primary"] p {{ color: #fff !important; }}
button[kind="primary"]:hover {{ filter: brightness(1.06); }}
button[kind="primary"]:disabled {{ background: {GROUP2} !important; color: {LABEL3} !important; box-shadow: none; }}
button[kind="primary"]:disabled p {{ color: {LABEL3} !important; }}
button[kind="secondary"], [data-testid="stBaseButton-secondary"] {{
  background: {BLUE_SOFT} !important; color: {BLUE} !important; border: none !important;
  border-radius: 10px !important; font-weight: 500 !important;
}}
button[kind="secondary"] p {{ color: {BLUE} !important; }}
button[kind="secondary"]:hover {{ filter: brightness(0.97); }}

/* Pillole (selezione multipla) — agganci per più versioni di Streamlit */
button[data-variant="pills"], button[kind="pills"] {{
  background: {GROUP} !important; border: 1px solid {SEPARATOR} !important; border-radius: 18px !important;
  box-shadow: 0 1px 1px rgba(0,0,0,0.03) !important; color: {LABEL} !important;
}}
button[data-variant="pills"] p, button[kind="pills"] p {{ color: {LABEL} !important; font-size: 15px !important; }}
button[data-variant="pills"][data-selected="true"], button[kind="pillsActive"] {{
  background: {BLUE_SOFT} !important; border: 1px solid {BLUE} !important;
}}
button[data-variant="pills"][data-selected="true"] p, button[kind="pillsActive"] p {{
  color: {BLUE} !important; font-weight: 600 !important;
}}

/* Controllo segmentato come in iOS: binario grigio, segmento scelto bianco */
[data-testid="stButtonGroup"]:has(button[data-variant="segmented_control"]) > div,
[data-testid="stButtonGroup"]:has(button[kind^="segmented_control"]) > div {{
  background: {GROUP2}; border-radius: 10px; padding: 2px; display: inline-flex; gap: 2px;
}}
button[data-variant="segmented_control"], button[kind="segmented_control"] {{
  background: transparent !important; border: none !important; border-radius: 8px !important;
  box-shadow: none !important; padding: 6px 18px !important; min-height: 32px;
}}
button[data-variant="segmented_control"] p, button[kind="segmented_control"] p {{
  color: {LABEL} !important; font-size: 15px !important;
}}
button[data-variant="segmented_control"][data-selected="true"], button[kind="segmented_controlActive"] {{
  background: {GROUP} !important; box-shadow: 0 1px 3px rgba(0,0,0,0.12), 0 1px 1px rgba(0,0,0,0.04) !important;
}}
button[data-variant="segmented_control"][data-selected="true"] p, button[kind="segmented_controlActive"] p {{
  font-weight: 600 !important;
}}

/* Schede della pagina principale come controllo segmentato */
[data-testid="stTabs"] [role="tablist"] {{ background: {GROUP2}; border-radius: 10px; padding: 2px; gap: 0; border: none; }}
[data-testid="stTabs"] [role="tab"] {{ border-radius: 8px; padding: 6px 16px; border: none !important; }}
[data-testid="stTabs"] [role="tab"] p {{ color: {LABEL} !important; font-size: 15px; }}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {{ background: {GROUP}; box-shadow: 0 1px 3px rgba(0,0,0,0.12) !important; }}
[data-testid="stTabs"] [role="tab"], [data-testid="stTab"] {{ border-bottom: none !important; }}
[data-testid="stTabs"] [role="tab"]::after, [data-testid="stTabs"] [role="tab"]::before,
[data-testid="stTabs"] [role="tablist"]::after, [data-testid="stTabs"] [role="tablist"]::before {{ display: none !important; }}
[data-testid="stTabs"] [role="tablist"] {{ border-bottom: none !important; box-shadow: none !important; }}
[data-testid="stTabs"] .react-aria-SelectionIndicator {{ display: none !important; }}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] p {{ font-weight: 600; }}
[data-testid="stTabs"] [data-baseweb="tab-highlight"], [data-testid="stTabs"] [data-baseweb="tab-border"] {{ display: none; }}

/* Espandi/chiudi come righe di un gruppo iOS */
[data-testid="stExpander"] details {{ background: {GROUP}; border: none !important; border-radius: 14px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04); }}
[data-testid="stExpander"] summary {{ padding: 14px 16px; }}
[data-testid="stExpander"] summary p {{ color: {LABEL} !important; font-size: 16px; }}

/* Contenitori con bordo = gruppi bianchi (riquadri con nome *_box) */
[class*="st-key-"][class*="_box"], [data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {{
  background: {GROUP}; border: none !important; border-radius: 18px !important; padding: 18px 18px 14px !important;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05), 0 4px 16px rgba(0,0,0,0.03);
}}

/* Avvisi, avanzamento, tabelle */
[data-testid="stAlert"] {{ background: {GROUP} !important; border-radius: 12px !important; border: 1px solid {SEPARATOR} !important; }}
[data-testid="stAlert"] p {{ color: {LABEL} !important; }}
[data-testid="stProgress"] > div > div > div > div {{ background: {BLUE} !important; }}
[data-testid="stProgress"] p {{ color: {LABEL2} !important; font-size: 13px; }}
[data-testid="stDataFrame"] {{ border-radius: 12px; overflow: hidden; }}
a, a p {{ color: {BLUE} !important; }}

/* Componenti propri */
.ios-card {{ background: {GROUP}; border-radius: 18px; padding: 18px 20px; margin-bottom: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05), 0 4px 16px rgba(0,0,0,0.03); }}
.ios-tile {{ background: {GROUP}; border-radius: 14px; padding: 14px 16px; margin-bottom: 10px; min-height: 112px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04); }}
.ios-tile-label {{ font-size: 13px; color: {LABEL2}; margin-bottom: 4px; }}
.ios-tile-value {{ font-size: 22px; font-weight: 600; letter-spacing: 0.35px; line-height: 28px; }}
.ios-tile-sub {{ font-size: 12px; color: {LABEL2}; margin-top: 3px; line-height: 16px; }}
.ios-badge {{ display: inline-block; border-radius: 999px; padding: 4px 12px; font-size: 13px; font-weight: 600; }}
.ios-chip {{ display: inline-block; background: {GROUP2}; border-radius: 6px; padding: 2px 8px;
             font-size: 13px; font-weight: 600; color: {LABEL}; margin-right: 6px; }}
.ios-list {{ background: {GROUP}; border-radius: 14px; overflow: hidden; margin-bottom: 10px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04); }}
.ios-row {{ padding: 12px 16px; font-size: 15px; line-height: 20px; color: {LABEL}; border-bottom: 1px solid {SEPARATOR}; }}
.ios-row:last-child {{ border-bottom: none; }}
.ios-row .sub {{ display: block; font-size: 13px; color: {LABEL2}; margin-top: 2px; }}
.ios-dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 8px; vertical-align: middle; }}
.ios-score {{ padding: 12px 16px; border-bottom: 1px solid {SEPARATOR}; }}
.ios-score:last-child {{ border-bottom: none; }}
.ios-score-top {{ display: flex; justify-content: space-between; font-size: 15px; color: {LABEL}; }}
.ios-score-top .w {{ color: {LABEL3}; font-size: 13px; margin-left: 6px; }}
.ios-track {{ height: 6px; background: {GROUP2}; border-radius: 3px; margin-top: 8px; }}
.ios-fill {{ height: 6px; border-radius: 3px; }}
.ios-table {{ width: 100%; border-collapse: collapse; font-size: 14px; color: {LABEL}; }}
.ios-table th {{ text-align: right; font-weight: 500; color: {LABEL2}; font-size: 12px; padding: 10px 12px;
                 border-bottom: 1px solid {SEPARATOR}; white-space: nowrap; }}
.ios-table td {{ text-align: right; padding: 10px 12px; border-bottom: 1px solid {SEPARATOR}; white-space: nowrap; }}
.ios-table th:first-child, .ios-table td:first-child {{ text-align: left; }}
.ios-table tr:last-child td {{ border-bottom: none; }}
.ios-scroll {{ overflow-x: auto; background: {GROUP}; border-radius: 14px; margin-bottom: 10px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04); }}
.ios-hero-price {{ font-size: 40px; font-weight: 700; letter-spacing: 0.4px; line-height: 46px; color: {LABEL}; }}
.ios-hero-cur {{ font-size: 17px; color: {LABEL2}; font-weight: 500; }}
.ios-callout {{ background: {GROUP}; border-radius: 16px; padding: 16px 18px; font-size: 17px; line-height: 24px;
  margin: 6px 0 12px; color: {LABEL}; box-shadow: 0 1px 3px rgba(0,0,0,0.05); border-left: 4px solid {BLUE}; }}

/* Compatibilità con le classi della pagina principale */
.metric-card {{ background: {GROUP}; border-radius: 14px; padding: 14px 16px; margin-bottom: 10px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04); }}
.metric-label {{ font-size: 13px; color: {LABEL2}; margin-bottom: 4px; text-transform: none !important;
  letter-spacing: 0 !important; font-weight: 400 !important; }}
.metric-value {{ font-size: 20px; font-weight: 600; color: {LABEL}; }}
.metric-value.green {{ color: {GREEN}; }} .metric-value.red {{ color: {RED}; }}
.metric-value.blue {{ color: {BLUE}; }} .metric-value.orange {{ color: {ORANGE}; }}
.section-header {{ font-size: 20px; font-weight: 600; margin: 28px 0 10px; color: {LABEL};
  text-transform: none !important; letter-spacing: 0.38px !important; border: none !important; }}
.price-main {{ font-size: 40px; font-weight: 700; line-height: 46px; color: {LABEL}; }}
.company-name {{ font-size: 15px; color: {LABEL2}; margin-bottom: 4px; }}
.ticker-badge {{ display: inline-block; background: {GROUP2}; border-radius: 6px; padding: 2px 8px;
                 font-size: 13px; font-weight: 600; color: {LABEL}; margin-right: 6px; }}
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
