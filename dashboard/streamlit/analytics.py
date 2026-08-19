"""Decision Product Analytics helper for Vision Zero Chicago Streamlit decision-support app.

Contract: docs/data_quality/decision_output_mart_contract.md

Provides isolated, anonymous, decision-relevant telemetry via PostHog.
Guarantees:
- Completely safe no-op if PostHog is disabled, unavailable, uninstalled, or unconfigured.
- Never raises exceptions or interferes with analytical calculations.
- Zero PII, zero personal data, zero crash-level data.
- Default state is DISABLED unless explicitly configured via config/project.yml,
  Streamlit secrets, or environment variables.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

# Root directory
ROOT = Path(__file__).resolve().parents[2]
PROJECT_CONFIG_PATH = ROOT / "config" / "project.yml"

# Module-level client cache
_POSTHOG_CLIENT = None
_ANALYTICS_INITIALIZED = False
_ANONYMOUS_DISTINCT_ID = None


def _load_analytics_config() -> Dict[str, Any]:
    """Load analytics configuration from config/project.yml, env vars, or Streamlit secrets."""
    config = {
        "enabled": False,
        "platform": "posthog",
        "posthog_api_key": "",
        "posthog_host": "https://us.i.posthog.com",
    }

    # 1. Try reading config/project.yml
    try:
        if PROJECT_CONFIG_PATH.exists():
            import yaml

            with open(PROJECT_CONFIG_PATH, "r", encoding="utf-8") as f:
                p_cfg = yaml.safe_load(f) or {}
                a_cfg = p_cfg.get("analytics", {})
                if isinstance(a_cfg, dict):
                    config["enabled"] = bool(a_cfg.get("enabled", False))
                    config["posthog_api_key"] = str(a_cfg.get("posthog_api_key", "")).strip()
                    config["posthog_host"] = str(a_cfg.get("posthog_host", "https://us.i.posthog.com")).strip()
    except Exception:
        pass

    # 2. Environment variable overrides
    env_enabled = os.environ.get("VISION_ZERO_ANALYTICS_ENABLED", "").strip().lower()
    if env_enabled in ("1", "true", "yes", "on"):
        config["enabled"] = True
    elif env_enabled in ("0", "false", "no", "off"):
        config["enabled"] = False

    env_key = os.environ.get("POSTHOG_API_KEY", "").strip()
    if env_key:
        config["posthog_api_key"] = env_key

    env_host = os.environ.get("POSTHOG_HOST", "").strip()
    if env_host:
        config["posthog_host"] = env_host

    # 3. Streamlit secrets overrides if present
    try:
        import streamlit as st

        if hasattr(st, "secrets") and "analytics" in st.secrets:
            sec_a = st.secrets["analytics"]
            if "enabled" in sec_a:
                config["enabled"] = bool(sec_a["enabled"])
            if "posthog_api_key" in sec_a:
                config["posthog_api_key"] = str(sec_a["posthog_api_key"]).strip()
            if "posthog_host" in sec_a:
                config["posthog_host"] = str(sec_a["posthog_host"]).strip()
    except Exception:
        pass

    return config


def _get_distinct_id() -> str:
    """Generate or retrieve an anonymous session-scoped identifier without any PII."""
    global _ANONYMOUS_DISTINCT_ID
    try:
        import streamlit as st

        if hasattr(st, "session_state"):
            if "_anonymous_user_id" not in st.session_state:
                st.session_state["_anonymous_user_id"] = f"anon_{uuid.uuid4().hex[:12]}"
            return str(st.session_state["_anonymous_user_id"])
    except Exception:
        pass

    if _ANONYMOUS_DISTINCT_ID is None:
        _ANONYMOUS_DISTINCT_ID = f"anon_{uuid.uuid4().hex[:12]}"
    return _ANONYMOUS_DISTINCT_ID


def _get_posthog_client():
    """Lazily initialize and return PostHog client, or None if disabled/unavailable."""
    global _POSTHOG_CLIENT, _ANALYTICS_INITIALIZED
    if _ANALYTICS_INITIALIZED:
        return _POSTHOG_CLIENT

    _ANALYTICS_INITIALIZED = True
    try:
        cfg = _load_analytics_config()
        if not cfg.get("enabled"):
            _POSTHOG_CLIENT = None
            return None

        api_key = cfg.get("posthog_api_key", "")
        if not api_key:
            _POSTHOG_CLIENT = None
            return None

        import posthog

        host = cfg.get("posthog_host", "https://us.i.posthog.com")
        _POSTHOG_CLIENT = posthog.Posthog(
            project_api_key=api_key,
            host=host,
            debug=False,
            disable_geoip=True,  # Preserve anonymity
        )
    except Exception:
        _POSTHOG_CLIENT = None

    return _POSTHOG_CLIENT


def is_analytics_enabled() -> bool:
    """Check if decision product analytics is currently active and configured."""
    try:
        cfg = _load_analytics_config()
        return bool(cfg.get("enabled") and cfg.get("posthog_api_key"))
    except Exception:
        return False


def track_event(event_name: str, properties: Optional[Dict[str, Any]] = None) -> None:
    """Emit an anonymous event to PostHog if analytics is enabled. Safe no-op on failure."""
    try:
        client = _get_posthog_client()
        if client is None:
            return
        distinct_id = _get_distinct_id()
        props = properties.copy() if properties else {}
        props["app"] = "vision-zero-chicago"
        client.capture(distinct_id=distinct_id, event=event_name, properties=props)
    except Exception:
        pass


def track_page_view(page_name: str) -> None:
    """Track anonymous page navigation event."""
    track_event("page_view", {"page": page_name})


def track_scenario_selected(
    scenario_id: str,
    budget: Optional[float] = None,
    equity_floor: Optional[float] = None,
    cmf_scenario: Optional[str] = None,
) -> None:
    """Track anonymous scenario parameter selection event."""
    props: Dict[str, Any] = {"scenario_id": scenario_id}
    if budget is not None:
        props["budget"] = float(budget)
    if equity_floor is not None:
        props["equity_floor"] = float(equity_floor)
    if cmf_scenario is not None:
        props["cmf_scenario"] = str(cmf_scenario)
    track_event("scenario_selected", props)


def track_corridor_inspected(corridor_id: str) -> None:
    """Track anonymous corridor detail inspection event."""
    track_event("corridor_inspected", {"corridor_id": corridor_id})


def track_portfolio_exported(scenario_id: str, budget: Optional[float] = None) -> None:
    """Track anonymous portfolio CSV export event."""
    props: Dict[str, Any] = {"scenario_id": scenario_id}
    if budget is not None:
        props["budget"] = float(budget)
    track_event("portfolio_exported", props)


def track_app_open() -> None:
    """Track anonymous application session initialization."""
    track_event("app_open")
