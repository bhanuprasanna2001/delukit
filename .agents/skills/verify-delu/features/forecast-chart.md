# Forecast chart

## Sub-features

Run day; 05:30 and 11:30 model runs; day-ahead and 10-day horizons; Load and Day-ahead price series in the isolated fixture; Point and Probabilistic types; realised-value overlay and chart inspection by keyboard. The end state is a visibly selected control and a chart for the corresponding response.

## How to get to it (user POV)

Open the instance URL. `Forecasts` is the initial page and remains available in the top navigation. No account is needed.

## Driving it with CUA and HTTP

Doctor the instance. In a fresh browser tab, inspect the `Run day` pop-up: it starts on Tue 6 Jan. Capture the default `11:30`, `Day-ahead`, `Load`, `Probabilistic` view. Activate the `05:30` button and capture the changed selection and chart. Change one control at a time for broader checks: `Previous run day, Mon 5 Jan`, `10-day`, `Series` to Day-ahead price, then `Point`. Inspect the current AX tree or screenshot after each action. Compare `meta.date`, `meta.gate`, `meta.span`, `meta.target`, quantiles, and row count with `GET /api/forecast` using the same parameters. The seeded latest day-ahead load has first non-null P50 value 1030 at 11:30 and 1010 at 05:30, with 96 non-null P50 quarters. `Point` returns null P10 and P90; `Probabilistic` returns both arrays.

## Gotchas

The controls do not expose `aria-pressed`, so use a screenshot to prove which segmented button is selected. Dia may show no AX diff after an AX click; keyboard focus plus Return worked in the live check. The response prepends realised history, represented by null P50 values, to the target forecast quarters. The two-run tooltip describes real upstream knowledge, while the fixture only distinguishes stored outputs. Serving a synthetic file cannot prove source availability or prevent point-in-time leakage in the producer. Backend tests `test_forecast_options_resolve_newest` and `test_forecast_load_with_actuals` prove lookup and response shape but do not cover browser wiring.
