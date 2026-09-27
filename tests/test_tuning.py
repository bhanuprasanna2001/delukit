from openstef_core.mixins.param_ranges import FloatRange, IntRange

from delukit.core.config.products import tuning_hyperparams


def test_tuning_hyperparams_exposes_all_seven_search_dimensions() -> None:
    assert tuning_hyperparams().get_search_space() == {
        "n_estimators": IntRange(50, 300, tune=True),
        "max_depth": IntRange(3, 10, tune=True),
        "learning_rate": FloatRange(0.05, 0.5, log=True, tune=True),
        "min_child_weight": FloatRange(1.0, 10.0, tune=True),
        "subsample": FloatRange(0.7, 1.0, tune=True),
        "colsample_bytree": FloatRange(0.7, 1.0, tune=True),
        "reg_lambda": FloatRange(1e-3, 10.0, log=True, tune=True),
    }
