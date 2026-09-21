"""Thread-pool runner for day-fetches. The main thread owns progress."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger(__name__)


class RateLimited(Exception):
    """A worker is persistently rate limited; stop scheduling new work."""


def run_parallel(work, fetch, workers, on_each=None):
    """Fetch ``(category, day)`` pairs; ``fetch`` returns a state string."""
    counts = {"fetched": 0, "updated": 0, "unchanged": 0, "no_data": 0, "failed": 0}
    stop = threading.Event()

    def wrap(item):
        category, day = item
        if stop.is_set():
            return category, day, "failed"
        try:
            return category, day, fetch(category, day)
        except RateLimited:
            stop.set()
            return category, day, "failed"
        except Exception:
            log.exception("failed: %s %s", category, day)
            return category, day, "failed"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(wrap, item) for item in work]
        for future in as_completed(futures):
            category, day, state = future.result()
            counts[state] += 1
            if on_each:
                on_each(category, day, state)
            if stop.is_set():
                for pending in futures:
                    pending.cancel()
                log.warning("still rate limited, stopping early; rerun to resume")
                break
    return counts
