# Working in Delukit

Start a new task by reading the relevant part of `README.md` and locating the current owner of the behavior. The root Python project, `delu/` Python API, and `delu/frontend/` have separate dependency locks. Use `scripts/verify --list` to choose focused checks while working, then run `scripts/verify` for the complete repository gate.

For new code, place provider fetch and conversion in `sources`, clean-to-versioned mapping in `data`, prediction in `models`, publication and monitoring in `ops`, and orchestration in `dagster_app`. Shared gate, product, availability, and path policy belongs in `core/config`. The API belongs in `delu/backend`; browser behavior belongs in `delu/frontend`. If a task crosses these owners, identify the data contract at each boundary before editing.

For an existing path, trace its callers and persisted or API consumers before changing a signature, file layout, or payload. Preserve the schema-1 manifest and legacy lookup until their consumers are migrated. A passing verifier cannot establish that a forecast used only information available at its gate.
