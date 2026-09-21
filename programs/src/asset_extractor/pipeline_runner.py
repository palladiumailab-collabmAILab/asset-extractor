"""Narrow subprocess boundary for pipeline stages."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable

from .errors import PipelineError


PythonRunner = Callable[[Path, list[str]], subprocess.CompletedProcess[str]]


def run_python(script: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    command = [str(Path(sys.executable).resolve()), str(script.resolve()), *arguments]
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15 * 60,
        )
    except subprocess.TimeoutExpired as exc:
        raise PipelineError(f"pipeline subprocess timed out after 900 seconds: {script}") from exc
