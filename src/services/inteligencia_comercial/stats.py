"""Pure numpy/pandas statistical toolkit.

Every method used by the Inteligencia Comercial report is implemented here from
first principles. The project runtime has numpy, pandas, matplotlib and openpyxl
but NOT scipy, statsmodels or scikit-learn, and adding them would touch the
dependency set that the production daily job runs on. Implementing the handful
of primitives we need keeps the report reproducible with zero new dependencies.

Every function is deterministic and side-effect free.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Distributions (replacements for the scipy.stats calls we would otherwise use)
# ---------------------------------------------------------------------------

_SQRT2 = math.sqrt(2.0)


def normal_cdf(z: float) -> float:
    """Standard normal CDF via the stdlib error function."""
    return 0.5 * (1.0 + math.erf(z / _SQRT2))


def normal_sf(z: float) -> float:
    """Standard normal survival function P(Z > z)."""
    return 1.0 - normal_cdf(z)


def two_sided_p(z: float) -> float:
    """Two-sided p-value for a standard normal test statistic."""
    return 2.0 * normal_sf(abs(float(z)))


def chi2_sf(stat: float, df: int) -> float:
    """Upper-tail probability of a chi-square distribution.

    Uses the Wilson-Hilferty cube-root transform, which maps a chi-square to an
    approximately standard normal variable. Its relative error is below ~1% for
    df >= 3, which is well inside what we need to flag over/under-indexed cells
    in a contingency table.
    """
    if df <= 0:
        return float("nan")
    if stat <= 0:
        return 1.0
    ratio = stat / df
    z = (ratio ** (1.0 / 3.0) - (1.0 - 2.0 / (9.0 * df))) / math.sqrt(2.0 / (9.0 * df))
    return normal_sf(z)


# ---------------------------------------------------------------------------
# Robust location / scale
# ---------------------------------------------------------------------------

# Scale factor that makes the MAD a consistent estimator of sigma for normal data.
MAD_TO_SIGMA = 1.4826


def mad(values: np.ndarray) -> float:
    """Median absolute deviation (unscaled)."""
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    return float(np.median(np.abs(arr - np.median(arr))))


def robust_zscore(values) -> np.ndarray:
    """Modified z-score using median and scaled MAD.

    Preferred over the classic mean/std z-score because a handful of extreme
    clients would otherwise inflate the standard deviation and mask themselves.
    Falls back to a zero vector when the MAD collapses (constant series).
    """
    arr = np.asarray(values, dtype=float)
    med = np.nanmedian(arr)
    scale = MAD_TO_SIGMA * mad(arr)
    if not np.isfinite(scale) or scale == 0:
        return np.zeros_like(arr)
    return (arr - med) / scale


def coefficient_of_variation(values) -> float:
    """Std / mean. Returns NaN when the mean is zero or the series is empty."""
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    mean = arr.mean()
    if mean == 0:
        return float("nan")
    return float(arr.std(ddof=0) / abs(mean))


# ---------------------------------------------------------------------------
# Concentration
# ---------------------------------------------------------------------------


def gini(values) -> float:
    """Gini coefficient of a non-negative distribution.

    0 = perfectly even, 1 = one entity holds everything. Negative values (returns,
    credit notes) are clipped to zero first because the Gini is only defined on a
    non-negative distribution.
    """
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    arr = np.clip(arr, 0, None)
    if arr.size == 0 or arr.sum() == 0:
        return float("nan")
    arr = np.sort(arr)
    n = arr.size
    index = np.arange(1, n + 1)
    return float((2.0 * (index * arr).sum()) / (n * arr.sum()) - (n + 1.0) / n)


def lorenz_curve(values, points: int = 101) -> tuple[np.ndarray, np.ndarray]:
    """Lorenz curve resampled onto a fixed grid.

    Returns (cumulative share of population, cumulative share of value), both on
    [0, 1] and both starting at 0. The fixed grid keeps the chart series small
    regardless of how many clients feed it.
    """
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    arr = np.clip(arr, 0, None)
    if arr.size == 0 or arr.sum() == 0:
        grid = np.linspace(0, 1, points)
        return grid, grid
    arr = np.sort(arr)
    cum = np.cumsum(arr) / arr.sum()
    pop = np.arange(1, arr.size + 1) / arr.size
    pop = np.concatenate([[0.0], pop])
    cum = np.concatenate([[0.0], cum])
    grid = np.linspace(0, 1, points)
    return grid, np.interp(grid, pop, cum)


def hhi(values) -> float:
    """Herfindahl-Hirschman Index on a 0-10000 scale.

    Sum of squared percentage market shares. Under US DoJ guidance, < 1500 is
    unconcentrated, 1500-2500 moderately concentrated, > 2500 highly concentrated.
    """
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    arr = np.clip(arr, 0, None)
    total = arr.sum()
    if total == 0:
        return float("nan")
    shares = arr / total * 100.0
    return float((shares**2).sum())


def pareto_share(values, threshold: float = 0.8) -> float:
    """Fraction of entities that accumulate `threshold` of the total value.

    The classic "what % of clients make 80% of revenue" number.
    """
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    arr = np.clip(arr, 0, None)
    if arr.size == 0 or arr.sum() == 0:
        return float("nan")
    arr = np.sort(arr)[::-1]
    cum = np.cumsum(arr) / arr.sum()
    reached = int(np.searchsorted(cum, threshold) + 1)
    return float(min(reached, arr.size) / arr.size)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def quantile_score(series: pd.Series, bins: int = 5, ascending: bool = True) -> pd.Series:
    """Rank a series into `bins` scores of 1..bins.

    Uses average-rank percentiles rather than pd.qcut because real business data
    is full of ties (hundreds of clients with exactly one invoice), and qcut
    raises or produces unequal bins when duplicate edges collapse.

    Args:
        series: values to score.
        bins: number of buckets.
        ascending: True  -> higher value gets the higher score (frequency, monetary).
                   False -> higher value gets the LOWER score (recency: recent is better).
    """
    values = pd.to_numeric(series, errors="coerce")
    if values.notna().sum() == 0:
        return pd.Series(np.nan, index=series.index, dtype="float64")
    pct = values.rank(method="average", pct=True, ascending=ascending)
    scores = np.ceil(pct * bins)
    scores = scores.clip(lower=1, upper=bins)
    return scores.astype("Int64")


# ---------------------------------------------------------------------------
# Hypothesis tests
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProportionTest:
    """Result of comparing one group's rate against the pooled rate."""

    rate: float
    baseline: float
    n: int
    z: float
    p_value: float

    @property
    def significant(self) -> bool:
        """Two-sided significance at alpha = 0.05."""
        return bool(np.isfinite(self.p_value) and self.p_value < 0.05)


def proportion_ztest(successes: float, n: float, baseline: float) -> ProportionTest:
    """One-sample z-test of a proportion against a known baseline rate.

    Used to separate genuinely underperforming branches/carriers from small
    samples that merely look bad. A branch with 3 rejections out of 40 is noise;
    the same rate over 9000 lines is a real signal.
    """
    n = float(n)
    if n <= 0 or not np.isfinite(baseline) or baseline <= 0 or baseline >= 1:
        return ProportionTest(float("nan"), baseline, int(n), float("nan"), float("nan"))
    rate = float(successes) / n
    se = math.sqrt(baseline * (1.0 - baseline) / n)
    if se == 0:
        return ProportionTest(rate, baseline, int(n), float("nan"), float("nan"))
    z = (rate - baseline) / se
    return ProportionTest(rate, baseline, int(n), float(z), two_sided_p(z))


@dataclass(frozen=True)
class ChiSquareResult:
    """Contingency-table independence test."""

    statistic: float
    dof: int
    p_value: float
    expected: pd.DataFrame
    residuals: pd.DataFrame
    cramers_v: float


def chi_square_residuals(table: pd.DataFrame) -> ChiSquareResult:
    """Pearson chi-square test of independence with standardized residuals.

    The residual (observed - expected) / sqrt(expected) is approximately standard
    normal, so |residual| > 2 marks a cell that over- or under-indexes beyond
    chance. That is the actionable output: which channel buys which category far
    more (or far less) than its size would predict.
    """
    observed = table.astype(float).fillna(0.0)
    total = observed.values.sum()
    if total <= 0:
        empty = observed * np.nan
        return ChiSquareResult(float("nan"), 0, float("nan"), empty, empty, float("nan"))

    row_totals = observed.sum(axis=1).values.reshape(-1, 1)
    col_totals = observed.sum(axis=0).values.reshape(1, -1)
    expected_values = row_totals @ col_totals / total
    expected = pd.DataFrame(expected_values, index=observed.index, columns=observed.columns)

    with np.errstate(divide="ignore", invalid="ignore"):
        residual_values = np.where(
            expected_values > 0,
            (observed.values - expected_values) / np.sqrt(expected_values),
            np.nan,
        )
    residuals = pd.DataFrame(residual_values, index=observed.index, columns=observed.columns)

    statistic = float(np.nansum(residual_values**2))
    dof = (observed.shape[0] - 1) * (observed.shape[1] - 1)
    p_value = chi2_sf(statistic, dof) if dof > 0 else float("nan")
    min_dim = min(observed.shape) - 1
    cramers_v = float(math.sqrt(statistic / (total * min_dim))) if min_dim > 0 else float("nan")

    return ChiSquareResult(statistic, dof, p_value, expected, residuals, cramers_v)


# ---------------------------------------------------------------------------
# Regression
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OLSResult:
    """Simple linear regression y = intercept + slope * x."""

    slope: float
    intercept: float
    slope_stderr: float
    r_squared: float
    n: int
    t_stat: float
    p_value: float

    def ci95(self) -> tuple[float, float]:
        """Normal-approximation 95% confidence interval for the slope.

        We use +/-1.96 rather than a t-quantile; with the sample sizes involved
        (hundreds of client-month observations per article) the two agree to
        within a couple of percent.
        """
        if not np.isfinite(self.slope_stderr):
            return (float("nan"), float("nan"))
        return (self.slope - 1.96 * self.slope_stderr, self.slope + 1.96 * self.slope_stderr)


def ols(x, y) -> OLSResult:
    """Least-squares fit of a single predictor, with inference on the slope."""
    xa = np.asarray(x, dtype=float)
    ya = np.asarray(y, dtype=float)
    mask = np.isfinite(xa) & np.isfinite(ya)
    xa, ya = xa[mask], ya[mask]
    n = xa.size
    nan = float("nan")
    if n < 3 or np.allclose(xa, xa[0]):
        return OLSResult(nan, nan, nan, nan, n, nan, nan)

    design = np.column_stack([np.ones(n), xa])
    coeffs, *_ = np.linalg.lstsq(design, ya, rcond=None)
    intercept, slope = float(coeffs[0]), float(coeffs[1])

    fitted = design @ coeffs
    residuals = ya - fitted
    ss_res = float((residuals**2).sum())
    ss_tot = float(((ya - ya.mean()) ** 2).sum())
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else nan

    dof = n - 2
    sigma2 = ss_res / dof if dof > 0 else nan
    sxx = float(((xa - xa.mean()) ** 2).sum())
    stderr = math.sqrt(sigma2 / sxx) if (dof > 0 and sxx > 0 and sigma2 >= 0) else nan
    t_stat = slope / stderr if (np.isfinite(stderr) and stderr > 0) else nan
    p_value = two_sided_p(t_stat) if np.isfinite(t_stat) else nan

    return OLSResult(slope, intercept, stderr, r_squared, n, t_stat, p_value)


# ---------------------------------------------------------------------------
# Time series
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Decomposition:
    """Classical decomposition of a seasonal series."""

    observed: pd.Series
    trend: pd.Series
    seasonal: pd.Series
    residual: pd.Series
    seasonal_indices: pd.Series
    model: str

    @property
    def seasonal_strength(self) -> float:
        """Share of de-trended variance explained by the seasonal component.

        Following Wang/Smith/Hyndman: 1 - Var(residual) / Var(seasonal + residual),
        clipped to [0, 1]. Above ~0.6 means seasonality genuinely drives the series.
        """
        seasonal = self.seasonal.dropna()
        residual = self.residual.dropna()
        common = seasonal.index.intersection(residual.index)
        if len(common) < 3:
            return float("nan")
        combined = seasonal.loc[common] + residual.loc[common]
        denom = float(np.var(combined))
        if denom == 0:
            return float("nan")
        return float(np.clip(1.0 - float(np.var(residual.loc[common])) / denom, 0.0, 1.0))


def seasonal_decompose(series: pd.Series, period: int = 12, model: str = "multiplicative") -> Decomposition:
    """Classical decomposition into trend, seasonal and residual components.

    Trend is a centred moving average of length `period` (a 2xN average when the
    period is even, so the window stays centred). The seasonal component is the
    average de-trended value per calendar position, normalised so the indices
    average to 1 (multiplicative) or sum to 0 (additive).

    A multiplicative model is the right default for beverage volume: the summer
    peak scales with the size of the business rather than adding a fixed amount.
    """
    values = pd.to_numeric(series, errors="coerce").astype(float)
    n = len(values)
    if n < 2 * period:
        empty = pd.Series(np.nan, index=values.index, dtype=float)
        return Decomposition(
            values, empty, empty, empty,
            pd.Series(np.nan, index=range(period), dtype=float), model,
        )

    if period % 2 == 0:
        rolled = values.rolling(window=period, center=True).mean()
        trend = rolled.rolling(window=2).mean().shift(-1)
    else:
        trend = values.rolling(window=period, center=True).mean()

    if model == "multiplicative":
        with np.errstate(divide="ignore", invalid="ignore"):
            detrended = values / trend.replace(0, np.nan)
    else:
        detrended = values - trend

    position = np.arange(n) % period
    frame = pd.DataFrame({"pos": position, "value": detrended.values})
    means = frame.groupby("pos")["value"].mean()
    means = means.reindex(range(period))

    if model == "multiplicative":
        overall = means.mean()
        indices = means / overall if (pd.notna(overall) and overall != 0) else means
        indices = indices.fillna(1.0)
    else:
        indices = (means - means.mean()).fillna(0.0)

    seasonal = pd.Series(indices.values[position], index=values.index, dtype=float)

    if model == "multiplicative":
        with np.errstate(divide="ignore", invalid="ignore"):
            residual = values / (trend * seasonal).replace(0, np.nan)
    else:
        residual = values - trend - seasonal

    return Decomposition(values, trend, seasonal, residual, indices, model)


@dataclass(frozen=True)
class Forecast:
    """Point forecast plus a prediction interval."""

    fitted: pd.Series
    forecast: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    alpha: float
    beta: float
    gamma: float
    sse: float
    residual_std: float
    mape: float
    params: dict = field(default_factory=dict)


def holt_winters_additive(
    series: pd.Series,
    period: int = 12,
    horizon: int = 6,
    grid: int = 5,
) -> Forecast:
    """Additive Holt-Winters (triple exponential smoothing) with grid-searched parameters.

    Level, trend and seasonal components are updated recursively; the smoothing
    parameters alpha/beta/gamma are chosen by exhaustive grid search minimising
    in-sample squared error, which is robust and needs no optimiser.

    The prediction interval widens with the horizon following the standard
    additive-error approximation sigma_h = sigma * sqrt(1 + sum_{j<h} (alpha(1+j*beta))^2),
    so the band reflects that uncertainty compounds the further out you forecast.
    """
    values = pd.to_numeric(series, errors="coerce").astype(float).dropna()
    y = values.values
    n = y.size
    nan_arr = np.full(horizon, np.nan)

    if n < 2 * period + 1:
        return Forecast(
            pd.Series(np.nan, index=values.index, dtype=float),
            nan_arr, nan_arr.copy(), nan_arr.copy(),
            float("nan"), float("nan"), float("nan"),
            float("nan"), float("nan"), float("nan"),
            {"reason": f"serie de {n} puntos, se necesitan al menos {2 * period + 1}"},
        )

    level0 = y[:period].mean()
    trend0 = (y[period : 2 * period].mean() - y[:period].mean()) / period
    seasonal0 = y[:period] - level0

    candidates = np.linspace(0.1, 0.9, grid)

    def run(alpha: float, beta: float, gamma: float):
        level, trend = level0, trend0
        seasonal = seasonal0.copy()
        fitted = np.empty(n)
        for t in range(n):
            season = seasonal[t % period]
            fitted[t] = level + trend + season
            error = y[t] - fitted[t]
            prev_level = level
            level = alpha * (y[t] - season) + (1 - alpha) * (prev_level + trend)
            trend = beta * (level - prev_level) + (1 - beta) * trend
            seasonal[t % period] = gamma * (y[t] - level) + (1 - gamma) * season
            del error
        return fitted, level, trend, seasonal

    best = None
    for alpha in candidates:
        for beta in candidates:
            for gamma in candidates:
                fitted, level, trend, seasonal = run(alpha, beta, gamma)
                sse = float(((y[period:] - fitted[period:]) ** 2).sum())
                if not np.isfinite(sse):
                    continue
                if best is None or sse < best[0]:
                    best = (sse, alpha, beta, gamma, fitted, level, trend, seasonal)

    if best is None:
        return Forecast(
            pd.Series(np.nan, index=values.index, dtype=float),
            nan_arr, nan_arr.copy(), nan_arr.copy(),
            float("nan"), float("nan"), float("nan"),
            float("nan"), float("nan"), float("nan"),
            {"reason": "no convergio"},
        )

    sse, alpha, beta, gamma, fitted, level, trend, seasonal = best

    steps = np.arange(1, horizon + 1)
    point = level + steps * trend + np.array([seasonal[(n + h - 1) % period] for h in steps])

    residuals = y[period:] - fitted[period:]
    dof = max(len(residuals) - 3, 1)
    residual_std = float(math.sqrt(float((residuals**2).sum()) / dof))

    variance_multiplier = np.array(
        [1.0 + sum((alpha * (1.0 + j * beta)) ** 2 for j in range(1, h)) for h in steps]
    )
    sigma_h = residual_std * np.sqrt(variance_multiplier)

    with np.errstate(divide="ignore", invalid="ignore"):
        actual = y[period:]
        pct_err = np.where(actual != 0, np.abs(residuals / actual), np.nan)
    mape = float(np.nanmean(pct_err) * 100.0)

    return Forecast(
        pd.Series(fitted, index=values.index, dtype=float),
        point,
        point - 1.96 * sigma_h,
        point + 1.96 * sigma_h,
        float(alpha), float(beta), float(gamma),
        float(sse), residual_std, mape,
        {"period": period, "n": n},
    )


@dataclass(frozen=True)
class ControlLimits:
    """Robust statistical-process-control band."""

    center: float
    lower: float
    upper: float
    breaches: pd.Series


def control_limits(series: pd.Series, sigmas: float = 3.0) -> ControlLimits:
    """Shewhart-style control chart built on median and scaled MAD.

    The classic mean +/- 3-sigma chart is self-defeating on sales data: the very
    outliers you want to detect drag the mean and inflate the standard deviation,
    so they end up inside their own limits. Median and MAD are unaffected by up
    to 50% contamination.
    """
    values = pd.to_numeric(series, errors="coerce").astype(float)
    center = float(np.nanmedian(values))
    scale = MAD_TO_SIGMA * mad(values.values)
    if not np.isfinite(scale) or scale == 0:
        scale = float(np.nanstd(values))
    lower = center - sigmas * scale
    upper = center + sigmas * scale
    breaches = (values < lower) | (values > upper)
    return ControlLimits(center, lower, upper, breaches.fillna(False))


# ---------------------------------------------------------------------------
# Association rules
# ---------------------------------------------------------------------------


def association_rules(
    baskets: pd.DataFrame,
    basket_col: str,
    item_col: str,
    min_support: float = 0.01,
    min_lift: float = 1.0,
    max_items: int = 60,
) -> pd.DataFrame:
    """Pairwise market-basket rules with support, confidence, lift and conviction.

    Co-occurrence is computed as a boolean incidence matrix multiplied by its own
    transpose, which is far faster than enumerating itemsets and is exact for the
    pairwise (2-itemset) case that drives cross-sell decisions.

    Metrics, for a rule A -> B:
      support(A,B) = P(A and B)                  how often the pair actually happens
      confidence   = P(B|A)                      hit rate of the recommendation
      lift         = P(B|A) / P(B)               >1 means A genuinely predicts B
      leverage     = P(A,B) - P(A)P(B)           absolute excess over independence
      conviction   = (1-P(B)) / (1-P(B|A))       how often the rule would be wrong
                                                 if A and B were independent

    Args:
        baskets: long frame of (basket id, item) pairs; duplicates are ignored.
        min_support: minimum P(A and B) for a rule to be reported.
        min_lift: minimum lift for a rule to be reported.
        max_items: keep only the N most frequent items, bounding the matrix at N^2.
    """
    columns = [
        "antecedente", "consecuente", "soporte", "soporte_antecedente",
        "soporte_consecuente", "confianza", "lift", "leverage", "conviccion", "baskets",
    ]
    if baskets.empty:
        return pd.DataFrame(columns=columns)

    pairs = baskets[[basket_col, item_col]].dropna().drop_duplicates()
    if pairs.empty:
        return pd.DataFrame(columns=columns)

    top_items = pairs[item_col].value_counts().head(max_items).index
    pairs = pairs[pairs[item_col].isin(top_items)]

    n_baskets = pairs[basket_col].nunique()
    if n_baskets == 0:
        return pd.DataFrame(columns=columns)

    incidence = pd.crosstab(pairs[basket_col], pairs[item_col]).astype(bool).astype(np.int32)
    items = list(incidence.columns)
    matrix = incidence.values
    co_counts = matrix.T @ matrix
    item_counts = np.diag(co_counts).astype(float)

    support_single = item_counts / n_baskets
    rows = []
    for i, antecedent in enumerate(items):
        p_a = support_single[i]
        if p_a <= 0:
            continue
        for j, consequent in enumerate(items):
            if i == j:
                continue
            joint = co_counts[i, j] / n_baskets
            if joint < min_support:
                continue
            p_b = support_single[j]
            confidence = joint / p_a
            lift = confidence / p_b if p_b > 0 else float("nan")
            if not np.isfinite(lift) or lift < min_lift:
                continue
            conviction = (1 - p_b) / (1 - confidence) if confidence < 1 else float("inf")
            rows.append(
                {
                    "antecedente": antecedent,
                    "consecuente": consequent,
                    "soporte": joint,
                    "soporte_antecedente": p_a,
                    "soporte_consecuente": p_b,
                    "confianza": confidence,
                    "lift": lift,
                    "leverage": joint - p_a * p_b,
                    "conviccion": conviction,
                    "baskets": int(co_counts[i, j]),
                }
            )

    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows).sort_values("lift", ascending=False).reset_index(drop=True)
