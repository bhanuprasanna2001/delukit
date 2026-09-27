from datetime import date

import pandas as pd
import pytest


def test_gate_is_visible_only_after_every_product_passes(tmp_dirs):
    from delukit.core.config.products import SPANS, TARGETS
    from delukit.ops.publication import (
        begin_run,
        expected_index,
        publish,
        published_products,
    )

    day = date(2026, 3, 28)
    root = begin_run(day, "0530")
    products = []
    for span in SPANS:
        (root / span).mkdir()
        grid = expected_index(day, span)
        for target in TARGETS:
            pd.DataFrame(
                {
                    "quantile_P10": 1.0,
                    "quantile_P50": 2.0,
                    "quantile_P90": 3.0,
                },
                index=grid,
            ).to_parquet(root / span / f"{target}__xgboost.parquet")
            products.append({"span": span, "target": target, "model": "xgboost"})
    assert len(expected_index(day, "d1")) == 92
    assert published_products(day, "0530", "d1") == []

    bad = root / "d1" / f"{TARGETS[0]}__xgboost.parquet"
    frame = pd.read_parquet(bad)
    frame.loc[frame.index[0], "quantile_P10"] = float("nan")
    frame.to_parquet(bad)
    with pytest.raises(ValueError, match="non-finite"):
        publish(day, "0530", root, products)
    assert published_products(day, "0530", "d1") == []

    frame.loc[frame.index[0], "quantile_P10"] = 1.0
    frame.to_parquet(bad)
    manifest = publish(day, "0530", root, products)
    assert manifest.is_file()
    assert len(published_products(day, "0530", "d1")) == len(TARGETS)
