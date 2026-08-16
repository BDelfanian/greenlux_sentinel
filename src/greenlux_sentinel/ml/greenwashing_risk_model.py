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
percentages (etl/load_funds_postgres.COMPOSITION_COLUMNS) — plus (Phase 9d) three train-fold-only,
leakage-safe `category`-derived features (CATEGORY_RATE_COLUMNS). Deliberately excludes
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

Phase 9d — category encoding. `category` (295 distinct Morningstar categories) was originally left
out of v1 (docs/DATA.md) — too high-cardinality for naive one-hot, and target-mean encoding risks
leakage unless done carefully. Added here as three derived features, `category_low_rate`/
`category_medium_rate`/`category_high_rate`: for each category, the (Laplace-smoothed, blended
toward the global training-set distribution) empirical rate of Low/Medium/High claimed ratings
among funds in that SAME category, computed on the train fold only and applied unchanged to the
test fold and at score() time — exactly the same fit-on-train/apply-to-test discipline
`build_feature_matrix()` already used for median imputation, extended to cover this too (see
`FeatureFitStats`). A fund in a rare or unseen category falls back to the global training-set
rate rather than a category-specific rate estimated from too few rows to trust.
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

CATEGORY_RATE_COLUMNS: list[str] = ["category_low_rate", "category_medium_rate", "category_high_rate"]

# All model input columns, in the order concatenated onto the feature matrix -- objective
# composition + per-column missingness flags + category-derived rates. Callers building a Postgres
# SELECT (train_greenwashing_risk_model.py, ml_risk_agent.py) need "category" fetched alongside
# FEATURE_COLUMNS for build_feature_matrix() to work; it is deliberately not itself a member of
# FEATURE_COLUMNS/ALL_MODEL_COLUMNS since it's consumed as a lookup key, not a numeric feature.
ALL_MODEL_COLUMNS: list[str] = FEATURE_COLUMNS + [f"{c}__missing" for c in FEATURE_COLUMNS] + CATEGORY_RATE_COLUMNS

RATING_BUCKETS = ("Low", "Medium", "High")

MODEL_VERSION = "tier1-composition-anomaly-v2"

MODEL_ARTIFACT_PATH = Path(__file__).parent / "artifacts" / "greenwashing_rating_classifier.joblib"

CAVEAT = (
    "This score is a data-driven proxy indicating whether a fund's claimed Morningstar "
    "Sustainability Rating looks statistically typical for its objective portfolio composition "
    "(sector/asset-class/credit-quality/controversial-business-involvement mix, and how its "
    "Morningstar category's ratings typically run), relative to the broader fund population. It "
    "is not a determination of greenwashing, SFDR non-compliance, or any other regulatory/legal "
    "finding, and it is a different, coarser signal from the Tier 2 holdings-based Greenwashing "
    "Risk Score (agents/risk_agent.py) — the two need not agree."
)

_CATEGORY_MISSING = "__missing_category__"
_CATEGORY_SMOOTHING = 5.0  # weight (in "pseudo-funds") given to the global rate for a rare/unseen
# category -- a standard Laplace/additive-smoothing constant, not fit-tuned; large enough that a
# category with a handful of funds doesn't swing to an overconfident 0%/100% rate, small enough
# that a well-populated category (thousands of funds) is barely pulled off its own real rate.


def _bucket_rating(rating: float | None) -> str | None:
    """1-5 Morningstar globes -> Low(1-2)/Medium(3)/High(4-5). None/NaN -> None (no claim)."""
    if rating is None or pd.isna(rating):
        return None
    if rating <= 2:
        return "Low"
    if rating == 3:
        return "Medium"
    return "High"


def _fit_category_rates(category: pd.Series, y: pd.Series) -> dict[str, dict[str, float]]:
    """Train-fold-only, Laplace-smoothed per-category class-rate table (see module docstring's
    Phase 9d section for why). Returns {"__global__": {...}, "<category>": {...}, ...}, each value
    a dict of RATING_BUCKETS -> probability summing to 1.0."""
    global_counts = y.value_counts()
    global_total = len(y)
    global_rates = {b: global_counts.get(b, 0) / global_total for b in RATING_BUCKETS}

    table: dict[str, dict[str, float]] = {"__global__": global_rates}
    for cat, sub_y in y.groupby(category):
        n = len(sub_y)
        counts = sub_y.value_counts()
        table[cat] = {
            b: (counts.get(b, 0) + _CATEGORY_SMOOTHING * global_rates[b]) / (n + _CATEGORY_SMOOTHING)
            for b in RATING_BUCKETS
        }
    return table


def _apply_category_rates(category: pd.Series, table: dict[str, dict[str, float]]) -> pd.DataFrame:
    """Look up each row's category in `table` (fit on a train fold via _fit_category_rates),
    falling back to the global training-set rate for a category never seen during fit."""
    if category.empty:
        # pd.DataFrame([], index=...) has zero columns, so selecting RATING_BUCKETS from it would
        # raise KeyError even though there are (correctly) zero rows -- e.g. every row in the
        # input lacked a claimed rating, so build_feature_matrix already filtered df/category down
        # to nothing before this runs. Return the equivalent empty-but-column-shaped frame instead.
        return pd.DataFrame(columns=CATEGORY_RATE_COLUMNS, index=category.index, dtype=float)
    global_rates = table["__global__"]
    rows = [table.get(cat, global_rates) for cat in category]
    rates_df = pd.DataFrame(rows, index=category.index)[list(RATING_BUCKETS)]
    return rates_df.rename(columns=dict(zip(RATING_BUCKETS, CATEGORY_RATE_COLUMNS, strict=True)))


@dataclass
class FeatureFitStats:
    """Everything build_feature_matrix() fits on a train fold and must apply, unchanged, to a
    test fold or a single fund at score() time -- bundled together so callers thread one object
    instead of a growing list of positional statistics."""

    medians: pd.Series
    category_rates: dict[str, dict[str, float]]


def build_feature_matrix(
    df: pd.DataFrame, fit_stats: FeatureFitStats | None = None
) -> tuple[pd.DataFrame, pd.Series, FeatureFitStats]:
    """Build (X, y_bucket, fit_stats_used) from a funds-shaped DataFrame.

    Rows with no claimed sustainability_rating (nothing to compare against) are dropped. Missing
    feature values are median-imputed with a same-named `<col>__missing` indicator flag added per
    column — missingness here is structural (e.g. credit_* columns are absent for equity funds,
    sector_* absent for bond funds — see docs/DATA.md), not random, so the flags carry real signal.
    `category` (missing -> a sentinel bucket, not dropped) is encoded as three per-category
    claimed-rating rate features (CATEGORY_RATE_COLUMNS, Phase 9d) rather than one-hot, since it
    has 295 distinct values.

    Pass `fit_stats=None` to fit medians + category rates from `df` itself (training); pass a
    previously-fit `FeatureFitStats` to apply them unchanged (evaluating a held-out test set, or
    scoring a single fund) — so a test/production row is never imputed/encoded using its own (or
    the test set's) statistics.
    """
    y = df["sustainability_rating"].map(_bucket_rating)
    keep = y.notna()
    df = df.loc[keep]
    y = y.loc[keep]

    feat = df[FEATURE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    missing_flags = feat.isna().astype(int).add_suffix("__missing")
    category = df["category"].fillna(_CATEGORY_MISSING) if "category" in df.columns else pd.Series(
        _CATEGORY_MISSING, index=df.index
    )

    if fit_stats is None:
        fit_stats = FeatureFitStats(medians=feat.median(), category_rates=_fit_category_rates(category, y))

    imputed = feat.fillna(fit_stats.medians)
    category_features = _apply_category_rates(category, fit_stats.category_rates)

    X = pd.concat([imputed, missing_flags, category_features], axis=1)
    return X, y, fit_stats


def _groups(df: pd.DataFrame) -> pd.Series:
    """Group key for GroupShuffleSplit — isin (shared across share classes), falling back to
    fund_id where isin is null. Prevents near-duplicate share-class rows of the same underlying
    fund from leaking across the train/test split (see docs/DATA.md for the measured ~6% impact)."""
    return df["isin"].fillna(df["fund_id"])


@dataclass
class TrainResult:
    model: RandomForestClassifier
    fit_stats: FeatureFitStats
    tier_thresholds: dict[str, float]
    metrics: dict[str, Any]
    feature_columns: list[str] = field(default_factory=lambda: list(ALL_MODEL_COLUMNS))
    model_version: str = MODEL_VERSION
    trained_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def train(df: pd.DataFrame, test_size: float = 0.2, random_state: int = 42) -> TrainResult:
    """Group-split train + evaluate the classifier on a funds-shaped DataFrame (the output of
    etl.load_funds_postgres.transform(), or an equivalent live-Postgres SELECT that also includes
    `category`).

    Uses GroupShuffleSplit grouped by ISIN, not a naive row split — see _groups()'s docstring and
    docs/DATA.md for the measured leakage this avoids. Returns a TrainResult with the fitted model,
    the fit statistics (medians + category rates, fit on the train fold only, applied to test — no
    leakage), quantile anomaly-tier thresholds, and a full metrics report (accuracy, macro-F1,
    per-class precision/recall, confusion matrix) — not just one headline number.
    """
    y_all = df["sustainability_rating"].map(_bucket_rating)
    scorable = df.loc[y_all.notna()]
    if scorable["isin"].fillna(scorable["fund_id"]).nunique() < 2:
        raise ValueError("need at least 2 distinct funds (by isin/fund_id) with a claimed rating to train")

    groups = _groups(scorable)
    splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
    train_idx, test_idx = next(splitter.split(scorable, groups=groups))
    train_df, test_df = scorable.iloc[train_idx], scorable.iloc[test_idx]

    X_train, y_train, fit_stats = build_feature_matrix(train_df)
    X_test, y_test, _ = build_feature_matrix(test_df, fit_stats=fit_stats)

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
    # population (train + test, imputed/encoded with the training fit_stats) — a fixed business
    # rule computed once at train time, not a second trained model.
    X_all, y_actual, _ = build_feature_matrix(scorable, fit_stats=fit_stats)
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

    return TrainResult(model=clf, fit_stats=fit_stats, tier_thresholds=tier_thresholds, metrics=metrics)


def score(result: TrainResult, feature_row: dict[str, Any]) -> dict[str, Any]:
    """Score one fund. `feature_row` must include `sustainability_rating` (the real claimed
    rating, to know the actual bucket), `category`, plus the FEATURE_COLUMNS. Returns predicted
    vs. actual bucket, the composition_anomaly_score (0-100, higher = more atypical for the
    claimed tier), and its quantile-bucketed tier."""
    row_df = pd.DataFrame([feature_row])
    X, y, _ = build_feature_matrix(row_df, fit_stats=result.fit_stats)
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
