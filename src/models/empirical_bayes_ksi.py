"""Empirical Bayes KSI Rate Benchmark Model (Gamma-Poisson Conjugate).

Contract: docs/data_quality/cleaning_contract.md, spatial_assignment_contract.md
Config:   config/modeling.yml
Decision: D001 (Corridor-month grain), D005 (Governance authority)

Model Details:
- Observed KSI count Y_i: total KSI crashes from 2019-2025 (7 years).
- Exposure E_i: 7.0 * corridor_length_miles_i.
- Prior distribution: lambda_i ~ Gamma(shape=alpha, rate=beta).
- Likelihood: Y_i | lambda_i ~ Poisson(E_i * lambda_i).
- Marginal log-likelihood optimization via Scipy L-BFGS-B (with Nelder-Mead fallback).
- Posterior mean rate: (alpha + Y_i) / (beta + E_i).
- EB annual expected KSI count: posterior_mean_rate * corridor_length_miles_i.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def fit_empirical_bayes_ksi(
    df_panel_or_features: pd.DataFrame,
    start_year: int = 2019,
    end_year: int = 2025,
) -> Tuple[Dict[str, Any], pd.DataFrame]:
    """Fit Gamma-Poisson Empirical Bayes model on historical corridor KSI data.

    Returns:
        (fit_summary_dict, corridor_eb_df)
    """
    df = df_panel_or_features[
        (df_panel_or_features["calendar_year"] >= start_year)
        & (df_panel_or_features["calendar_year"] <= end_year)
    ].copy()

    n_years = float(end_year - start_year + 1)

    if "corridor_id" not in df.columns:
        df = df.reset_index()

    agg_df = (
        df.groupby("corridor_id")
        .agg(
            corridor_name=("corridor_name", "first"),
            corridor_length_miles=("corridor_length_miles", "first"),
            historical_ksi_count=("ksi_crashes", "sum"),
        )
        .reset_index()
    )

    if len(agg_df) == 0:
        raise ValueError("No corridor data found for EB model fit")

    # Physical corridor length and 7-year exposure must remain distinct
    agg_df["eb_exposure_corridor_mile_years"] = n_years * agg_df["corridor_length_miles"]
    if (agg_df["eb_exposure_corridor_mile_years"] <= 0).any():
        raise ValueError("All corridor exposures must be strictly greater than 0")

    y_vals = agg_df["historical_ksi_count"].astype(float).values
    e_vals = agg_df["eb_exposure_corridor_mile_years"].astype(float).values

    # Method of Moments initialization
    rates = y_vals / e_vals
    mean_r = float(np.mean(rates))
    var_r = float(np.var(rates, ddof=1))

    if var_r > 0 and mean_r > 0:
        alpha_init = float((mean_r**2) / var_r)
        beta_init = float(mean_r / var_r)
    else:
        alpha_init = 1.0
        beta_init = 1.0

    def neg_log_likelihood(params: np.ndarray) -> float:
        alpha, beta = params[0], params[1]
        if alpha <= 1e-6 or beta <= 1e-6:
            return 1e12

        # log p(Y_i | alpha, beta, E_i)
        ll = (
            gammaln(alpha + y_vals)
            - gammaln(alpha)
            - gammaln(y_vals + 1.0)
            + alpha * np.log(beta)
            + y_vals * np.log(e_vals)
            - (alpha + y_vals) * np.log(beta + e_vals)
        )
        return -float(np.sum(ll))

    # 1. Attempt L-BFGS-B first
    optimizer_attempted_first = "L-BFGS-B"
    fallback_used = False
    bounds = [(1e-6, None), (1e-6, None)]

    res = minimize(
        neg_log_likelihood,
        x0=np.array([alpha_init, beta_init]),
        method="L-BFGS-B",
        bounds=bounds,
    )

    accepted_optimizer = "L-BFGS-B"

    # 2. Fallback to Nelder-Mead if L-BFGS-B fails
    if not res.success:
        fallback_used = True
        # Nelder-Mead does not support bounds; ensure positive initial point
        # and validate result post-optimization
        res = minimize(
            neg_log_likelihood,
            x0=np.array([max(1e-6, alpha_init), max(1e-6, beta_init)]),
            method="Nelder-Mead",
        )
        accepted_optimizer = "Nelder-Mead"

    if not res.success:
        raise RuntimeError(f"Empirical Bayes optimization failed to converge: {res.message}")

    alpha_fit = float(res.x[0])
    beta_fit = float(res.x[1])

    # Enforce positivity regardless of optimizer (Nelder-Mead cannot enforce bounds)
    if alpha_fit <= 0 or beta_fit <= 0:
        raise ValueError(f"Invalid fitted EB parameters: alpha={alpha_fit}, beta={beta_fit}")

    # Compute posterior estimates
    agg_df["posterior_mean_annual_rate_per_mile"] = (alpha_fit + y_vals) / (beta_fit + e_vals)

    # EB annual expected KSI count must use physical corridor length (NOT 7-year exposure)
    agg_df["eb_annual_historical_ksi_benchmark"] = (
        agg_df["posterior_mean_annual_rate_per_mile"] * agg_df["corridor_length_miles"]
    )
    agg_df["historical_annual_average_ksi"] = agg_df["historical_ksi_count"] / n_years

    # Prior mean rate per mile: alpha / beta
    prior_mean_rate = alpha_fit / beta_fit

    summary = {
        "start_year": start_year,
        "end_year": end_year,
        "n_years": n_years,
        "corridor_count": len(agg_df),
        "optimizer_attempted_first": optimizer_attempted_first,
        "fallback_used": fallback_used,
        "accepted_optimizer": accepted_optimizer,
        "converged": bool(res.success),
        "convergence_message": str(res.message),
        "objective_value_nll": round(float(res.fun), 6),
        "iterations": int(getattr(res, "nit", 0)),
        "function_evaluations": int(getattr(res, "nfev", 0)),
        "initialization_method": "method_of_moments",
        "alpha_0": round(alpha_init, 6),
        "beta_0": round(beta_init, 6),
        "alpha": round(alpha_fit, 6),
        "beta": round(beta_fit, 6),
        "prior_mean_annual_rate_per_mile": round(prior_mean_rate, 6),
        "total_historical_ksi_crashes": int(np.sum(y_vals)),
        "total_eb_annual_expected_ksi": round(float(agg_df["eb_annual_historical_ksi_benchmark"].sum()), 4),
    }

    return summary, agg_df
