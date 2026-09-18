"""Transforms: pure silver-to-gold computation — no storage, no I/O.

Each module here holds DataFrame-to-DataFrame functions: cross-source
harmonization (entsoe vs energy_charts day-ahead prices), point-in-time
feature builds, aggregations. pipelines/gold.py (when written) reads
silver, calls these, and upserts through the gold store; a transform
never touches a store, a path, or a connection, so it stays trivially
testable. Bronze-to-silver deserialization is different work and lives
with the silver layer (layers/silver/parsers).
"""
