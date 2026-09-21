"""Product matrix: what we forecast, when, and how far.

One workflow per (target x gate x span). Gates see different information,
so they are different models; spans need different max-lead horizons, so
day-ahead and 10-day are different models too.
"""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from openstef_core.types import LeadTime, Q
from openstef_models.integrations.mlflow import MLFlowStorage
from openstef_models.presets.forecasting_workflow import LocationConfig
from pydantic_extra_types.coordinate import Coordinate, Latitude, Longitude
from pydantic_extra_types.country import CountryAlpha2

# Gate wall-clock labels, Berlin. Mirrors core/config/availability.GATES.
GATE_0530 = "0530"
GATE_1130 = "1130"

# Forecast targets: SDAC price, actual load, actual generation (a few types
# plus the total). Add more smard/entsoe columns here to grow the matrix.
TARGETS = (
    "price_sdac_seq1_eur_mwh",
    "load_actual_mw",
    "gen_actual_total_mwh",
    "gen_actual_wind_onshore_mwh",
    "gen_actual_wind_offshore_mwh",
    "gen_actual_photovoltaics_mwh",
)

# smard actual type columns summed into gen_actual_total_mwh (see dataset.py).
GEN_TOTAL_COLUMNS = (
    "gen_actual_biomass_mwh",
    "gen_actual_hydropower_mwh",
    "gen_actual_wind_offshore_mwh",
    "gen_actual_wind_onshore_mwh",
    "gen_actual_photovoltaics_mwh",
    "gen_actual_other_renewable_mwh",
    "gen_actual_nuclear_mwh",
    "gen_actual_lignite_mwh",
    "gen_actual_hard_coal_mwh",
    "gen_actual_fossil_gas_mwh",
    "gen_actual_hydro_pumped_storage_mwh",
    "gen_actual_other_conventional_mwh",
)

QUANTILES = [Q(0.1), Q(0.5), Q(0.9)]

# Spans: day-ahead predicts D+1 only, 10-day predicts D+1..D+10.
SPAN_D1 = "d1"
SPAN_D10 = "d10"
SPANS = (SPAN_D1, SPAN_D10)

# Leakage doctrine: training sees flat history (every column valued), but
# at the gate many cells are still NaN (unpublished). So:
#   1. horizons = the span's MAXIMUM lead. LagsAdder keeps only older lags,
#      hence every kept lag is genuinely known for every predicted row.
#      (Minimum-lead horizons train on lags that are NaN at predict time
#      -> flat, biased forecasts.)
#   2. A published-curve column may enter only if known at the gate for
#      EVERY predicted row. The rest are excluded via selected_features.
HORIZONS = {
    # 0530: D+1 23:45 is 42h15m out; D+11 00:00 is 258h30m out.
    (GATE_0530, SPAN_D1): [LeadTime(timedelta(hours=42, minutes=30))],
    (GATE_0530, SPAN_D10): [LeadTime(timedelta(hours=258, minutes=30))],
    # 1130: D+1 23:45 is 36h15m out; D+11 00:00 is 252h30m out.
    (GATE_1130, SPAN_D1): [LeadTime(timedelta(hours=36, minutes=30))],
    (GATE_1130, SPAN_D10): [LeadTime(timedelta(hours=252, minutes=30))],
}

# 48h covers D+1 plus spill from both gates; 11d covers D+1..D+10 + DST.
PREDICT_LENGTH = {SPAN_D1: timedelta(hours=48), SPAN_D10: timedelta(days=11)}

# Day-ahead curves for target day T, published before T. Same-ts values for
# future targets are NaN at the gate but valued in flat training history.
PUBLISHED_CURVES = (
    "price_exaa_eur_mwh",
    "price_sdac_seq1_eur_mwh",
    "price_sdac_seq2_eur_mwh",
    "load_forecast_mw",
    "gen_forecast_total_mw",
    "solar_forecast_mw",
    "wind_offshore_forecast_mw",
    "wind_onshore_forecast_mw",
    "load_forecast_mwh",
    "gen_forecast_total_mwh",
    "gen_forecast_photovoltaics_and_wind_mwh",
    "gen_forecast_photovoltaics_mwh",
    "gen_forecast_other_mwh",
    "gen_forecast_wind_offshore_mwh",
    "gen_forecast_wind_onshore_mwh",
)

# (gate, span) -> published curves known at the gate for every predicted row.
# Only the 1130 day-ahead product sees EXAA + the ENTSO-E load forecast;
# everything else is published after the gate (or after D+1 for long rows).
KNOWN_AT_GATE = {
    (GATE_1130, SPAN_D1): ("price_exaa_eur_mwh", "load_forecast_mw"),
}


# Measured actuals. Same-timestamp values from the sister source are never
# valid features (unknown at the gate for future rows). Keep these lists in
# sync with the versioned parts: dataset.py raises on unmapped clean columns,
# which is the cue to update them. The target itself is always kept.
ENTSOE_ACTUAL_COLUMNS = (
    "load_actual_mw",
    "gen_actual_B01_mw",
    "gen_actual_B02_mw",
    "gen_actual_B03_mw",
    "gen_actual_B04_mw",
    "gen_actual_B05_mw",
    "gen_actual_B06_mw",
    "gen_actual_B09_mw",
    "gen_actual_B10_inBZ_mw",
    "gen_actual_B10_outBZ_mw",
    "gen_actual_B11_mw",
    "gen_actual_B12_mw",
    "gen_actual_B15_mw",
    "gen_actual_B16_mw",
    "gen_actual_B17_mw",
    "gen_actual_B18_mw",
    "gen_actual_B19_mw",
    "gen_actual_B20_mw",
)
SMARD_ACTUAL_COLUMNS = (
    "load_actual_mwh",
    "gen_actual_biomass_mwh",
    "gen_actual_hydropower_mwh",
    "gen_actual_wind_offshore_mwh",
    "gen_actual_wind_onshore_mwh",
    "gen_actual_photovoltaics_mwh",
    "gen_actual_other_renewable_mwh",
    "gen_actual_nuclear_mwh",
    "gen_actual_lignite_mwh",
    "gen_actual_hard_coal_mwh",
    "gen_actual_fossil_gas_mwh",
    "gen_actual_hydro_pumped_storage_mwh",
    "gen_actual_other_conventional_mwh",
    "gen_actual_total_mwh",
)


def feature_exclude(target: str, gate: str, span: str) -> list[str]:
    """Columns unknown at the gate for predicted rows (see doctrine above).

    Published curves carry future values in training but are NaN at the
    gate (except KNOWN_AT_GATE); sister-source actuals teach the trees an
    identity mapping that collapses at predict time. What remains: the
    target's own lags, weather, calendar, known curves.
    """
    known = KNOWN_AT_GATE.get((gate, span), ())
    curves = [c for c in PUBLISHED_CURVES if c != target and c not in known]
    actuals = [c for c in ENTSOE_ACTUAL_COLUMNS + SMARD_ACTUAL_COLUMNS if c != target]
    return curves + actuals


# Reference location for the preset's pvlib-derived features (daylight,
# clear-sky). The 125 per-location columns stay raw features for the trees;
# switch to a national mean if the backtest says resolution matters.
WEATHER_REFERENCE_LOCATION = "frankfurt"

LOCATION = LocationConfig(
    name="DE-LU",
    coordinate=Coordinate(
        latitude=Latitude(Decimal("51.16")), longitude=Longitude(Decimal("10.45"))
    ),
    country_code=CountryAlpha2("DE"),
)

# History available at prediction time (also the LagsAdder window).
PREDICT_CONTEXT = timedelta(days=14)
# Below this completeness the primary refuses and the fallback chain runs.
COMPLETENESS_THRESHOLD = 0.5

# Backtest replay mirrors operations: daily gate, weekly retrain.
TRAINING_CONTEXT = timedelta(days=90)
TRAIN_INTERVAL = timedelta(days=7)
PREDICT_CONTEXT_MIN_COVERAGE = 0.5
TRAINING_CONTEXT_MIN_COVERAGE = 0.5

# XGBoost threads per fit (the preset leaves n_jobs=1).
N_JOBS = 4

# Calibrate quantiles post-hoc (IsotonicQuantileCalibrator, doc recipe).
# Fixes the systematically narrow intervals raw pinball models emit.
CALIBRATE_QUANTILES = True

# Flatline detection per target. Renewables genuinely sit at exact zero for
# long stretches (PV nights, dead-calm wind), so they get a longer leash
# plus non-zero stuck-meter detection; other series never flatline for real.
FLATLINER_THRESHOLD = timedelta(hours=24)
FLATLINER_THRESHOLDS = {
    "gen_actual_photovoltaics_mwh": timedelta(hours=48),
    "gen_actual_wind_onshore_mwh": timedelta(hours=48),
    "gen_actual_wind_offshore_mwh": timedelta(hours=48),
}
DETECT_NON_ZERO_FLATLINER = (
    "gen_actual_photovoltaics_mwh",
    "gen_actual_wind_onshore_mwh",
    "gen_actual_wind_offshore_mwh",
)

# Tuning minimizes rCRPS over the full quantile set. Note the registry's
# model-selection still scores median R2 (preset default) — tuned for
# distribution shape, promoted on point skill.
TUNE_METRIC = "rCRPS"
TUNE_DIRECTION = "minimize"


def tuning_hyperparams():
    """XGBoost search space: ranges enable tuning, fields keep defaults."""
    from openstef_core.mixins.param_ranges import FloatRange, IntRange
    from openstef_models.models.forecasting.xgboost_forecaster import XGBoostHyperParams

    return XGBoostHyperParams(
        n_estimators=IntRange(50, 300, tune=True),
        max_depth=IntRange(3, 10, tune=True),
        learning_rate=FloatRange(0.05, 0.5, log=True, tune=True),
        min_child_weight=FloatRange(1.0, 10.0, tune=True),
        subsample=FloatRange(0.7, 1.0, tune=True),
        colsample_bytree=FloatRange(0.7, 1.0, tune=True),
        reg_lambda=FloatRange(1e-3, 10.0, log=True, tune=True),
    )


MLFLOW_DIR = Path("data/mlflow")
TUNING_DIR = Path("data/tuning")
BACKTEST_DIR = Path("data/backtests")
FORECAST_DIR = Path("data/forecasts")


def weather_ref(field: str) -> str:
    """Reference-location column for a weather field, e.g. temperature_2m__frankfurt."""
    return f"{field}__{WEATHER_REFERENCE_LOCATION}"


def energy_price_column(target: str) -> str:
    """Price reference: EXAA for the price product, SDAC lags for load/gen."""
    return (
        "price_exaa_eur_mwh"
        if target.startswith("price_")
        else "price_sdac_seq1_eur_mwh"
    )


def model_id(target: str, gate: str, span: str) -> str:
    return f"{target}__{gate}__{span}"


def mlflow_storage() -> MLFlowStorage:
    """Local registry: sqlite tracking (MLflow 3 deprecated the file store)."""
    MLFLOW_DIR.mkdir(parents=True, exist_ok=True)
    return MLFlowStorage(
        tracking_uri=f"sqlite:///{(MLFLOW_DIR / 'mlflow.db').resolve()}",
        artifact_location=f"file:{(MLFLOW_DIR / 'artifacts').resolve()}",
    )
