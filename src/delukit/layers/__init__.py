"""Layers: what is stored where, per medallion tier (bronze, silver, gold).

Each layer owns its stores, table names, and schemas — and knows no
backend mechanics (delukit.backends owns those). Pipelines compose the
two; tests/test_architecture.py fails any layer that reaches across.
"""
