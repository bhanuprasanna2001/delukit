"""Raw -> clean builder: data/clean/{entsoe,smard,weather,calendar}.parquet."""

from delukit.sources import calendar, entsoe, smard, weather


def main():
    for name, module in (
        ("entsoe", entsoe),
        ("smard", smard),
        ("weather", weather),
        ("calendar", calendar),
    ):
        path = module.to_clean()
        print(f"clean {name}: {path}")


if __name__ == "__main__":
    main()
