"""Main Streamlit decision-support application entrypoint for Vision Zero Chicago.

Contract: docs/data_quality/decision_output_mart_contract.md
"""

from __future__ import annotations

from pathlib import Path
import streamlit as st

st.set_page_config(
    page_title="Vision Zero Chicago - Decision Support System",
    page_icon="🚦",
    layout="wide",
    initial_sidebar_state="expanded",
)

PAGES_DIR = Path(__file__).parent / "pages"

pages = [
    st.Page(str(PAGES_DIR / "1_Portfolio_Overview.py"), title="Portfolio Overview", icon="📊", default=True),
    st.Page(str(PAGES_DIR / "2_Corridor_Explorer.py"), title="Corridor Explorer", icon="🗺️"),
    st.Page(str(PAGES_DIR / "3_Governance_and_Methodology.py"), title="Governance & Methodology", icon="📜"),
]

pg = st.navigation(pages)
pg.run()
