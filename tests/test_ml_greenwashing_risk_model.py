"""Unit tests for ml/greenwashing_risk_model.py — pure logic, small in-memory DataFrames (no DB,
no live services), matching test_risk_agent.py's style for pure scoring logic.

Real-scale metrics (accuracy ~90.7%/macro-F1 ~0.908 against the full ~67k-row Morningstar export)
live in notebooks/02_ml_model_worked_example.ipynb, not here — these tests only check that the
training/scoring machinery is correct, not that it hits a particular real-world number.
"""

from __future__ import annotations

import random

import numpy as np
import pandas as pd
import pytest

from greenlux_sentinel.ml import greenwashing_risk_model as m


class TestBucketRating:
    @pytest.mark.parametrize(
        "rating,expected",
        [(1, "Low"), (2, "Low"), (3, "Medium"), (4, "High"), (5, "High")],
    )
    def test_buckets(self, rating, expected):
        assert m._bucket_rating(rating) == expected

    def test_none_and_nan_return_none(self):
        assert m._bucket_rating(None) is None
        assert m._bucket_rating(float("nan")) is None


def _synthetic_df(n_per_bucket: int = 20, seed: int = 0) -> pd.DataFrame:
    """An obviously-separable synthetic funds table: High-bucket funds get a high
    sector_technology / low involvement_thermal_coal signature, Low-bucket funds the reverse —
    strong enough that a correctly-wired classifier should beat a trivial baseline easily. One
    row per distinct fund_id/isin (group-split correctness is covered separately by
    TestGroups; this fixture doesn't need duplicate share classes)."""
    rng = random.Random(seed)
    rows = []
    signatures = {
        "Low": {"sector_technology": (2, 5), "sector_energy": (25, 35), "involvement_thermal_coal": (8, 15)},
        "Medium": {"sector_technology": (12, 18), "sector_energy": (10, 15), "involvement_thermal_coal": (3, 6)},
        "High": {"sector_technology": (30, 40), "sector_energy": (0, 3), "involvement_thermal_coal": (0, 1)},
    }
    rating_for_bucket = {"Low": 1, "Medium": 3, "High": 5}
    idx = 0
    for bucket, sig in signatures.items():
        for _ in range(n_per_bucket):
            idx += 1
            row = dict.fromkeys(m.FEATURE_COLUMNS, 0.0)
            for col, (lo, hi) in sig.items():
                row[col] = rng.uniform(lo, hi)
            row["fund_id"] = f"F{idx:04d}"
            row["isin"] = f"LU{idx:010d}"
            row["sustainability_rating"] = rating_for_bucket[bucket]
            rows.append(row)
    return pd.DataFrame(rows)


class TestBuildFeatureMatrix:
    def test_drops_rows_with_no_claimed_rating(self):
        df = _synthetic_df(n_per_bucket=3)
        df.loc[df.index[0], "sustainability_rating"] = np.nan
        X, y, _ = m.build_feature_matrix(df)
        assert len(X) == len(df) - 1
        assert len(y) == len(df) - 1

    def test_missing_flags_and_median_imputation_when_fitting(self):
        df = _synthetic_df(n_per_bucket=5)
        df.loc[df.index[0], "sector_healthcare"] = np.nan
        df.loc[df.index[1], "sector_healthcare"] = 10.0
        df.loc[df.index[2], "sector_healthcare"] = 20.0
        X, _, medians = m.build_feature_matrix(df)
        assert X.loc[df.index[0], "sector_healthcare__missing"] == 1
        assert X.loc[df.index[1], "sector_healthcare__missing"] == 0
        # imputed value equals the column's own (fit) median
        assert X.loc[df.index[0], "sector_healthcare"] == pytest.approx(medians["sector_healthcare"])

    def test_transform_only_uses_passed_medians_not_own_distribution(self):
        train_df = _synthetic_df(n_per_bucket=5, seed=1)
        _, _, train_medians = m.build_feature_matrix(train_df)

        test_df = _synthetic_df(n_per_bucket=1, seed=2)
        test_df["sector_healthcare"] = np.nan  # force imputation on every row
        X_test, _, medians_used = m.build_feature_matrix(test_df, medians=train_medians)

        assert medians_used is train_medians
        assert (X_test["sector_healthcare"] == train_medians["sector_healthcare"]).all()


class TestGroups:
    def test_falls_back_to_fund_id_when_isin_missing(self):
        df = pd.DataFrame({"fund_id": ["F1", "F2"], "isin": ["LU0001", None]})
        groups = m._groups(df)
        assert list(groups) == ["LU0001", "F2"]


class TestTrain:
    def test_raises_with_fewer_than_two_funds(self):
        df = _synthetic_df(n_per_bucket=1).iloc[:1]
        with pytest.raises(ValueError, match="at least 2 distinct funds"):
            m.train(df)

    def test_returns_fitted_model_with_expected_metric_keys(self):
        df = _synthetic_df(n_per_bucket=20, seed=3)
        result = m.train(df, test_size=0.3, random_state=42)

        assert set(result.metrics) == {
            "n_train", "n_test", "accuracy", "macro_f1",
            "confusion_matrix", "confusion_matrix_labels", "classification_report",
        }
        assert result.metrics["n_train"] + result.metrics["n_test"] == len(df)
        assert set(result.tier_thresholds) == {"medium", "high"}

    def test_beats_trivial_baseline_on_separable_data(self):
        df = _synthetic_df(n_per_bucket=25, seed=4)
        result = m.train(df, test_size=0.3, random_state=42)
        # 3 balanced buckets -> a most-frequent-class baseline scores ~1/3; this fixture's signal
        # is strong enough that a correctly-wired model should clear that easily.
        assert result.metrics["accuracy"] > 0.6


class TestScore:
    @pytest.fixture
    def trained(self):
        return m.train(_synthetic_df(n_per_bucket=25, seed=5), test_size=0.3, random_state=42)

    def test_anomaly_score_in_bounds_and_tier_is_valid(self, trained):
        row = dict.fromkeys(m.FEATURE_COLUMNS, 0.0)
        row.update({"sector_technology": 35.0, "sector_energy": 1.0, "involvement_thermal_coal": 0.2,
                     "sustainability_rating": 5})
        out = m.score(trained, row)
        assert 0.0 <= out["composition_anomaly_score"] <= 100.0
        assert out["composition_anomaly_tier"] in ("Low", "Medium", "High")
        assert out["predicted_rating_bucket"] in m.RATING_BUCKETS
        assert out["actual_rating_bucket"] == "High"
        assert out["caveat"] == m.CAVEAT

    def test_raises_when_no_claimed_rating(self, trained):
        row = dict.fromkeys(m.FEATURE_COLUMNS, 0.0)
        row["sustainability_rating"] = None
        with pytest.raises(ValueError, match="no claimed sustainability_rating"):
            m.score(trained, row)


class TestSaveLoadModel:
    def test_round_trip(self, tmp_path):
        result = m.train(_synthetic_df(n_per_bucket=15, seed=6), test_size=0.3, random_state=42)
        path = tmp_path / "model.joblib"

        m.save_model(result, path)
        loaded = m.load_model(path)

        assert loaded.model_version == result.model_version
        assert loaded.tier_thresholds == result.tier_thresholds
        row = dict.fromkeys(m.FEATURE_COLUMNS, 0.0)
        row["sustainability_rating"] = 3
        assert m.score(loaded, row)["predicted_rating_bucket"] in m.RATING_BUCKETS
