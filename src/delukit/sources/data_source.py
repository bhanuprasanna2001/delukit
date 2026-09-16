from abc import ABC

class DataSource(ABC):
    def fetch():
        raise "Fetch method not built"

    def parse():
        raise "Parse method not built"
