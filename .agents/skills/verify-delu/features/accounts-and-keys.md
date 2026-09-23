# Accounts and keys

## Sub-features

Sign up; email confirmation; sign in and sign out; unverified gate; one-time API key reveal; key usage and quota; key refresh; account deletion. The end state for the core path is a verified account, one active key, and a keyed forecast call reflected in usage.

## How to get to it (user POV)

Use `Sign up` or `Sign in` in the top navigation. After sign-in, `API & keys` opens the dashboard. A confirmation link returns to the app's `Email confirmation` panel.

## Driving it with CUA and HTTP

Doctor the isolated instance. Use a disposable `example.test` address and new test password in the isolated browser flow when permitted by the computer-use policy. Submit `Create account`, then inspect `$RUN_DIR/server.log` for the local `verify` record containing that email and its confirmation URL. Open that URL in the same isolated instance and check the `Email confirmed` panel and one-time key reveal. Sign in if needed; `API & keys` must show the key prefix and `Forecast API`. Call `GET /v1/forecast` with `X-API-Key` and the issued key, then refresh the dashboard and confirm `used_today` increased. Keep the raw key out of screenshots and shared logs. To test refresh, use `Refresh key` and `Click again to replace the key`, then verify the old key gets 401 and the new one works. Use only accounts in this run's SQLite database.

## Gotchas

The helper disables Resend and SMTP, so confirmation is recorded in the local server log rather than delivered. The key is shown once; a screenshot may disclose it. `Refresh key` revokes the old key and carries quota usage; backend `test_keys_minute_quota_and_refresh_carries_day` covers that invariant. `Delete account` is permanent and removes account, key, sessions, and counters, so leave that flow to a dedicated disposable-account check with any action-time approval required by the browser harness. Backend auth tests do not prove the browser screens.
