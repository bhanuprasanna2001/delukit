"""One registry of local and CI verification commands."""

import argparse
import shlex
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type Group = Literal[
    "hygiene",
    "python-root",
    "python-delu",
    "frontend",
    "docker-root",
    "docker-delu",
]
type EnvironmentId = Literal["root-uv", "delu-uv", "frontend-npm", "docker"]
type Status = Literal["passed", "failed", "skipped"]

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class EnvironmentSpec:
    id: EnvironmentId
    directory: Path
    setup: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class CheckSpec:
    id: str
    group: Group
    environment: EnvironmentId
    command: tuple[str, ...]
    description: str


@dataclass(frozen=True, slots=True)
class Result:
    id: str
    status: Status
    exit_code: int | None


ENVIRONMENTS: tuple[EnvironmentSpec, ...] = (
    EnvironmentSpec("root-uv", REPO_ROOT, ("uv", "sync", "--locked")),
    EnvironmentSpec("delu-uv", REPO_ROOT / "delu", ("uv", "sync", "--locked")),
    EnvironmentSpec("frontend-npm", REPO_ROOT / "delu/frontend", ("npm", "ci")),
    EnvironmentSpec("docker", REPO_ROOT, None),
)

CHECKS: tuple[CheckSpec, ...] = (
    CheckSpec(
        "pre-commit",
        "hygiene",
        "root-uv",
        (
            "uv",
            "run",
            "--no-sync",
            "pre-commit",
            "run",
            "--all-files",
            "--show-diff-on-failure",
        ),
        "All repository pre-commit hooks",
    ),
    CheckSpec(
        "root-ruff",
        "python-root",
        "root-uv",
        ("uv", "run", "--no-sync", "ruff", "check", "."),
        "Root Python Ruff lint",
    ),
    CheckSpec(
        "root-format",
        "python-root",
        "root-uv",
        ("uv", "run", "--no-sync", "ruff", "format", "--check", "."),
        "Root Python Ruff format",
    ),
    CheckSpec(
        "root-pyright",
        "python-root",
        "root-uv",
        ("uv", "run", "--no-sync", "pyright"),
        "Root Python type check",
    ),
    CheckSpec(
        "root-pytest",
        "python-root",
        "root-uv",
        ("uv", "run", "--no-sync", "pytest", "-q"),
        "Root Python tests",
    ),
    CheckSpec(
        "delu-ruff",
        "python-delu",
        "delu-uv",
        ("uv", "run", "--no-sync", "ruff", "check", "."),
        "DELU Python Ruff lint",
    ),
    CheckSpec(
        "delu-format",
        "python-delu",
        "delu-uv",
        ("uv", "run", "--no-sync", "ruff", "format", "--check", "."),
        "DELU Python Ruff format",
    ),
    CheckSpec(
        "delu-pyright",
        "python-delu",
        "delu-uv",
        ("uv", "run", "--no-sync", "pyright"),
        "DELU Python type check",
    ),
    CheckSpec(
        "delu-pytest",
        "python-delu",
        "delu-uv",
        ("uv", "run", "--no-sync", "pytest", "-q"),
        "DELU Python tests",
    ),
    CheckSpec(
        "frontend-lint",
        "frontend",
        "frontend-npm",
        ("npm", "run", "lint"),
        "Frontend Oxlint",
    ),
    CheckSpec(
        "frontend-build",
        "frontend",
        "frontend-npm",
        ("npm", "run", "build"),
        "Frontend TypeScript and Vite build",
    ),
    CheckSpec(
        "docker-root-build",
        "docker-root",
        "docker",
        ("docker", "build", "-t", "delukit:verify", "."),
        "Root Docker image",
    ),
    CheckSpec(
        "docker-delu-build",
        "docker-delu",
        "docker",
        ("docker", "build", "-t", "delu:verify", "./delu"),
        "DELU Docker image",
    ),
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse and validate selection at the command boundary."""
    groups = tuple(dict.fromkeys(check.group for check in CHECKS))
    check_ids = tuple(check.id for check in CHECKS)
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--group", action="append", choices=groups, metavar="GROUP")
    selection.add_argument(
        "--check", action="append", choices=check_ids, metavar="CHECK"
    )
    parser.add_argument("--list", action="store_true", help="List groups and checks")
    args = parser.parse_args(argv)
    if args.list and (args.group or args.check):
        parser.error("--list cannot be combined with --group or --check")
    return args


def select_checks(args: argparse.Namespace) -> tuple[CheckSpec, ...]:
    """Select checks in registry order, with no duplicates."""
    if args.group:
        selected = set(args.group)
        return tuple(check for check in CHECKS if check.group in selected)
    if args.check:
        selected = set(args.check)
        return tuple(check for check in CHECKS if check.id in selected)
    return CHECKS


def print_list() -> None:
    """Display the same groups and checks used by the runner."""
    for group in dict.fromkeys(check.group for check in CHECKS):
        print(group)
        for check in CHECKS:
            if check.group == group:
                print(f"  {check.id:<20} {check.description}")


def run_command(command: tuple[str, ...], directory: Path) -> int:
    """Run a fixed argv in its project directory and stream its output."""
    print(f"\n$ (cd {directory} && {shlex.join(command)})", flush=True)
    try:
        return subprocess.run(command, cwd=directory, check=False).returncode
    except OSError as error:
        print(f"Could not start {command[0]}: {error}", file=sys.stderr)
        return 127


def run_checks(checks: tuple[CheckSpec, ...]) -> tuple[Result, ...]:
    """Prepare each selected environment once and run independent checks."""
    environments = {environment.id: environment for environment in ENVIRONMENTS}
    setup_codes: dict[EnvironmentId, int] = {}
    results: list[Result] = []
    for check in checks:
        environment = environments[check.environment]
        if environment.id not in setup_codes:
            setup_code = (
                run_command(environment.setup, environment.directory)
                if environment.setup is not None
                else 0
            )
            setup_codes[environment.id] = setup_code
            if setup_code:
                results.append(Result(f"setup:{environment.id}", "failed", setup_code))
        if setup_codes[environment.id]:
            results.append(Result(check.id, "skipped", None))
            continue
        code = run_command(check.command, environment.directory)
        results.append(Result(check.id, "failed" if code else "passed", code))
    return tuple(results)


def print_summary(results: tuple[Result, ...]) -> None:
    """Report every selected check and setup failure after execution."""
    print("\nVerification summary")
    for result in results:
        code = f" (exit {result.exit_code})" if result.exit_code else ""
        print(f"  {result.status:<7} {result.id}{code}")
    counts = {
        status: sum(result.status == status for result in results)
        for status in ("passed", "failed", "skipped")
    }
    print(
        f"{counts['passed']} passed, {counts['failed']} failed, "
        f"{counts['skipped']} skipped"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Return success only when all selected checks and setup steps passed."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.list:
        print_list()
        return 0
    results = run_checks(select_checks(args))
    print_summary(results)
    return int(any(result.status != "passed" for result in results))
