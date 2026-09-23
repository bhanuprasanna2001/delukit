"""The three live schedules select the intended files and Berlin days."""

from datetime import datetime
from zoneinfo import ZoneInfo

import dagster as dg


def test_schedule_jobs_do_not_refetch_at_a_forecast_or_score_cutoff():
    from delukit.dagster_app.definitions import defs

    jobs = {job.name: job for job in defs.resolve_all_job_defs()}
    selected = {
        schedule.name: {
            key.to_user_string()
            for key in jobs[schedule.job.name].asset_layer.executable_asset_keys
        }
        for schedule in defs.schedules[:3]
    }
    assert selected == {
        "source_refresh_schedule": {"raw_data", "clean_data", "versioned_data"},
        "gate_schedule": {"forecast_d1", "forecast_d10"},
        "scores_schedule": {"forecast_scores"},
    }
    assert all(
        schedule.default_status == dg.DefaultScheduleStatus.RUNNING
        for schedule in defs.schedules[:3]
    )


def test_spring_dst_schedule_keys_use_berlin_civil_dates():
    from delukit.dagster_app.definitions import defs, gate_schedule, scores_schedule

    berlin = ZoneInfo("Europe/Berlin")
    repo = defs.get_repository_def()
    gate = gate_schedule.evaluate_tick(
        dg.build_schedule_context(
            scheduled_execution_time=datetime(2026, 3, 29, 5, 30, tzinfo=berlin),
            repository_def=repo,
        )
    )
    score = scores_schedule.evaluate_tick(
        dg.build_schedule_context(
            scheduled_execution_time=datetime(2026, 3, 29, 15, 30, tzinfo=berlin),
            repository_def=repo,
        )
    )
    assert [request.partition_key for request in gate.run_requests] == [
        "2026-03-29|0530"
    ]
    assert [request.partition_key for request in score.run_requests] == ["2026-03-28"]
