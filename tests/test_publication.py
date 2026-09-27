import hashlib
import json
from datetime import date

import pandas as pd
import pytest


def test_gate_is_visible_only_after_every_product_passes(tmp_dirs):
    from delukit.core.config.products import QUANTILES, SPANS, TARGETS
    from delukit.ops.publication import (
        begin_run,
        expected_index,
        publish,
        published_products,
    )

    day = date(2026, 3, 28)
    assert [quantile.format() for quantile in QUANTILES] == [
        f"quantile_P{level}" for level in range(10, 100, 10)
    ]
    root = begin_run(day, "0530")
    products = []
    for span in SPANS:
        (root / span).mkdir()
        grid = expected_index(day, span)
        for target in TARGETS:
            pd.DataFrame(
                {quantile.format(): i for i, quantile in enumerate(QUANTILES)},
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

    frame.loc[frame.index[0], "quantile_P10"] = 0.0
    frame.loc[frame.index[0], "quantile_P40"] = -1.0
    frame.to_parquet(bad)
    with pytest.raises(ValueError, match="unordered"):
        publish(day, "0530", root, products)

    frame.loc[frame.index[0], "quantile_P40"] = 3.0
    frame.to_parquet(bad)
    (root / "features.parquet").write_bytes(b"gate input snapshot")
    manifest = publish(day, "0530", root, products)
    assert manifest.is_file()
    snapshot = json.loads(manifest.read_text())["input_snapshot"]
    assert snapshot == {
        "path": f".runs/{root.name}/features.parquet",
        "sha256": hashlib.sha256(b"gate input snapshot").hexdigest(),
    }
    assert len(published_products(day, "0530", "d1")) == len(TARGETS)


def test_new_publication_requires_all_nine_quantiles(tmp_dirs):
    from delukit.ops.publication import expected_index, validate_product

    day = date(2026, 3, 28)
    path = tmp_dirs["forecasts"] / "three_quantiles.parquet"
    pd.DataFrame(
        {"quantile_P10": 1.0, "quantile_P50": 2.0, "quantile_P90": 3.0},
        index=expected_index(day, "d1"),
    ).to_parquet(path)
    with pytest.raises(ValueError, match="missing forecast quantiles"):
        validate_product(path, day, "d1")
