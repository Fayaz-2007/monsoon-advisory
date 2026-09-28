"""Logging configuration: rich console output + a plain log file in data/processed/."""

from __future__ import annotations

import logging

from rich.console import Console
from rich.logging import RichHandler

from pipeline.config import get_settings

console = Console()


def setup_logging(verbose: bool = False) -> None:
    settings = get_settings()
    settings.ensure_dirs()
    level = logging.DEBUG if verbose else logging.INFO

    rich_handler = RichHandler(console=console, show_path=False, rich_tracebacks=True,
                               markup=False, log_time_format="%H:%M:%S")
    rich_handler.setLevel(level)
    file_handler = logging.FileHandler(settings.processed_dir / "pipeline.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)
    root.addHandler(rich_handler)
    root.addHandler(file_handler)
    for noisy in ("urllib3", "fiona", "pyogrio", "matplotlib", "cdsapi", "multiurl",
                  "ecmwf", "datapi"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
