"""Tests for the pure-numpy statistical toolkit.

Every assertion checks against a value derived analytically or from a textbook
worked example, not against whatever the implementation happens to return.
"""
import math

import numpy as np
import pandas as pd
import pytest

from src.services.inteligencia_comercial import stats


class TestDistributions:
    def test_normal_cdf_at_zero_is_half(self):
        assert stats.normal_cdf(0.0) == pytest.approx(0.5)

    def test_normal_cdf_matches_known_quantiles(self):
        assert stats.normal_cdf(1.959964) == pytest.approx(0.975, abs=1e-5)
        assert stats.normal_cdf(-1.644854) == pytest.approx(0.05, abs=1e-5)

    def test_two_sided_p_of_196_is_five_percent(self):
        assert stats.two_sided_p(1.959964) == pytest.approx(0.05, abs=1e-5)

    def test_two_sided_p_is_symmetric(self):
        assert stats.two_sided_p(2.3) == pytest.approx(stats.two_sided_p(-2.3))

    def test_chi2_sf_near_critical_values(self):
        # chi2 critical value at alpha=0.05 with 10 dof is 18.307
        assert stats.chi2_sf(18.307, 10) == pytest.approx(0.05, abs=0.005)
        # with 4 dof it is 9.488
        assert stats.chi2_sf(9.488, 4) == pytest.approx(0.05, abs=0.01)

    def test_chi2_sf_is_one_for_zero_statistic(self):
        assert stats.chi2_sf(0.0, 5) == 1.0

    def test_chi2_sf_returns_nan_for_zero_dof(self):
        assert math.isnan(stats.chi2_sf(3.0, 0))


class TestRobustStats:
    def test_mad_of_symmetric_sequence(self):
        # deviations from median 3 are [2,1,0,1,2] -> median 1
        assert stats.mad(np.array([1, 2, 3, 4, 5])) == pytest.approx(1.0)

    def test_robust_zscore_flags_the_outlier_only(self):
        data = np.array([10, 11, 10, 12, 11, 10, 90])
        z = stats.robust_zscore(data)
        assert abs(z[-1]) > 3
        assert np.all(np.abs(z[:-1]) < 3)

    def test_robust_zscore_survives_constant_series(self):
        z = stats.robust_zscore(np.array([5.0, 5.0, 5.0]))
        assert np.all(z == 0)

    def test_mad_ignores_nan(self):
        assert stats.mad(np.array([1, 2, 3, 4, 5, np.nan])) == pytest.approx(1.0)

    def test_coefficient_of_variation(self):
        data = np.array([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
        # mean 5, population std 2 -> CV 0.4
        assert stats.coefficient_of_variation(data) == pytest.approx(0.4)

    def test_coefficient_of_variation_nan_on_zero_mean(self):
        assert math.isnan(stats.coefficient_of_variation(np.array([-1.0, 1.0])))


class TestConcentration:
    def test_gini_of_perfect_equality_is_zero(self):
        assert stats.gini(np.ones(50)) == pytest.approx(0.0, abs=1e-9)

    def test_gini_of_total_inequality_approaches_one(self):
        values = np.zeros(100)
        values[0] = 1000.0
        assert stats.gini(values) == pytest.approx(0.99, abs=0.01)

    def test_gini_known_value(self):
        # For [1,2,3,4,5] the Gini is exactly 4/15
        assert stats.gini(np.array([1, 2, 3, 4, 5])) == pytest.approx(4 / 15)

    def test_hhi_of_monopoly_is_10000(self):
        assert stats.hhi(np.array([100.0])) == pytest.approx(10000.0)

    def test_hhi_of_four_equal_players(self):
        # four players at 25% each -> 4 * 625 = 2500
        assert stats.hhi(np.array([25.0, 25.0, 25.0, 25.0])) == pytest.approx(2500.0)

    def test_pareto_share_on_uniform_distribution(self):
        # perfectly even: 80% of entities are needed for 80% of value
        assert stats.pareto_share(np.ones(100)) == pytest.approx(0.8, abs=0.02)

    def test_pareto_share_on_concentrated_distribution(self):
        values = np.array([80.0] + [1.0] * 20)
        assert stats.pareto_share(values) < 0.15

    def test_lorenz_curve_endpoints_and_monotonicity(self):
        pop, cum = stats.lorenz_curve(np.array([1, 2, 3, 4, 100]))
        assert pop[0] == pytest.approx(0.0)
        assert pop[-1] == pytest.approx(1.0)
        assert cum[0] == pytest.approx(0.0)
        assert cum[-1] == pytest.approx(1.0)
        assert np.all(np.diff(cum) >= -1e-12)
        # a concentrated distribution bows below the diagonal
        assert np.all(cum <= pop + 1e-9)

    def test_gini_clips_negative_values(self):
        # credit notes must not produce a Gini outside [0,1]
        result = stats.gini(np.array([-50.0, 10.0, 20.0, 30.0]))
        assert 0.0 <= result <= 1.0


class TestQuantileScore:
    def test_ascending_gives_top_score_to_largest(self):
        scores = stats.quantile_score(pd.Series(range(100)), bins=5, ascending=True)
        assert scores.iloc[-1] == 5
        assert scores.iloc[0] == 1

    def test_descending_gives_top_score_to_smallest(self):
        # recency: fewest days since last purchase must score best
        scores = stats.quantile_score(pd.Series(range(100)), bins=5, ascending=False)
        assert scores.iloc[0] == 5
        assert scores.iloc[-1] == 1

    def test_all_scores_within_range(self):
        scores = stats.quantile_score(pd.Series(np.random.RandomState(0).rand(500)), bins=5)
        assert scores.min() >= 1
        assert scores.max() <= 5

    def test_handles_massive_ties_without_raising(self):
        # qcut would raise here; the rank-based scorer must not
        series = pd.Series([1] * 90 + [2] * 10)
        scores = stats.quantile_score(series, bins=5)
        assert scores.notna().all()
        assert scores.max() == 5

    def test_empty_series_returns_all_nan(self):
        scores = stats.quantile_score(pd.Series([np.nan, np.nan]), bins=5)
        assert scores.isna().all()


class TestProportionTest:
    def test_large_sample_deviation_is_significant(self):
        result = stats.proportion_ztest(successes=300, n=1000, baseline=0.20)
        assert result.rate == pytest.approx(0.30)
        assert result.z > 5
        assert result.significant

    def test_small_sample_same_rate_is_not_significant(self):
        result = stats.proportion_ztest(successes=3, n=10, baseline=0.20)
        assert result.rate == pytest.approx(0.30)
        assert not result.significant

    def test_zero_sample_returns_nan(self):
        result = stats.proportion_ztest(successes=0, n=0, baseline=0.2)
        assert math.isnan(result.z)
        assert not result.significant


class TestChiSquare:
    def test_independent_table_has_near_zero_statistic(self):
        table = pd.DataFrame(
            [[100, 200], [50, 100]], index=["a", "b"], columns=["x", "y"]
        )
        result = stats.chi_square_residuals(table)
        assert result.statistic == pytest.approx(0.0, abs=1e-9)
        assert result.p_value > 0.9

    def test_dependent_table_flags_the_right_cells(self):
        table = pd.DataFrame(
            [[90, 10], [10, 90]], index=["a", "b"], columns=["x", "y"]
        )
        result = stats.chi_square_residuals(table)
        assert result.statistic > 100
        assert result.p_value < 0.01
        assert result.residuals.loc["a", "x"] > 2
        assert result.residuals.loc["a", "y"] < -2

    def test_expected_preserves_marginals(self):
        table = pd.DataFrame([[10, 20, 30], [40, 50, 60]])
        result = stats.chi_square_residuals(table)
        assert result.expected.sum(axis=1).values == pytest.approx(table.sum(axis=1).values)
        assert result.expected.sum(axis=0).values == pytest.approx(table.sum(axis=0).values)

    def test_cramers_v_bounded(self):
        table = pd.DataFrame([[90, 10], [10, 90]])
        result = stats.chi_square_residuals(table)
        assert 0.0 <= result.cramers_v <= 1.0

    def test_empty_table_returns_nan(self):
        result = stats.chi_square_residuals(pd.DataFrame([[0, 0], [0, 0]]))
        assert math.isnan(result.statistic)


class TestOLS:
    def test_recovers_exact_line(self):
        x = np.arange(20, dtype=float)
        y = 3.0 * x + 7.0
        result = stats.ols(x, y)
        assert result.slope == pytest.approx(3.0)
        assert result.intercept == pytest.approx(7.0)
        assert result.r_squared == pytest.approx(1.0)

    def test_noisy_slope_confidence_interval_contains_truth(self):
        rng = np.random.RandomState(42)
        x = np.arange(200, dtype=float)
        y = 2.0 * x + 5.0 + rng.normal(0, 10, 200)
        result = stats.ols(x, y)
        low, high = result.ci95()
        assert low < 2.0 < high
        assert result.p_value < 0.001

    def test_no_relationship_is_not_significant(self):
        rng = np.random.RandomState(1)
        x = rng.normal(0, 1, 300)
        y = rng.normal(0, 1, 300)
        result = stats.ols(x, y)
        assert result.p_value > 0.05

    def test_constant_predictor_returns_nan(self):
        result = stats.ols(np.ones(10), np.arange(10, dtype=float))
        assert math.isnan(result.slope)

    def test_too_few_points_returns_nan(self):
        result = stats.ols([1.0, 2.0], [1.0, 2.0])
        assert math.isnan(result.slope)


class TestSeasonalDecompose:
    def _seasonal_series(self, periods=48, amplitude=0.3, slope=2.0):
        index = pd.date_range("2022-01-01", periods=periods, freq="MS")
        t = np.arange(periods)
        season = 1.0 + amplitude * np.sin(2 * np.pi * t / 12)
        return pd.Series((100 + slope * t) * season, index=index)

    def test_recovers_upward_trend(self):
        result = stats.seasonal_decompose(self._seasonal_series(), period=12)
        trend = result.trend.dropna()
        assert trend.iloc[-1] > trend.iloc[0]

    def test_multiplicative_indices_average_to_one(self):
        result = stats.seasonal_decompose(self._seasonal_series(), period=12)
        assert result.seasonal_indices.mean() == pytest.approx(1.0, abs=1e-6)

    def test_additive_indices_sum_to_zero(self):
        result = stats.seasonal_decompose(
            self._seasonal_series(), period=12, model="additive"
        )
        assert result.seasonal_indices.sum() == pytest.approx(0.0, abs=1e-6)

    def test_detects_strong_seasonality(self):
        result = stats.seasonal_decompose(self._seasonal_series(amplitude=0.4), period=12)
        assert result.seasonal_strength > 0.6

    def test_flat_series_has_weak_seasonality(self):
        index = pd.date_range("2022-01-01", periods=48, freq="MS")
        rng = np.random.RandomState(7)
        flat = pd.Series(100 + rng.normal(0, 1, 48), index=index)
        result = stats.seasonal_decompose(flat, period=12)
        assert result.seasonal_strength < 0.6

    def test_short_series_returns_nan_without_raising(self):
        index = pd.date_range("2025-01-01", periods=8, freq="MS")
        result = stats.seasonal_decompose(pd.Series(range(8), index=index), period=12)
        assert result.trend.isna().all()

    def test_peak_index_lands_on_the_peak_month(self):
        # sine peaks at t=3 (April) for a January start
        result = stats.seasonal_decompose(self._seasonal_series(), period=12)
        assert int(result.seasonal_indices.idxmax()) == 3


class TestHoltWinters:
    def _series(self, periods=48):
        index = pd.date_range("2022-01-01", periods=periods, freq="MS")
        t = np.arange(periods)
        return pd.Series(100 + 2 * t + 20 * np.sin(2 * np.pi * t / 12), index=index)

    def test_forecast_length_matches_horizon(self):
        result = stats.holt_winters_additive(self._series(), period=12, horizon=6)
        assert result.forecast.shape == (6,)
        assert result.lower.shape == (6,)
        assert result.upper.shape == (6,)

    def test_forecast_continues_the_trend(self):
        series = self._series()
        result = stats.holt_winters_additive(series, period=12, horizon=6)
        # the series grows 2/month; the 6-month-ahead point must exceed the level a year prior
        assert result.forecast[-1] > series.iloc[-12]

    def test_interval_widens_with_horizon(self):
        result = stats.holt_winters_additive(self._series(), period=12, horizon=6)
        widths = result.upper - result.lower
        assert np.all(np.diff(widths) > 0)

    def test_interval_brackets_the_point_forecast(self):
        result = stats.holt_winters_additive(self._series(), period=12, horizon=6)
        assert np.all(result.lower < result.forecast)
        assert np.all(result.forecast < result.upper)

    def test_fits_a_clean_series_tightly(self):
        result = stats.holt_winters_additive(self._series(60), period=12, horizon=3)
        assert result.mape < 10.0

    def test_short_series_degrades_gracefully(self):
        index = pd.date_range("2025-01-01", periods=10, freq="MS")
        result = stats.holt_winters_additive(
            pd.Series(range(10), index=index), period=12, horizon=3
        )
        assert np.isnan(result.forecast).all()
        assert "reason" in result.params

    def test_parameters_stay_in_the_searched_range(self):
        result = stats.holt_winters_additive(self._series(), period=12, horizon=3)
        for param in (result.alpha, result.beta, result.gamma):
            assert 0.1 <= param <= 0.9


class TestControlLimits:
    def test_detects_injected_spike(self):
        rng = np.random.RandomState(3)
        values = pd.Series(rng.normal(100, 5, 200))
        values.iloc[50] = 400
        result = stats.control_limits(values)
        assert result.breaches.iloc[50]
        assert result.breaches.sum() < 10

    def test_clean_series_has_few_breaches(self):
        rng = np.random.RandomState(11)
        result = stats.control_limits(pd.Series(rng.normal(100, 5, 500)))
        assert result.breaches.sum() <= 10

    def test_limits_straddle_the_center(self):
        result = stats.control_limits(pd.Series([10, 12, 11, 13, 12, 11]))
        assert result.lower < result.center < result.upper

    def test_outliers_do_not_inflate_the_band(self):
        # this is the whole point of using MAD instead of std
        clean = pd.Series([100.0] * 50 + [101.0] * 50)
        contaminated = pd.concat([clean, pd.Series([100000.0] * 5)], ignore_index=True)
        robust = stats.control_limits(contaminated)
        assert robust.breaches.tail(5).all()


class TestAssociationRules:
    def _baskets(self):
        """100 baskets with a planted A->B rule and a genuinely independent C.

        A in baskets 0-79            -> P(A) = 0.80
        B in baskets 0-71 and 80-83  -> P(B) = 0.76
        A and B together in 0-71     -> P(A,B) = 0.72
          confidence(A->B) = 0.72/0.80 = 0.90
          lift(A->B)       = 0.90/0.76 = 1.184
        C in every even basket       -> P(C) = 0.50
        A and C together in 0-78 even-> P(A,C) = 0.40 = P(A)P(C), exactly independent
          lift(A->C) = 1.00, leverage(A->C) = 0.00
        Z in baskets 80-99: filler so that EVERY basket carries at least one item.
          Without it those baskets never reach the incidence matrix, the basket
          count drops below 100 and every probability above is silently wrong.

        A must NOT appear in every basket: an item present everywhere has lift
        exactly 1 against everything, because it predicts nothing.
        """
        rows = []
        for i in range(100):
            if i < 80:
                rows.append((i, "A"))
            if i < 72 or 80 <= i < 84:
                rows.append((i, "B"))
            if i % 2 == 0:
                rows.append((i, "C"))
            if i >= 80:
                rows.append((i, "Z"))
        return pd.DataFrame(rows, columns=["ticket", "item"])

    def test_fixture_covers_every_basket(self):
        # guards the probabilities every other test in this class asserts on
        assert self._baskets()["ticket"].nunique() == 100

    def test_finds_the_planted_rule(self):
        rules = stats.association_rules(self._baskets(), "ticket", "item", min_support=0.05)
        ab = rules[(rules.antecedente == "A") & (rules.consecuente == "B")]
        assert not ab.empty
        assert ab.iloc[0]["confianza"] == pytest.approx(0.90)
        assert ab.iloc[0]["soporte"] == pytest.approx(0.72)

    def test_lift_above_one_for_associated_items(self):
        rules = stats.association_rules(self._baskets(), "ticket", "item", min_support=0.05)
        ab = rules[(rules.antecedente == "A") & (rules.consecuente == "B")]
        assert ab.iloc[0]["lift"] == pytest.approx(0.90 / 0.76, abs=1e-6)
        assert ab.iloc[0]["lift"] > 1.0

    def test_independent_item_has_lift_near_one(self):
        rules = stats.association_rules(
            self._baskets(), "ticket", "item", min_support=0.05, min_lift=0.0
        )
        ac = rules[(rules.antecedente == "A") & (rules.consecuente == "C")]
        assert ac.iloc[0]["lift"] == pytest.approx(1.0, abs=0.05)

    def test_leverage_is_zero_under_independence(self):
        rules = stats.association_rules(
            self._baskets(), "ticket", "item", min_support=0.05, min_lift=0.0
        )
        ac = rules[(rules.antecedente == "A") & (rules.consecuente == "C")]
        assert ac.iloc[0]["leverage"] == pytest.approx(0.0, abs=0.02)

    def test_min_support_filters_rare_pairs(self):
        rules = stats.association_rules(self._baskets(), "ticket", "item", min_support=0.95)
        assert rules.empty

    def test_no_self_rules(self):
        rules = stats.association_rules(
            self._baskets(), "ticket", "item", min_support=0.01, min_lift=0.0
        )
        assert (rules.antecedente != rules.consecuente).all()

    def test_empty_input_returns_empty_frame(self):
        rules = stats.association_rules(
            pd.DataFrame(columns=["ticket", "item"]), "ticket", "item"
        )
        assert rules.empty
        assert "lift" in rules.columns

    def test_duplicate_lines_do_not_double_count(self):
        # the same article on two invoice lines must count once for the basket
        base = self._baskets()
        doubled = pd.concat([base, base], ignore_index=True)
        rules_base = stats.association_rules(base, "ticket", "item", min_support=0.05)
        rules_doubled = stats.association_rules(doubled, "ticket", "item", min_support=0.05)
        assert rules_base["soporte"].tolist() == pytest.approx(rules_doubled["soporte"].tolist())
