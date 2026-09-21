"""Hyperparameter tuning per product with Optuna.

Tunes the XGBoost search space declared on the workflow config, then stores
the winning hyperparams as data/tuning/<target>__<gate>__<span>.json.
Re-run the backtest with --tuned to measure the improvement; promote by
fitting production with the tuned config (the registry keeps the champion).
"""

from datetime import datetime, timedelta

from openstef_models.integrations.optuna import HyperparameterTuner

from delukit.core.clean import UTC
from delukit.core.config.products import (
    TUNE_DIRECTION,
    TUNE_METRIC,
    TUNING_DIR,
    tuning_hyperparams,
)
from delukit.dataset import load
from delukit.forecast import (
    GATE_WALL,
    SPAN_D1,
    SPANS,
    create_workflow_from_config,
    workflow_config,
)


def tune_product(
    target: str, gate: str, span: str, *, n_trials: int = 10, train_days: int = 180
):
    """Tune on trailing history; persist the winning hyperparams."""
    cutoff = datetime.now(UTC)
    train_data = (
        load()
        .filter_by_range(cutoff - timedelta(days=train_days), cutoff)
        .filter_by_available_before(cutoff)
        .select_version()
    )
    config = workflow_config(target, gate, span, use_tuned=False)
    config.xgboost_hyperparams = tuning_hyperparams()
    tuner = HyperparameterTuner(
        config=config,
        train_dataset=train_data,
        create_workflow=create_workflow_from_config,
        target_quantile="global",  # rCRPS scores the full quantile set
        metric_name=TUNE_METRIC,
        direction=TUNE_DIRECTION,
        n_trials=n_trials,
        study_name=f"tune_{target}_{gate}_{span}",
    )
    best_config, study = tuner.tune()
    TUNING_DIR.mkdir(parents=True, exist_ok=True)
    path = TUNING_DIR / f"{target}__{gate}__{span}.json"
    path.write_text(best_config.xgboost_hyperparams.model_dump_json(indent=2))
    best = study.best_trial
    print(f"tuned {target} {gate} {span}: {TUNE_METRIC}={best.value:.4f} -> {path}")
    print(f"params: {best.params}")
    return path


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Tune one product with Optuna.")
    parser.add_argument("--target", default="load_actual_mw")
    parser.add_argument("--gate", choices=sorted(GATE_WALL), default="0530")
    parser.add_argument("--span", choices=list(SPANS), default=SPAN_D1)
    parser.add_argument("--n-trials", type=int, default=10)
    parser.add_argument("--train-days", type=int, default=180)
    args = parser.parse_args()

    tune_product(
        args.target,
        args.gate,
        args.span,
        n_trials=args.n_trials,
        train_days=args.train_days,
    )


if __name__ == "__main__":
    main()
