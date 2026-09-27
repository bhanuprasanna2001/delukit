import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from openstef_core.types import LeadTime, Q
from openstef_models.integrations.mlflow import MLFlowStorage
from openstef_models.presets.forecasting_workflow import LocationConfig
from pydantic_extra_types.coordinate import Coordinate, Latitude, Longitude
from pydantic_extra_types.country import CountryAlpha2

GATE_0530 = "0530"
GATE_1130 = "1130"

TARGETS = (
    "price_sdac_seq1_eur_mwh",
    "load_actual_mw",
    "gen_actual_total_mwh",
    "gen_actual_wind_onshore_mwh",
    "gen_actual_wind_offshore_mwh",
    "gen_actual_photovoltaics_mwh",
)

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

QUANTILES = [Q(level / 10) for level in range(1, 10)]

SPAN_D1 = "d1"
SPAN_D10 = "d10"
SPANS = (SPAN_D1, SPAN_D10)
PRODUCTS_BY_GATE = {
    GATE_0530: tuple((span, target) for span in SPANS for target in TARGETS),
    GATE_1130: tuple((span, "price_sdac_seq1_eur_mwh") for span in SPANS),
}

HORIZONS = {
    (GATE_0530, SPAN_D1): [LeadTime(timedelta(hours=42, minutes=30))],
    (GATE_0530, SPAN_D10): [LeadTime(timedelta(hours=258, minutes=30))],
    (GATE_1130, SPAN_D1): [LeadTime(timedelta(hours=36, minutes=30))],
    (GATE_1130, SPAN_D10): [LeadTime(timedelta(hours=252, minutes=30))],
}

PREDICT_LENGTH = {SPAN_D1: timedelta(hours=48), SPAN_D10: timedelta(days=11)}

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

KNOWN_AT_GATE = {
    (GATE_1130, SPAN_D1): ("price_exaa_eur_mwh", "load_forecast_mw"),
}


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
    known = KNOWN_AT_GATE.get((gate, span), ())
    curves = [c for c in PUBLISHED_CURVES if c != target and c not in known]
    actuals = [c for c in ENTSOE_ACTUAL_COLUMNS + SMARD_ACTUAL_COLUMNS if c != target]
    return curves + actuals


WEATHER_REFERENCE_LOCATION = "frankfurt"

LOCATION = LocationConfig(
    name="DE-LU",
    coordinate=Coordinate(
        latitude=Latitude(Decimal("51.16")), longitude=Longitude(Decimal("10.45"))
    ),
    country_code=CountryAlpha2("DE"),
)

PREDICT_CONTEXT = timedelta(days=14)
COMPLETENESS_THRESHOLD = 0.5

TRAINING_DAYS: int | None = None
TRAIN_INTERVAL = timedelta(days=7)
PREDICT_CONTEXT_MIN_COVERAGE = 0.5
TRAINING_CONTEXT_MIN_COVERAGE = 0.5

N_JOBS = int(os.getenv("DELUKIT_MODEL_THREADS", "4"))

CALIBRATE_QUANTILES = True

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

TUNE_METRIC = "rCRPS"
TUNE_DIRECTION = "minimize"


def tuning_hyperparams():
    from openstef_core.mixins.param_ranges import FloatRange, IntRange
    from openstef_models.models.forecasting.xgboost_forecaster import XGBoostHyperParams

    return XGBoostHyperParams.model_validate(
        {
            "n_estimators": IntRange(50, 300, tune=True),
            "max_depth": IntRange(3, 10, tune=True),
            "learning_rate": FloatRange(0.05, 0.5, log=True, tune=True),
            "min_child_weight": FloatRange(1.0, 10.0, tune=True),
            "subsample": FloatRange(0.7, 1.0, tune=True),
            "colsample_bytree": FloatRange(0.7, 1.0, tune=True),
            "reg_lambda": FloatRange(1e-3, 10.0, log=True, tune=True),
        },
        by_name=True,
    )


MLFLOW_DIR = Path("data/mlflow")
TUNING_DIR = Path("data/tuning")
BACKTEST_DIR = Path("data/backtests")
FORECAST_DIR = Path("data/forecasts")
SCORES_DIR = Path("data/scores")


def weather_ref(field: str) -> str:
    return f"{field}__{WEATHER_REFERENCE_LOCATION}"


def energy_price_column(target: str) -> str:
    return (
        "price_exaa_eur_mwh"
        if target.startswith("price_")
        else "price_sdac_seq1_eur_mwh"
    )


def model_id(target: str, gate: str, span: str) -> str:
    return f"{target}__{gate}__{span}"


def mlflow_storage() -> MLFlowStorage:
    MLFLOW_DIR.mkdir(parents=True, exist_ok=True)
    return MLFlowStorage(
        tracking_uri=f"sqlite:///{(MLFLOW_DIR / 'mlflow.db').resolve()}",
        local_artifacts_path=MLFLOW_DIR / "artifacts_local",
        artifact_location=f"file:{(MLFLOW_DIR / 'artifacts').resolve()}",
    )
