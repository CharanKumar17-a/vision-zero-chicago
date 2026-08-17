"""Main Streamlit decision-support application entrypoint for Vision Zero Chicago.

Contract: docs/data_quality/decision_output_mart_contract.md
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add repository root to sys.path so Streamlit Cloud can resolve top-level dashboard namespace
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import streamlit as st

st.set_page_config(
    page_title="Vision Zero Chicago - Decision Support System",
    layout="wide",
    initial_sidebar_state="expanded",
)

PAGES_DIR = Path(__file__).parent / "pages"

pages = [
    st.Page(str(PAGES_DIR / "0_Executive_Recommendation.py"), title="Executive Recommendation", default=True),
    st.Page(str(PAGES_DIR / "1_Portfolio_Overview.py"), title="Portfolio Overview"),
    st.Page(str(PAGES_DIR / "2_Corridor_Explorer.py"), title="Corridor Explorer"),
    st.Page(str(PAGES_DIR / "3_Governance_and_Methodology.py"), title="Governance & Methodology"),
]

pg = st.navigation(pages)
pg.run()
