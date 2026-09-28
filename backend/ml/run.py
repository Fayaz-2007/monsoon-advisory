"""Segment 2 CLI.

    python -m ml.run --stage build-targets     # features + targets → data/processed/ml/
    python -m ml.run --stage validate          # rolling-origin hindcast → model_skill, artifacts
    python -m ml.run --stage train             # final models + calibrators + model card
    python -m ml.run --stage predict --issue-date 2026-09-28
    python -m ml.run --stage all               # build-targets → validate → train → predict

``validate`` runs before ``train`` because the final calibrators and boosting rounds come
from the validation folds.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable
from datetime import date

import pandas as pd
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from pipeline.db import check_connection, mark_stale_runs, track_run
from pipeline.logging_setup import console, setup_logging
from pipeline.run import StageResult

log = logging.getLogger("ml.run")

ORDER = ["build-targets", "validate", "train", "predict"]
ProgressFn = Callable[[str], None]


def stage_build_targets(args: argparse.Namespace, p: ProgressFn) -> tuple[int, list[str]]:
    from ml.config import CFG
    from ml.data import ISSUE_FILE, build_dataset, save_dataset

    ds = build_dataset(p)
    save_dataset(ds)
    i = ds.issue
    notes = [f"{len(i):,} region×issue-date rows ({i['year'].min()}–{i['year'].max()}, "
             f"{i['region_id'].nunique()} regions), final data to {ds.final_end}"]
    for k in CFG.leads:
        n = int(i[f"total_l{k}"].notna().sum())
        notes.append(f"L{k}: {n:,} targets, heavy {i[f'heavy_l{k}'].mean():.3f}, "
                     f"dry {i[f'dry_l{k}'].mean():.3f}")
    notes.append(f"cache: {ISSUE_FILE.relative_to(ISSUE_FILE.parents[3]).as_posix()}")
    return len(i), notes


def stage_validate(args: argparse.Namespace, p: ProgressFn) -> tuple[int, list[str]]:
    from ml.config import CFG
    from ml.data import load_dataset
    from ml.schema import upsert_skill
    from ml.tracking import mlflow_run
    from ml.validate import new_model_version, run_validate

    mv = args.model_version or new_model_version()
    with mlflow_run(f"validate {mv}", {"model_version": mv, "stage": "validate"}) as tr:
        tr.params({"first_oof_year": CFG.first_oof_year, "first_test_year": CFG.first_test_year,
                   "oni_lag": CFG.oni_lag, "dmi_lag": CFG.dmi_lag, "n_boot": CFG.n_boot,
                   "max_rounds": CFG.max_rounds, **CFG.lgbm_params})
        res = run_validate(load_dataset(), p, mv)
        skill = res["skill"]
        n = upsert_skill(skill)
        main = skill[(skill["model"] == "lgbm") & skill["metric"].isin(["rpss", "bss", "auc", "qss"])]
        tr.metrics({f"{r.target}.{r.metric}.L{r.lead_week}.{r.season}": r.value for r in main.itertuples()})
        tr.metrics({f"{r.target}.{r.metric}.L{r.lead_week}.{r.season}.ci_low": r.ci_low
                    for r in main.itertuples() if r.ci_low == r.ci_low})
        for y, s in res["info"]["fold_seconds"].items():
            tr.metrics({"fold_seconds": s}, step=int(y))
        from ml.config import ARTIFACTS_DIR
        tr.artifact(ARTIFACTS_DIR / mv / "skill.csv")
        tr.artifact(ARTIFACTS_DIR / mv / "validation.json")
    info = res["info"]
    rp = skill[(skill["model"] == "lgbm") & (skill["target"] == "tercile") & (skill["metric"] == "rpss")
               & (skill["season"] == "ALL")]
    notes = [f"model_version {mv}",
             f"OOF years {info['oof_years'][0]}–{info['oof_years'][-1]}, "
             f"test {info['test_years'][0]}–{info['test_years'][-1]} ({info['n_test_rows']:,} rows)",
             "RPSS (ALL) " + ", ".join(f"L{int(r.lead_week)} {r.value:+.3f}" for r in rp.itertuples()),
             f"{n} model_skill rows"]
    return n, notes


def stage_train(args: argparse.Namespace, p: ProgressFn) -> tuple[int, list[str]]:
    from ml.config import ARTIFACTS_DIR
    from ml.data import load_dataset
    from ml.tracking import mlflow_run
    from ml.train import latest_validated, run_train

    mv = args.model_version or latest_validated()
    with mlflow_run(f"train {mv}", {"model_version": mv, "stage": "train"}) as tr:
        res = run_train(load_dataset(), p, mv)
        tr.params({"train_years": res["meta"]["train_years"], "n_features": len(res["meta"]["features"])})
        tr.metrics({"train_seconds": res["seconds"]})
        for name in ("model_card.md", "feature_importance.csv", "meta.json"):
            tr.artifact(ARTIFACTS_DIR / mv / name)
    top = ", ".join(res["top"].head(5).index)
    return 24, [f"model_version {mv}: 24 models", f"top features: {top}",
                f"card: ml/artifacts/{mv}/model_card.md"]


def stage_predict(args: argparse.Namespace, p: ProgressFn) -> tuple[int, list[str]]:
    from ml.predict import run_predict

    p("building features and predicting")
    fc, n = run_predict(args.issue_date, args.model_version)
    t = fc["issue_date"].iloc[0]
    conf = fc["confidence"].value_counts().to_dict()
    return n, [f"issue date {t}: {n} forecast rows ({fc['region_id'].nunique()} regions × 4 leads)",
               "confidence " + ", ".join(f"{k} {v}" for k, v in sorted(conf.items())),
               f"model {fc['model_version'].iloc[0]}"]


STAGES: dict[str, Callable[[argparse.Namespace, ProgressFn], tuple[int, list[str]]]] = {
    "build-targets": stage_build_targets,
    "validate": stage_validate,
    "train": stage_train,
    "predict": stage_predict,
}


def execute(names: list[str], args: argparse.Namespace) -> list[StageResult]:
    results: list[StageResult] = []
    with Progress(SpinnerColumn(), TextColumn("[bold]{task.fields[stage]:<13}"),
                  TextColumn("{task.description}"), BarColumn(bar_width=24),
                  TextColumn("{task.completed}/{task.total}"), TimeElapsedColumn(),
                  console=console, transient=False) as progress:
        task = progress.add_task("starting", total=len(names), stage="")
        for name in names:
            def report(msg: str, _name: str = name) -> None:
                progress.update(task, description=msg, stage=_name)

            report("running")
            t0 = time.perf_counter()
            status, rows, msg = "success", 0, ""
            try:
                with track_run(f"ml:{name}", {"issue_date": args.issue_date,
                                              "model_version": args.model_version}) as h:
                    rows, notes = STAGES[name](args, report)
                    h.add_rows(rows)
                    for n in notes:
                        h.note(n)
                    msg = " | ".join(notes)
            except Exception as exc:  # noqa: BLE001
                status, msg = "failed", f"{type(exc).__name__}: {exc}"
                log.exception("Stage %s failed", name)
            results.append(StageResult(name, status, rows, time.perf_counter() - t0, msg))
            progress.advance(task)
            if status == "failed":
                report("stopped: stage failed")
                break
        progress.update(task, description="done", stage="")
    return results


def print_summary(results: list[StageResult]) -> None:
    colors = {"success": "green", "failed": "red"}
    table = Table(title="Segment 2 summary")
    for col in ("Stage", "Status", "Rows", "Time", "Notes"):
        table.add_column(col, overflow="fold")
    for r in results:
        c = colors.get(r.status, "white")
        table.add_row(r.stage, f"[{c}]{r.status}[/{c}]", f"{r.rows:,}", f"{r.seconds:.1f}s",
                      r.message.replace(" | ", "\n")[:900])
    console.print(table)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m ml.run", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True, choices=[*ORDER, "all"])
    ap.add_argument("--issue-date", type=date.fromisoformat, default=None,
                    help="predict: YYYY-MM-DD (default: day after the last rainfall date)")
    ap.add_argument("--model-version", default=None,
                    help="validate: name to use; train/predict: which version (default latest)")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)
    for noisy in ("mlflow", "alembic", "git", "lightgbm"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        check_connection()
        mark_stale_runs()
        from ml.schema import init_ml_tables
        init_ml_tables()
    except RuntimeError as exc:
        log.error("%s", exc)
        return 2
    names = ORDER if args.stage == "all" else [args.stage]
    console.rule(f"[bold]Segment 2 · {args.stage}"
                 + (f" · issue {args.issue_date}" if args.issue_date else ""))
    results = execute(names, args)
    print_summary(results)
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
