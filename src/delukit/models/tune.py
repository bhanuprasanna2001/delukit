from datetime import datetime, timedelta

from openstef_models.integrations.optuna import HyperparameterTuner

from delukit.core.clean import UTC
from delukit.core.config.products import (
    TUNE_DIRECTION,
    TUNE_METRIC,
    TUNING_DIR,
    tuning_hyperparams,
)
from delukit.data.dataset import load
from delukit.models.forecast import (
    GATE_WALL,
    SPAN_D1,
    SPANS,
    create_workflow_from_config,
    workflow_config,
)


def tune_product(
    target: str,
    gate: str,
    span: str,
    *,
    n_trials: int = 10,
    train_days: int | None = None,
):
    cutoff = datetime.now(UTC)
    ds = load()
    if train_days is not None:
        ds = ds.filter_by_range(cutoff - timedelta(days=train_days), cutoff)
    train_data = ds.filter_by_available_before(cutoff).select_version()
    config = workflow_config(target, gate, span, use_tuned=False)
    config.xgboost_hyperparams = tuning_hyperparams()
    tuner = HyperparameterTuner(
        config=config,
        train_dataset=train_data,
        create_workflow=create_workflow_from_config,
        target_quantile="global",
        metric_name=TUNE_METRIC,
        direction=TUNE_DIRECTION,
        n_trials=n_trials,
        study_name=f"tune_{target}_{gate}_{span}",
    )
    best_config, study = tuner.tune()
    candidate_dir = TUNING_DIR / "candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    path = candidate_dir / f"{target}__{gate}__{span}.json"
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
    parser.add_argument("--train-days", type=int, default=None)
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
