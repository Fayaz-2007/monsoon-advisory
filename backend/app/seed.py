"""Seed the demo: create the backend tables and draft today's advisories.

    python -m app.seed                       # tables + hazards + draft advisories for today
    python -m app.seed --date 2026-10-20     # another issue date
    python -m app.seed --scenarios           # also precompute every demo scenario
    python -m app.seed --purge               # empty the backend tables first (S1/S2 untouched)
"""

from __future__ import annotations

import argparse
import collections
import logging
from datetime import date

from app import state
from app.advisory.engine import draft_advisories
from app.config import today
from app.db import APP_TABLES, execute, fetch_all, init_app_tables
from app.hazards.engine import clear_memo, ensure_context, list_hazards
from app.mock.scenarios import SCENARIOS


def _run(d: date | None, label: str) -> None:
    ctx = ensure_context(d, force=True)
    stats = draft_advisories(ctx)  # also refreshes drafts after template changes
    hz = list_hazards(ctx.run_id)
    adv = fetch_all("SELECT status, count(*) AS n FROM advisories WHERE issue_date = :d AND "
                    "forecast_source = :s AND scenario = :sc GROUP BY status",
                    {"d": ctx.issue_date, "s": ctx.source, "sc": ctx.scenario})
    sev = collections.Counter(h["severity"] for h in hz)
    print(f"[{label}] {ctx.issue_date} source={ctx.source} scenario={ctx.scenario} "
          f"forecast_issue_date={ctx.meta.forecast_issue_date} model={ctx.meta.model_version}")
    print(f"    hazards: {len(hz)} ({dict(sev)}) in {len({h['district'] for h in hz})} districts")
    by_status = {r["status"]: r["n"] for r in adv}
    print(f"    advisories: {by_status} (this run: {stats})")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", type=date.fromisoformat, default=None)
    p.add_argument("--scenarios", action="store_true", help="precompute all demo scenarios")
    p.add_argument("--purge", action="store_true", help="empty the backend tables first")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)

    init_app_tables()
    print(f"Backend tables ready: {', '.join(APP_TABLES)}")
    if args.purge:
        for t in APP_TABLES:
            if t != "app_settings":
                execute(f"TRUNCATE {t} RESTART IDENTITY CASCADE")
        print("Purged backend workflow tables")
    previous = state.get_scenario()
    state.set_scenario(None)
    clear_memo()
    _run(args.date or today(), f"{state.get_source()} baseline")
    if args.scenarios:
        source = state.get_source()
        state.set_source("mock")
        for name in SCENARIOS:
            state.set_scenario(name)
            clear_memo()
            _run(None, f"scenario {name}")
        state.set_source(source)
    state.set_scenario(previous)
    print("Done. Start the API with:  uvicorn app.main:app --reload")


if __name__ == "__main__":
    main()
