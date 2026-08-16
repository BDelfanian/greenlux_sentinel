"""Tier 1 composition-anomaly model — a classical, trained ML component (Phase 9).

This is a DIFFERENT signal from `agents/risk_agent.py`'s Tier 2 `compute_gap()`, not a
replacement for it, and the two need not agree — see docs/DATA.md's "Tier 1 composition-anomaly
model" section for a worked example (the same fund) where they don't.

    Tier 2 (risk_agent.compute_gap): claimed sustainability rating vs. the REAL, security-level
    holdings-implied ESG score. Only computable for the 4 funds with real Tier 2 holdings data —
    the most grounded signal available, but tiny in coverage.

    Tier 1 (this module): claimed sustainability rating vs. what a fund with this OBJECTIVE
    portfolio composition typically claims, learned from the full ~41k-fund population that has
    both a claim and composition data. Broad coverage, but a coarser, population-relative signal —
    it can only say "this claim looks atypical for this kind of portfolio," not "this claim is
    inconsistent with this fund's actual constituent-level ESG profile."

Model: a single `RandomForestClassifier` predicting each fund's own REAL, existing claimed
`sustainability_rating` bucket (Low 1-2 / Medium 3 / High 4-5 globes) from FEATURE_COLUMNS —
objective sector/asset-class/market-cap/credit-quality/controversial-business-involvement
percentages (etl/load_funds_postgres.COMPOSITION_COLUMNS). Deliberately excludes
environmental_score/social_score/governance_score/sustainability_score: schema.sql comments those
as claimed-side, same signal as the target, so including them would make the prediction circular.

Why not a fabricated "greenwashing" label: no free dataset carries a real SFDR/greenwashing label
(see docs/DATA.md#ground-truth-methodology) — this model predicts a REAL Morningstar field, not an
invented one. Why not a second model on the first model's own residual/quantile-bins: considered
and rejected as near-tautological (same features, target derived from the first model's own
output) — the shipped model's own `predict_proba` already gives the anomaly signal directly:
`composition_anomaly_score = (1 - P(actual claimed bucket)) * 100`.

CAVEAT (same framing as risk_agent.CAVEAT): this is a data-driven proxy indicator of whether a
fund's claimed sustainability rating looks statistically typical for its objective portfolio
composition — not a determination of greenwashing, SFDR non-compliance, or any other regulatory
finding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.model_selection import GroupShuffleSplit

from greenlux_sentinel.etl.load_funds_postgres import COMPOSITION_COLUMNS

FEATURE_COLUMNS: list[str] = COMPOSITION_COLUMNS

RATING_BUCKETS = ("Low", "Medium", "High")

MODEL_VERSION = "tier1-composition-anomaly-v1"

MODEL_ARTIFACT_PATH = Path(__file__).parent / "artifacts" / "greenwashing_rating_classifier.joblib"

CAVEAT = (
    "This score is a data-driven proxy indicating whether a fund's claimed Morningstar "
    "Sustainability Rating looks statistically typical for its objective portfolio composition "
    "(sector/asset-class/credit-quality/controversial-business-involvement mix), relative to the "
    "broader fund population. It is not a determination of greenwashing, SFDR non-compliance, or "
    "any other regulatory/legal finding, and it is a different, coarser signal from the Tier 2 "
    "holdings-based Greenwashing Risk Score (agents/risk_agent.py) — the two need not agree."
)


def _bucket_rating(rating: float | None) -> str | None:
    """1-5 Morningstar globes -> Low(1-2)/Medium(3)/High(4-5). None/NaN -> None (no claim)."""
    if rating is None or pd.isna(rating):
        return None
    if rating <= 2:
        return "Low"
    if rating == 3:
        return "Medium"
    return "High"


def build_feature_matrix(
    df: pd.DataFrame, medians: pd.Series | None = None
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Build (X, y_bucket, medians_used) from a funds-shaped DataFrame.

    Rows with no claimed sustainability_rating (nothing to compare against) are dropped. Missing
    feature values are median-imputed with a same-named `<col>__missing` indicator flag added per
    column — missingness here is structural (e.g. credit_* columns are absent for equity funds,
    sector_* absent for bond funds — see docs/DATA.md), not random, so the flags carry real signal.

    Pass `medians=None` to fit medians from `df` itself (training); pass a previously-fit `medians`
    Series to apply them unchanged (evaluating a held-out test set, or scoring a single fund) — so
    a test/production row is never imputed using its own (or the test set's) statistics.
    """
    y = df["sustainability_rating"].map(_bucket_rating)
    keep = y.notna()
    df = df.loc[keep]
    y = y.loc[keep]

    feat = df[FEATURE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    missing_flags = feat.isna().astype(int).add_suffix("__missing")

    if medians is None:
        medians = feat.median()
    imputed = feat.fillna(medians)

    X = pd.concat([imputed, missing_flags], axis=1)
    return X, y, medians


def _groups(df: pd.DataFrame) -> pd.Series:
    """Group key for GroupShuffleSplit — isin (shared across share classes), falling back to
    fund_id where isin is null. Prevents near-duplicate share-class rows of the same underlying
    fund from leaking across the train/test split (see docs/DATA.md for the measured ~6% impact)."""
    return df["isin"].fillna(df["fund_id"])


@dataclass
class TrainResult:
    model: RandomForestClassifier
    medians: pd.Series
    tier_thresholds: dict[str, float]
    metrics: dict[str, Any]
    feature_columns: list[str] = field(default_factory=lambda: list(FEATURE_COLUMNS))
    model_version: str = MODEL_VERSION
    trained_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def train(df: pd.DataFrame, test_size: float = 0.2, random_state: int = 42) -> TrainResult:
    """Group-split train + evaluate the classifier on a funds-shaped DataFrame (the output of
    etl.load_funds_postgres.transform(), or an equivalent live-Postgres SELECT).

    Uses GroupShuffleSplit grouped by ISIN, not a naive row split — see _groups()'s docstring and
    docs/DATA.md for the measured leakage this avoids. Returns a TrainResult with the fitted model,
    the imputation medians (fit on the train fold only, applied to test — no leakage), quantile
    anomaly-tier thresholds, and a full metrics report (accuracy, macro-F1, per-class
    precision/recall, confusion matrix) — not just one headline number.
    """
    y_all = df["sustainability_rating"].map(_bucket_rating)
    scorable = df.loc[y_all.notna()]
    if scorable["isin"].fillna(scorable["fund_id"]).nunique() < 2:
        raise ValueError("need at least 2 distinct funds (by isin/fund_id) with a claimed rating to train")

    groups = _groups(scorable)
    splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
    train_idx, test_idx = next(splitter.split(scorable, groups=groups))
    train_df, test_df = scorable.iloc[train_idx], scorable.iloc[test_idx]

    X_train, y_train, medians = build_feature_matrix(train_df)
    X_test, y_test, _ = build_feature_matrix(test_df, medians=medians)

    clf = RandomForestClassifier(
        n_estimators=300,
        max_depth=12,
        min_samples_leaf=5,
        class_weight="balanced",
        random_state=random_state,
    )
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    metrics = {
        "n_train": len(X_train),
        "n_test": len(X_test),
        "accuracy": float((y_pred == y_test).mean()),
        "macro_f1": float(f1_score(y_test, y_pred, average="macro", labels=list(RATING_BUCKETS))),
        "confusion_matrix": confusion_matrix(y_test, y_pred, labels=list(RATING_BUCKETS)).tolist(),
        "confusion_matrix_labels": list(RATING_BUCKETS),
        "classification_report": classification_report(
            y_test, y_pred, labels=list(RATING_BUCKETS), output_dict=True, zero_division=0
        ),
    }

    # Anomaly-tier thresholds: quantiles of (1 - P(actual bucket)) over the full scorable
    # population (train + test, imputed with the training medians) — a fixed business rule
    # computed once at train time, not a second trained model.
    X_all, y_actual, _ = build_feature_matrix(scorable, medians=medians)
    proba = clf.predict_proba(X_all)
    class_index = {c: i for i, c in enumerate(clf.classes_)}
    p_actual = pd.Series(
        [proba[i, class_index[actual]] for i, actual in enumerate(y_actual)], index=y_actual.index
    )
    anomaly_scores = (1 - p_actual) * 100
    tier_thresholds = {
        "medium": float(anomaly_scores.quantile(0.60)),
        "high": float(anomaly_scores.quantile(0.90)),
    }

    return TrainResult(
        model=clf, medians=medians, tier_thresholds=tier_thresholds, metrics=metrics
    )


def score(result: TrainResult, feature_row: dict[str, Any]) -> dict[str, Any]:
    """Score one fund. `feature_row` must include `sustainability_rating` (the real claimed
    rating, to know the actual bucket) plus the FEATURE_COLUMNS. Returns predicted vs. actual
    bucket, the composition_anomaly_score (0-100, higher = more atypical for the claimed tier),
    and its quantile-bucketed tier."""
    row_df = pd.DataFrame([feature_row])
    X, y, _ = build_feature_matrix(row_df, medians=result.medians)
    if X.empty:
        raise ValueError("feature_row has no claimed sustainability_rating to score against")

    actual_bucket = y.iloc[0]
    proba = result.model.predict_proba(X)[0]
    class_index = {c: i for i, c in enumerate(result.model.classes_)}
    predicted_bucket = result.model.classes_[proba.argmax()]
    p_actual = proba[class_index[actual_bucket]]
    anomaly_score = round((1 - p_actual) * 100, 2)

    if anomaly_score <= result.tier_thresholds["medium"]:
        tier = "Low"
    elif anomaly_score <= result.tier_thresholds["high"]:
        tier = "Medium"
    else:
        tier = "High"

    return {
        "predicted_rating_bucket": predicted_bucket,
        "actual_rating_bucket": actual_bucket,
        "composition_anomaly_score": anomaly_score,
        "composition_anomaly_tier": tier,
        "model_version": result.model_version,
        "caveat": CAVEAT,
    }


def save_model(result: TrainResult, path: Path = MODEL_ARTIFACT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(result, path, compress=3)


def load_model(path: Path = MODEL_ARTIFACT_PATH) -> TrainResult:
    return joblib.load(path)
