"""Gold layer: consumption-ready storage built from silver by transforms/.

Empty until the first transform lands: store.py and tables.py arrive with
the first gold table, composed by pipelines/gold.py. Cross-source
decisions (entsoe vs energy_charts day-ahead) happen here, never in
silver — silver keeps every source side by side so gold can choose.
"""
