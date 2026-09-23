# DELU feature map

Use [verify-delu](../SKILL.md) to launch and doctor an isolated instance before a browser or HTTP drive. The fixture contains two run days, both daily gates, day-ahead and 10-day files, load and day-ahead price, plus load and price actuals. It has no real providers or mail delivery.

| Feature | User entry | Proof target |
| --- | --- | --- |
| [Forecast chart](forecast-chart.md) | Forecasts | Selected controls change the rendered chart and match the public response. |
| [Downloads](downloads.md) | Download | A verified account obtains a file whose rows and metadata match the selection. |
| [Accounts and keys](accounts-and-keys.md) | Sign up, Sign in, API & keys | Verification unlocks one key; keyed calls and usage work. |
| [Forecast API](forecast-api.md) | API & keys, or HTTP client | Public and keyed routes return the requested stored forecast. |
| [About and contact](about-and-contact.md) | About, footer Contact | Pages render; a submitted contact message appears in the local mail log. |

The current backend tests in `delu/tests/test_backend.py` cover auth lifecycle, quotas, forecast lookup, complete export day coverage across DST, route status, and contact throttling. They do not drive the browser. Keep both kinds of evidence.
