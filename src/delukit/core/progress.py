from contextlib import contextmanager

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)


@contextmanager
def sync_progress(totals):
    """One rich bar per source; ``advance(source, day, state)`` feeds it."""
    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=None),
        MofNCompleteColumn(),
        TextColumn("[dim]{task.fields[status]}"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
    ) as progress:
        tasks = {
            source: progress.add_task(source.upper(), total=total, status="…")
            for source, total in totals.items()
        }
        counts = {
            source: {
                "fetched": 0,
                "updated": 0,
                "unchanged": 0,
                "no_data": 0,
                "failed": 0,
            }
            for source in totals
        }

        def advance(source, day, state):
            counts[source][state] += 1
            c = counts[source]
            progress.update(
                tasks[source],
                description=f"{source.upper()} {day}",
                advance=1,
                status=f"new {c['fetched']} | upd {c['updated']} | "
                f"same {c['unchanged']} | empty {c['no_data']} | "
                f"fail {c['failed']}",
            )

        yield advance
