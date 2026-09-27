# Domain glossary

**Event timestamp.** The UTC instant to which an observation or forecast value applies.

**Delivery date.** The Europe/Berlin calendar date for the electricity delivery period. It can differ from the UTC date of an event timestamp.

**Gate.** A scheduled forecast issue time on a Berlin delivery calendar. Its cutoff determines which inputs a forecast may use.

**Target.** The measured quantity that a forecast predicts, such as load or solar generation.

**Span.** The forecast horizon for a target, currently day-ahead (`d1`) or ten-day (`d10`).

**Available at.** The earliest instant when a retained input value could be used by a gate forecast. A value with a later availability time is unavailable to that gate.

**Dataset version.** A retained set of input values with availability information that permits point-in-time selection.

**Publication.** The complete target-by-span result for one gate made visible as a unit after validation.
