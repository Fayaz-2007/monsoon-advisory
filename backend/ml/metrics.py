"""Verification metrics with year-block bootstrap confidence intervals.

All 38 districts on one day share the same weather, so rows are far from independent.
Confidence intervals therefore resample whole TEST YEARS (with replacement, ``CFG.n_boot``
draws) and recompute the pooled score; the 5–95% percentiles are stored.

Skill scores are ratios of pooled sums (``1 − Σloss_model / Σloss_ref``), so a draw only
needs per-year sums. AUC is computed exactly for each draw from a year × year matrix of
Mann–Whitney pair counts.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ml.config import CFG


# ---------------------------------------------------------------------------
# Per-sample losses
# ---------------------------------------------------------------------------


def rps(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Ranked probability score for 3 ordered classes (p: [n,3], y: 0/1/2)."""
    cp = np.cumsum(p, axis=1)[:, :2]
    obs = np.eye(3)[y.astype(int)]
    co = np.cumsum(obs, axis=1)[:, :2]
    return ((cp - co) ** 2).sum(axis=1)


def brier(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    return (p - y) ** 2


def pinball(q: np.ndarray, y: np.ndarray, tau: float) -> np.ndarray:
    d = y - q
    return np.maximum(tau * d, (tau - 1.0) * d)


# ---------------------------------------------------------------------------
# Year-block bootstrap
# ---------------------------------------------------------------------------


def _draws(n_years: int, rng: np.random.Generator) -> np.ndarray:
    """[n_boot, n_years] counts: how often each year appears in each bootstrap draw."""
    idx = rng.integers(0, n_years, size=(CFG.n_boot, n_years))
    return np.stack([np.bincount(r, minlength=n_years) for r in idx]).astype(float)


def _ci(values: np.ndarray) -> tuple[float, float]:
    v = values[np.isfinite(values)]
    if v.size == 0:
        return np.nan, np.nan
    lo, hi = np.percentile(v, [CFG.ci_low_pct, CFG.ci_high_pct])
    return float(lo), float(hi)


def skill_score(loss_model: np.ndarray, loss_ref: np.ndarray, years: np.ndarray,
                rng: np.random.Generator) -> tuple[float, float, float]:
    """1 − Σmodel/Σref with a year-block bootstrap CI → (value, ci_low, ci_high)."""
    ok = np.isfinite(loss_model) & np.isfinite(loss_ref)
    lm, lr, yr = loss_model[ok], loss_ref[ok], years[ok]
    if lm.size == 0 or lr.sum() <= 0:
        return np.nan, np.nan, np.nan
    uy, inv = np.unique(yr, return_inverse=True)
    sm = np.bincount(inv, weights=lm, minlength=len(uy))
    sr = np.bincount(inv, weights=lr, minlength=len(uy))
    w = _draws(len(uy), rng)
    with np.errstate(invalid="ignore", divide="ignore"):
        boot = 1.0 - (w @ sm) / (w @ sr)
    return (1.0 - sm.sum() / sr.sum(), *_ci(boot))


def auc_score(p: np.ndarray, y: np.ndarray, years: np.ndarray,
              rng: np.random.Generator) -> tuple[float, float, float]:
    """ROC-AUC (ties count ½) with a year-block bootstrap CI → (value, ci_low, ci_high)."""
    ok = np.isfinite(p) & np.isfinite(y)
    p, y, years = p[ok], y[ok], years[ok]
    if y.size == 0 or y.min() == y.max():
        return np.nan, np.nan, np.nan
    uy, inv = np.unique(years, return_inverse=True)
    n = len(uy)
    pos = [np.sort(p[(inv == a) & (y == 1)]) for a in range(n)]
    neg = [np.sort(p[(inv == b) & (y == 0)]) for b in range(n)]
    npos = np.array([len(x) for x in pos], dtype=float)
    nneg = np.array([len(x) for x in neg], dtype=float)
    pairs = np.zeros((n, n))
    for a in range(n):
        if not len(pos[a]):
            continue
        for b in range(n):
            if not len(neg[b]):
                continue
            lo = np.searchsorted(neg[b], pos[a], side="left")
            hi = np.searchsorted(neg[b], pos[a], side="right")
            pairs[a, b] = lo.sum() + 0.5 * (hi - lo).sum()
    one = np.ones(n)
    value = (one @ pairs @ one) / (npos.sum() * nneg.sum())
    w = _draws(n, rng)
    with np.errstate(invalid="ignore", divide="ignore"):
        boot = np.einsum("ia,ab,ib->i", w, pairs, w) / ((w @ npos) * (w @ nneg))
    return (float(value), *_ci(boot))


# ---------------------------------------------------------------------------
# Reliability diagram
# ---------------------------------------------------------------------------


def reliability_curve(p: np.ndarray, y: np.ndarray, n_bins: int = 10
                      ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ok = np.isfinite(p) & np.isfinite(y)
    p, y = p[ok], y[ok]
    edges = np.linspace(0, 1, n_bins + 1)
    b = np.clip(np.digitize(p, edges) - 1, 0, n_bins - 1)
    cnt = np.bincount(b, minlength=n_bins).astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean_p = np.bincount(b, weights=p, minlength=n_bins) / cnt
        obs = np.bincount(b, weights=y, minlength=n_bins) / cnt
    return mean_p, obs, cnt


def plot_reliability(curves: dict[str, tuple[np.ndarray, np.ndarray]], title: str,
                     path: Path) -> None:
    """curves: label → (p, y). Saves a reliability diagram with a count histogram."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax, axh) = plt.subplots(2, 1, figsize=(5.2, 6.2), height_ratios=[3, 1], sharex=True)
    ax.plot([0, 1], [0, 1], color="0.6", lw=1, ls="--", label="perfect")
    colors = {"SWM": "#1f77b4", "NEM": "#d62728", "ALL": "#2ca02c"}
    for label, (p, y) in curves.items():
        mp, obs, cnt = reliability_curve(p, y)
        keep = cnt >= 30
        ax.plot(mp[keep], obs[keep], marker="o", lw=1.5, color=colors.get(label),
                label=f"{label} (n={int(cnt.sum()):,})")
        axh.bar(np.linspace(0.05, 0.95, 10), cnt, width=0.09, alpha=0.45, color=colors.get(label))
    ax.set_ylabel("observed frequency")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_title(title, fontsize=10)
    ax.legend(fontsize=8, loc="upper left")
    axh.set_yscale("log")
    axh.set_xlabel("forecast probability")
    axh.set_ylabel("count")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)
