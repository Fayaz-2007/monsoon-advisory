"""MLflow experiment tracking (local file store in backend/mlruns/, git-ignored).

MLflow ≥ 3.7 keeps the file store in "maintenance mode" and requires the opt-in
``MLFLOW_ALLOW_FILE_STORE=true``, which is set here. Tracking never breaks a run: if MLflow
fails, a warning is logged and the stage continues.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ml.config import MLFLOW_EXPERIMENT, MLRUNS_DIR

log = logging.getLogger(__name__)


class _Tracker:
    def __init__(self, mlflow_module) -> None:
        self._m = mlflow_module

    def params(self, params: dict) -> None:
        self._safe("log_params", {k: str(v)[:500] for k, v in params.items()})

    def metrics(self, metrics: dict[str, float], step: int | None = None) -> None:
        clean = {k: float(v) for k, v in metrics.items() if v == v}  # drop NaN
        self._safe("log_metrics", clean, step=step)

    def artifact(self, path: Path) -> None:
        if path.exists():
            self._safe("log_artifact", str(path))

    def _safe(self, fn_name: str, *args, **kwargs) -> None:
        if self._m is None:
            return
        try:
            getattr(self._m, fn_name)(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            log.warning("MLflow logging failed: %s", exc)


@contextmanager
def mlflow_run(run_name: str, tags: dict[str, str] | None = None) -> Iterator[_Tracker]:
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    try:
        import mlflow

        MLRUNS_DIR.mkdir(parents=True, exist_ok=True)
        mlflow.set_tracking_uri(MLRUNS_DIR.as_uri())
        mlflow.set_experiment(MLFLOW_EXPERIMENT)
        mlflow.start_run(run_name=run_name, tags=tags or {})
    except Exception as exc:  # noqa: BLE001
        log.warning("MLflow unavailable (%s); continuing without tracking", exc)
        yield _Tracker(None)
        return
    try:
        yield _Tracker(mlflow)
        mlflow.end_run(status="FINISHED")
    except BaseException:
        mlflow.end_run(status="FAILED")
        raise
