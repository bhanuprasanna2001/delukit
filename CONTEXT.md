# Delukit domain language

| Term | Meaning |
| --- | --- |
| Valid time | The UTC quarter when an energy measurement applies or a weather value is predicted. |
| Observation | A provider response captured by this system at a specific time. |
| Known time | The earliest defensible time this system could use the observed value. |
| Revision | A changed value for the same provider product and valid time. |
| Forecast origin | One Berlin civil date and its 05:30 or 11:30 decision gate. |
| Product | One target, gate, and forecast span combination. |
| Span | D1 covers the next Berlin delivery day; D10 covers the next ten. |
| Delivery day | The Berlin civil date being forecast and later scored. It has 92, 96, or 100 quarters. |
| Lead day | Delivery day minus origin day, measured in Berlin civil dates. |
| Complete evaluation | A score using every quarter of one delivery day with eligible forecast and truth values. |
| Operational forecast | A forecast published for a live gate and read by DELU. |
| Backtest | A replay of historical origins. A strict backtest requires reconstructable source vintages. |
