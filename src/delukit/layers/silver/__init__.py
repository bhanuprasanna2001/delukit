"""Silver layer: parsed, typed, one table per source+method at native grain.

parsers/ turn bronze payloads into frames, loader.py collapses bronze
versions to the latest payload, store.py upserts by natural key, and
tables.py names and keys every silver table. No cross-source merging —
gold decides.
"""
