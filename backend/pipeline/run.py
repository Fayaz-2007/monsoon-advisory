"""CLI entry point.

    python -m pipeline.run --stage all --start 1991-01-01 --end 2025-12-31
    python -m pipeline.run --stage daily        # incremental update (scheduler calls this)

Stages: boundaries, cropcal, indices, rainfall, era5, aggregate, climatology,
features, quality, all, daily.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from pipeline.config import get_settings
from pipeline.db import (StageSkipped, check_connection, init_db, mark_stale_runs, read_df,
                         track_run)
from pipeline.logging_setup import console, setup_logging

log = logging.getLogger("pipeline.run")

FULL_ORDER = ["boundaries", "cropcal", "indices", "rainfall", "era5", "aggregate",
              "climatology", "features", "quality"]
OPTIONAL_STAGES = {"era5", "cropcal"}
STAGE_CHOICES = [*FULL_ORDER, "all", "daily"]

ProgressFn = Callable[[str], None]


@dataclass
class StageResult:
    stage: str
    status: str
    rows: int
    seconds: float
    message: str


# ---------------------------------------------------------------------------
# Stage implementations (thin wrappers; heavy imports are local)
# ---------------------------------------------------------------------------


def stage_boundaries(start: date, end: date, force: bool, p: ProgressFn) -> tuple[int, list[str]]:
    from pipeline.sources.boundaries import load_boundaries
    n, level = load_boundaries()
    return n, [f"{n} {level}-level regions"]


def stage_cropcal(start: date, end: date, force: bool, p: ProgressFn) -> tuple[int, list[str]]:
    from pipeline.sources.crop_calendar import load_crop_calendar
    n = load_crop_calendar()
    return n, [f"{n} crop-calendar rows (SAMPLE)"]


def stage_indices(start: date, end: date, force: bool, p: ProgressFn) -> tuple[int, list[str]]:
    from pipeline.sources.climate_indices import run_indices
    return run_indices(start - timedelta(days=60), max(end, date.today()), force=force)


def stage_rainfall(start: date, end: date, force: bool, p: ProgressFn) -> tuple[int, list[str]]:
    from pipeline.sources.imd_rainfall import run_rainfall
    days, notes = run_rainfall(start, end, force=force, progress=p)
    return 0, [f"{days} days of gridded rainfall cached", *notes]


def stage_era5(start: date, end: date, force: bool, p: ProgressFn) -> tuple[int, list[str]]:
    from pipeline.sources.era5 import run_era5
    months, notes = run_era5(start, end, force=force, progress=p)
    return 0, notes


def stage_aggregate(start: date, end: date, force: bool, p: ProgressFn) -> tuple[int, list[str]]:
    from pipeline.transform.aggregate import run_aggregate
    return run_aggregate(start, end, recompute_weights=True, progress=p)


def stage_climatology(start: date, end: date, force: bool, p: ProgressFn) -> tuple[int, list[str]]:
    from pipeline.transform.climatology import run_climatology
    return run_climatology(progress=p)


def stage_features(start: date, end: date, force: bool, p: ProgressFn) -> tuple[int, list[str]]:
    from pipeline.transform.features import run_features
    return run_features(start, end, progress=p)


def stage_quality(start: date, end: date, force: bool, p: ProgressFn) -> tuple[int, list[str]]:
    from pipeline.quality import run_quality
    res = run_quality(start, end)
    return 0, [res.summary(), "report: data/processed/quality_report.md"]


STAGES: dict[str, Callable[[date, date, bool, ProgressFn], tuple[int, list[str]]]] = {
    "boundaries": stage_boundaries,
    "cropcal": stage_cropcal,
    "indices": stage_indices,
    "rainfall": stage_rainfall,
    "era5": stage_era5,
    "aggregate": stage_aggregate,
    "climatology": stage_climatology,
    "features": stage_features,
    "quality": stage_quality,
}


# ---------------------------------------------------------------------------
# Daily incremental mode
# ---------------------------------------------------------------------------


def daily_plan() -> tuple[date, date]:
    """Window to refresh, ending yesterday. It starts at the earliest of:
    last rainfall date + 1, yesterday - IMD_REALTIME_DAYS_BACK (provisional re-fetch), and
    the first day in the last DAILY_BACKFILL_DAYS that is missing rainfall for any active
    region (days IMD failed to serve on an earlier run are retried until they succeed).
    """
    s = get_settings()
    from pipeline.utils import as_date
    last = as_date(read_df("SELECT max(date) AS d FROM rainfall_daily")["d"].iloc[0])
    if last is None:
        raise RuntimeError("No rainfall_daily rows yet — run the full pipeline first "
                           "(python -m pipeline.run --stage all).")
    yesterday = date.today() - timedelta(days=1)
    start = min(last + timedelta(days=1), yesterday - timedelta(days=s.imd_realtime_days_back))
    gap = as_date(read_df("""
        SELECT min(d)::date AS g
        FROM generate_series(CAST(:a AS date), CAST(:b AS date), interval '1 day') AS d
        WHERE (SELECT count(*) FROM rainfall_daily rd JOIN regions r ON r.id = rd.region_id
               WHERE r.active AND rd.date = d::date AND rd.rain_mm IS NOT NULL)
            < (SELECT count(*) FROM regions WHERE active)
    """, {"a": yesterday - timedelta(days=s.daily_backfill_days), "b": last})["g"].iloc[0])
    if gap is not None and gap < start:
        log.warning("Rainfall gaps found since %s - daily window extended to backfill them", gap)
        start = gap
    return start, yesterday


def stage_daily_rainfall(start: date, end: date, force: bool, p: ProgressFn) -> tuple[int, list[str]]:
    from pipeline.sources.imd_rainfall import refresh_realtime, run_rainfall
    days, notes = run_rainfall(start, end, force=False, progress=p)
    p("re-fetching provisional days")
    refreshed = refresh_realtime(get_settings().imd_realtime_days_back)
    return 0, [f"{days} days available", f"{len(refreshed)} provisional days re-fetched", *notes]


def stage_daily_aggregate(start: date, end: date, force: bool, p: ProgressFn) -> tuple[int, list[str]]:
    from pipeline.transform.aggregate import run_aggregate
    return run_aggregate(start, end, recompute_weights=False, progress=p)


def stage_daily_era5(start: date, end: date, force: bool, p: ProgressFn) -> tuple[int, list[str]]:
    from pipeline.sources.era5 import run_era5
    _, notes = run_era5(start - timedelta(days=62), end, force=False, progress=p)
    return 0, notes


DAILY_STAGES: list[tuple[str, Callable[[date, date, bool, ProgressFn], tuple[int, list[str]]]]] = [
    ("indices", stage_indices),
    ("rainfall", stage_daily_rainfall),
    ("era5", stage_daily_era5),
    ("aggregate", stage_daily_aggregate),
    ("features", stage_features),
    ("quality", stage_quality),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def execute(plan: list[tuple[str, Callable[..., tuple[int, list[str]]]]], start: date, end: date,
            force: bool, mode: str) -> list[StageResult]:
    results: list[StageResult] = []
    with Progress(SpinnerColumn(), TextColumn("[bold]{task.fields[stage]:<12}"),
                  TextColumn("{task.description}"), BarColumn(bar_width=24),
                  TextColumn("{task.completed}/{task.total}"), TimeElapsedColumn(),
                  console=console, transient=False) as progress:
        task = progress.add_task("starting", total=len(plan), stage="")
        for name, fn in plan:
            def report(msg: str, _name: str = name) -> None:
                progress.update(task, description=msg, stage=_name)

            report("running")
            t0 = time.perf_counter()
            status, rows, msg = "success", 0, ""
            run_stage = f"daily:{name}" if mode == "daily" else name
            try:
                with track_run(run_stage, {"start": start, "end": end, "force": force}) as h:
                    rows, notes = fn(start, end, force, report)
                    h.add_rows(rows)
                    for n in notes:
                        h.note(n)
                    msg = "; ".join(notes)
                last = read_df("SELECT status, message FROM pipeline_runs WHERE id = :i",
                               {"i": h.id})
                status = str(last["status"].iloc[0])
                msg = str(last["message"].iloc[0] or "")
            except StageSkipped as exc:  # pragma: no cover — track_run swallows it
                status, msg = "skipped", str(exc)
            except Exception as exc:  # noqa: BLE001
                status, msg = "failed", f"{type(exc).__name__}: {exc}"
                log.exception("Stage %s failed", name)
            results.append(StageResult(name, status, rows, time.perf_counter() - t0, msg))
            progress.advance(task)
            if status == "failed" and name not in OPTIONAL_STAGES:
                report("stopped: required stage failed")
                break
        progress.update(task, description="done", stage="")
    return results


def print_summary(results: list[StageResult]) -> None:
    colors = {"success": "green", "skipped": "yellow", "failed": "red"}
    table = Table(title="Pipeline summary", show_lines=False)
    for col in ("Stage", "Status", "Rows", "Time", "Notes"):
        table.add_column(col, overflow="fold")
    for r in results:
        c = colors.get(r.status, "white")
        table.add_row(r.stage, f"[{c}]{r.status}[/{c}]", f"{r.rows:,}", f"{r.seconds:.1f}s",
                      r.message[:160])
    console.print(table)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    s = get_settings()
    ap = argparse.ArgumentParser(prog="python -m pipeline.run", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True, choices=STAGE_CHOICES)
    ap.add_argument("--start", type=date.fromisoformat, default=s.start_date,
                    help=f"YYYY-MM-DD (default {s.start_date})")
    ap.add_argument("--end", type=date.fromisoformat, default=s.end_date,
                    help=f"YYYY-MM-DD (default {s.end_date})")
    ap.add_argument("--force", action="store_true", help="re-download / re-crop cached files")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    if args.start > args.end:
        ap.error("--start must be on or before --end")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)
    s = get_settings()
    try:
        check_connection()
        init_db()
        mark_stale_runs()
    except RuntimeError as exc:
        log.error("%s", exc)
        return 2

    if args.stage == "daily":
        try:
            start, end = daily_plan()
        except RuntimeError as exc:
            log.error("%s", exc)
            return 2
        plan = DAILY_STAGES
        console.rule(f"[bold]daily update · {s.state_name} · {start} to {end}")
    else:
        start, end = args.start, args.end
        names = FULL_ORDER if args.stage == "all" else [args.stage]
        plan = [(n, STAGES[n]) for n in names]
        console.rule(f"[bold]{args.stage} · {s.state_name} · {start} to {end}")

    results = execute(plan, start, end, args.force, "daily" if args.stage == "daily" else "full")
    print_summary(results)
    return 1 if any(r.status == "failed" and r.stage not in OPTIONAL_STAGES for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
