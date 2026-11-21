"""Visual system: the survey sheet.

The audience reads municipal plan drawings, so the structure borrows theirs —
a title block that says what the sheet is, a plan extract, annotations in the
margin, a stamp for the caveat — without borrowing the nostalgia (no sepia, no
hatching, no texture).

Colour is functional. Each hue means one thing and appears nowhere else:
riverine is always teal, coastal is always ochre, red always means "qualified".
"""

from __future__ import annotations

import streamlit as st

PAPER = "#F6F7F4"
INK = "#15191B"
MUTED = "#5F6660"
RULE = "#C7CBC3"
RIVERINE = "#0E5A6B"
COASTAL = "#B07A1E"
SIGNAL = "#A6361C"
SIGNAL_WASH = "#FBEEE9"

CSS = f"""
<style>
@import url("https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap");

:root {{
  --paper: {PAPER}; --ink: {INK}; --muted: {MUTED}; --rule: {RULE};
  --riverine: {RIVERINE}; --coastal: {COASTAL};
  --signal: {SIGNAL}; --signal-wash: {SIGNAL_WASH};
  --ui: "Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --data: "IBM Plex Mono", ui-monospace, SFMono-Regular, monospace;
}}

.stApp {{ background: var(--paper); color: var(--ink); }}
html, body, [class*="css"] {{ font-family: var(--ui); }}
[data-testid="stHeader"] {{ background: var(--paper); }}
[data-testid="stToolbar"] {{ display: none; }}
.block-container {{ padding: 3.2rem 2rem 4rem; max-width: 1120px; }}
footer {{ display: none; }}

/* ---- sheet frame -------------------------------------------------- */
.sheet-head {{ border-bottom: 1px solid var(--rule); padding-bottom: .7rem;
  margin-bottom: .4rem; line-height: 1.5; }}
.brand {{ font-size: .95rem; font-weight: 600; letter-spacing: -.01em; }}
.brand span {{ color: var(--muted); font-weight: 400; }}
.scope-line {{ font-size: .8rem; color: var(--muted); font-family: var(--data); }}

h1.hero {{ font-size: 1.95rem; line-height: 1.22; font-weight: 600;
  letter-spacing: -.02em; margin: 1rem 0 .6rem; max-width: 46ch; }}
h1.hero strong {{ font-weight: 600; color: var(--riverine); }}
.hero-sub {{ color: var(--muted); font-size: .88rem; margin-bottom: 1.8rem; }}

h2.sec {{ font-size: .78rem; font-weight: 600; letter-spacing: 0; margin: 2.2rem 0 .5rem;
  padding-bottom: .35rem; border-bottom: 1px solid var(--rule); }}
p, li {{ line-height: 1.55; }}

/* ---- evidence margin ---------------------------------------------- */
.ev {{ font-size: .8rem; }}
.ev dt {{ color: var(--muted); margin-top: .75rem; font-size: .72rem; }}
.ev dd {{ margin: .1rem 0 0; color: var(--ink); }}
.ev .absent {{ color: var(--signal); }}

/* ---- mechanism bars ----------------------------------------------- */
.bar {{ display: grid; grid-template-columns: 5.2rem 1fr 5.5rem; align-items: center;
  gap: .8rem; margin: .45rem 0; font-size: .88rem; }}
.bar .track {{ display: block; height: 10px; background: #E4E6E1; }}
.bar .fill {{ display: block; height: 10px; }}
.bar .val {{ text-align: right; font-variant-numeric: tabular-nums;
  font-family: var(--data); font-size: .82rem; }}

/* ---- caveat stamp -------------------------------------------------- */
.stamp {{ border: 1px solid var(--signal); color: var(--signal);
  background: var(--signal-wash); padding: .6rem .8rem; font-size: .82rem;
  line-height: 1.4; margin: 1.2rem 0 .2rem; }}
.stamp b {{ font-weight: 600; }}

/* ---- tables -------------------------------------------------------- */
table.grid {{ width: 100%; border-collapse: collapse; font-size: .86rem; }}
table.grid th {{ text-align: left; font-weight: 500; color: var(--muted);
  border-bottom: 1px solid var(--rule); padding: .35rem .4rem; font-size: .75rem; }}
table.grid td {{ padding: .4rem; border-bottom: 1px solid #E4E6E1; }}
table.grid td.num {{ text-align: right; font-variant-numeric: tabular-nums;
  font-family: var(--data); font-size: .8rem; }}

/* ---- title block --------------------------------------------------- */
.titleblock {{ border-top: 1px solid var(--rule); margin-top: 3rem; padding-top: .6rem;
  display: flex; flex-wrap: wrap; gap: 1.6rem; font-family: var(--data);
  font-size: .7rem; color: var(--muted); }}

/* ---- refusal ------------------------------------------------------- */
.refusal {{ border-left: 3px solid var(--signal); padding: .5rem 0 .5rem .9rem; }}
.refusal .what {{ font-size: .95rem; font-weight: 500; }}
.refusal .missing {{ color: var(--muted); font-size: .82rem; margin-top: .4rem; }}

/* ---- native widgets, minimally ------------------------------------- */
.stSelectbox label, .stTextInput label {{ font-size: .72rem !important;
  color: var(--muted) !important; }}
.stButton button {{ border-radius: 0; font-family: var(--ui); font-weight: 500; }}
[data-testid="stBaseButton-primary"] {{ background: var(--ink); color: var(--paper);
  border: 1px solid var(--ink); }}
[data-testid="stBaseButton-primary"]:hover {{ background: #000; color: #fff; }}
[data-testid="stBaseButton-secondary"] {{ background: transparent; color: var(--ink);
  border: 1px solid var(--rule); }}
[data-testid="stBaseButton-secondary"]:hover {{ border-color: var(--ink); color: var(--ink); }}
[data-testid="stSegmentedControl"] {{ font-size: .82rem; }}
[data-testid="stSegmentedControl"] button {{ border-radius: 0 !important; }}
[data-testid="stSegmentedControl"] button p {{ font-size: .82rem; }}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
