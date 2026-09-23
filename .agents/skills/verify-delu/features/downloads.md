# Downloads

## Sub-features

Verified-account gate; forecast quantity and type; origin date range and presets; model run; horizon; time zone; CSV, Parquet, and XLSX; terms checkbox; generated filename and row estimate. The end state is a downloaded file with the selected origin dates, target times, quantile columns, and expected row coverage.

## How to get to it (user POV)

Choose `Download` in the top navigation. Anonymous users see `Sign In`; signed-in but unverified users see an email-confirmation message. A verified user sees `Download Forecasts` and its form.

## Driving it with CUA and HTTP

Use an isolated account created through the [accounts and keys](accounts-and-keys.md) flow. In the form, use labeled fields `Forecast Quantity`, `Forecast Type`, `Start`, `End`, `Model Run`, `Horizon in Days Ahead`, `Time Zone`, and `Format`. For the fixture choose Load, Point Forecast, both 2026-01-05 and 2026-01-06, 11:30, 1 day, Europe/Berlin, CSV. Capture the form before submission, read the Terms of Use, select `I have read and accept`, then activate `Download CSV`. Save the resulting file in the evidence directory and inspect its header, `origin_date`, `origin_time`, `target_time`, `horizon_in_hours`, and P50 rows. Compare each origin day with its stored D+1 file, including the final local quarter hour. For a boundary check, reverse Start and End and confirm the inline `End sits before start` error and disabled download.

## Gotchas

Both model runs use Europe/Berlin civil time. D+1 export covers the entire next Berlin delivery day, including its final quarter and DST day length (92, 96, or 100 rows). A missing origin day, partial horizon, or missing requested quantile fails the export. Check row coverage per origin day even when the HTTP request succeeds. The fixture supports only Load and Day-ahead price; it does not publish all six advertised series. Browser acceptance of terms is a separate UI action subject to the active computer-use policy.
