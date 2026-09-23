# Forecast API

## Sub-features

Public options and forecast routes; keyed `/v1/forecast`; OpenAPI forecast specification; validation of type, date, gate, span, and target; rate-limit headers and 429 behavior. The end state is a stored forecast response for the requested selection, with expected metadata, arrays, and auth behavior.

## How to get to it (user POV)

Open `API & keys` for the Swagger forecast UI after signing in and confirming the account email. An HTTP client can call the same service at `/api/options`, `/api/forecast`, and `/v1/forecast`; the latter needs an API key issued after verification.

## Driving it with curl

Doctor the isolated instance. Request `GET $URL/api/options`; expect dates 2026-01-05 and 2026-01-06, gates 0530 and 1130, spans d1 and d10, and Load and Day-ahead price targets. Request `/api/forecast?date=2026-01-06&gate=0530&span=d1&target=load_actual_mw&type=probabilistic` and save the body in evidence. Check `meta.gate` is `0530`, the first non-null P50 is 1010, 96 non-null P50 values exist, and P10/P90 arrays are present. The response also includes earlier realised quarters with null P50. The same query with `type=point` must return null P10/P90. Request `/v1/forecast` without a key and expect 401. For an issued isolated key, send `X-API-Key`, expect 200 with `X-RateLimit-Minute` and `X-RateLimit-Day`, and check the account usage counter. Save status, headers, and redacted bodies; do not write the raw key to evidence.

## Gotchas

`/api/forecast` is public while `/v1/forecast` is keyed. The published schema at `/openapi-forecast.json` contains only the keyed forecast route. Avoid trying to prove quotas by exhausting a shared account; this instance is isolated, but a dedicated quota check still needs a fresh disposable account. Backend tests `test_app_forecast_validation_and_v1_auth` and `test_app_v1_quota_and_export` exercise status and quota, while a live HTTP drive proves the running process and actual fixture.
