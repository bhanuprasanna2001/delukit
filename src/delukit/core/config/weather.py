"""Open-Meteo single-runs API, ecmwf_ifs 00z runs.

One cell_selection per request, so locations are grouped:
2 requests per day, runs immutable.
"""

WEATHER_URL = "https://single-runs-api.open-meteo.com/v1/forecast"
WEATHER_MODEL = "ecmwf_ifs"
WEATHER_FORECAST_DAYS = 16

WEATHER_FIELDS = (
    "temperature_2m",
    "wind_speed_100m",
    "wind_direction_100m",
    "shortwave_radiation",
    "cloud_cover",
)

# (name, latitude, longitude) per API cell_selection group.
WEATHER_LOCATIONS = {
    "land": (
        ("emden", 53.37, 7.21),
        ("bremen", 53.08, 8.80),
        ("hamburg", 53.55, 9.99),
        ("kiel", 54.32, 10.14),
        ("rostock", 54.09, 12.14),
        ("hanover", 52.38, 9.73),
        ("berlin", 52.52, 13.41),
        ("muenster", 51.96, 7.63),
        ("kassel", 51.31, 9.50),
        ("leipzig", 51.34, 12.37),
        ("dresden", 51.05, 13.74),
        ("cologne", 50.94, 6.96),
        ("frankfurt", 50.11, 8.68),
        ("erfurt", 50.98, 11.03),
        ("nuremberg", 49.45, 11.08),
        ("luxembourg", 49.61, 6.13),
        ("stuttgart", 48.78, 9.18),
        ("freiburg", 47.99, 7.85),
        ("munich", 48.14, 11.58),
        ("passau", 48.57, 13.46),
    ),
    "sea": (
        ("north_sea_west", 54.75, 6.30),
        ("north_sea_centre", 54.60, 7.50),
        ("north_sea_east", 54.40, 8.40),
        ("baltic_west", 54.50, 11.30),
        ("baltic_east", 54.50, 13.50),
    ),
}
