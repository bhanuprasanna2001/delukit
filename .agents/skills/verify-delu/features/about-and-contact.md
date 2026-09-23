# About and contact

## Sub-features

About, data attribution, privacy, and terms pages; contact form with name, email, topic, message, inline validation, and submission status. The local end state for contact is a success status and the exact submitted message in this run's server log.

## How to get to it (user POV)

Choose `About` in the top navigation. Follow its links to `terms of use`, `data attribution`, or `contact`. Footer buttons also open `Data attribution`, `Privacy`, `Terms`, and `Contact`.

## Driving it with CUA and HTTP

Doctor the instance and open `About`. Confirm the two-run explanation and links render. Open `contact`; first submit an invalid short message and confirm the inline validation. Then enter a disposable name and `example.test` email, select a topic such as `Data question`, enter a distinct 10+ character message, and submit `Send message`. Capture before and after screenshots. Confirm a `contact` entry with the exact email, topic, and message in `$RUN_DIR/server.log` and save a redacted excerpt in evidence. The app's HTTP route is `POST /api/contact`; a sixth request from the same IP within an hour gets 429, as covered by `test_app_auth_enumeration_and_contact_throttle`.

## Gotchas

The helper disables external mail. `send_contact` writes to the log and returns false, but `/api/contact` still returns a `Message sent` response; do not claim external delivery. The log contains submitted contact data, so use synthetic details and redact before sharing. The About and legal prose may describe six series, while this verification fixture publishes only two.
