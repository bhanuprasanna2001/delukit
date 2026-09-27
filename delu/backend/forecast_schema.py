"""Response contract for the keyed forecast API."""

from pydantic import BaseModel, Field


class ForecastMeta(BaseModel):
    date: str = Field(description="Origin date of the forecast run, YYYY-MM-DD.")
    gate: str = Field(description="Run time in Europe/Berlin: 0530 or 1130.")
    span: str = Field(description="Forecast span: d1 or d10.")
    target: str = Field(description="Forecast quantity identifier.")
    model: str = Field(description="Model name recorded with the publication.")
    rows: int = Field(description="Number of timestamps in this response.")
    generated_at: str = Field(description="Publication file time in ISO 8601 format.")


class ForecastResponse(BaseModel):
    meta: ForecastMeta
    timestamps: list[str] = Field(
        description="ISO 8601 target times. Every series aligns by array position."
    )
    p50: list[float | None] | None = Field(
        description="Median forecast. Null entries mark unavailable values."
    )
    p10: list[float | None] | None = Field(
        description="10th percentile, or null for a point request."
    )
    p20: list[float | None] | None = Field(
        description="20th percentile, or null for a point request."
    )
    p30: list[float | None] | None = Field(
        description="30th percentile, or null for a point request."
    )
    p40: list[float | None] | None = Field(
        description="40th percentile, or null for a point request."
    )
    p60: list[float | None] | None = Field(
        description="60th percentile, or null for a point request."
    )
    p70: list[float | None] | None = Field(
        description="70th percentile, or null for a point request."
    )
    p80: list[float | None] | None = Field(
        description="80th percentile, or null for a point request."
    )
    p90: list[float | None] | None = Field(
        description="90th percentile, or null for a point request."
    )
    actual: list[float | None] = Field(
        description="Observed values where available; null elsewhere."
    )
