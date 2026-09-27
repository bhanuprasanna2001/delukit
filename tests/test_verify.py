import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY_SCRIPT = REPO_ROOT / "scripts/verify"


def run_verify(
    tmp_path: Path,
    *args: str,
    fail_root_setup: bool = False,
    fail_root_ruff: bool = False,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_log = tmp_path / "calls.log"
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        "#!/bin/sh\n"
        'printf \'%s|%s\\n\' "$(pwd)" "$*" >> "$VERIFY_CALL_LOG"\n'
        'if [ "$VERIFY_FAIL_ROOT_SETUP" = 1 ] '
        '&& [ "$(pwd)" = "$VERIFY_ROOT" ] '
        "&& [ \"$*\" = 'sync --locked' ]; then exit 23; fi\n"
        'if [ "$VERIFY_FAIL_ROOT_RUFF" = 1 ] '
        '&& [ "$(pwd)" = "$VERIFY_ROOT" ] '
        "&& [ \"$*\" = 'run --no-sync ruff check .' ]; then exit 3; fi\n"
        "exit 0\n"
    )
    fake_uv.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "VERIFY_CALL_LOG": str(call_log),
            "VERIFY_ROOT": str(REPO_ROOT),
            "VERIFY_FAIL_ROOT_SETUP": str(int(fail_root_setup)),
            "VERIFY_FAIL_ROOT_RUFF": str(int(fail_root_ruff)),
        }
    )
    result = subprocess.run(
        [str(VERIFY_SCRIPT), *args],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    calls = call_log.read_text().splitlines() if call_log.exists() else []
    return result, calls


def test_group_selection_runs_only_selected_checks_in_registry_order(
    tmp_path: Path,
) -> None:
    result, calls = run_verify(tmp_path, "--group", "python-root")

    assert result.returncode == 0
    assert [call.partition("|")[2] for call in calls] == [
        "sync --locked",
        "run --no-sync ruff check .",
        "run --no-sync ruff format --check .",
        "run --no-sync pyright",
        "run --no-sync pytest -q",
    ]
    assert "4 passed, 0 failed, 0 skipped" in result.stdout


def test_failed_check_does_not_stop_later_checks(tmp_path: Path) -> None:
    result, calls = run_verify(
        tmp_path,
        "--group",
        "python-root",
        fail_root_ruff=True,
    )

    assert result.returncode == 1
    assert len(calls) == 5
    assert "failed  root-ruff (exit 3)" in result.stdout
    assert "passed  root-format" in result.stdout
    assert "3 passed, 1 failed, 0 skipped" in result.stdout


def test_failed_setup_skips_its_checks_and_runs_another_group(tmp_path: Path) -> None:
    result, calls = run_verify(
        tmp_path,
        "--group",
        "python-root",
        "--group",
        "python-delu",
        fail_root_setup=True,
    )

    assert result.returncode == 1
    assert len(calls) == 6
    assert calls[0] == f"{REPO_ROOT}|sync --locked"
    assert calls[1] == f"{REPO_ROOT / 'delu'}|sync --locked"
    assert all(not line.startswith(f"{REPO_ROOT}|run ") for line in calls)
    assert "failed  setup:root-uv (exit 23)" in result.stdout
    assert "skipped root-ruff" in result.stdout
    assert "passed  delu-ruff" in result.stdout
    assert "4 passed, 1 failed, 4 skipped" in result.stdout
