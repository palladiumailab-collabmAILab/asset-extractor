"""Typed contracts shared by the pipeline orchestrator and stage modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Required, TypedDict, cast


StageStatus = Literal["complete", "partial", "failed", "skipped", "blocked"]
_STAGE_STATUS_VALUES = {"complete", "partial", "failed", "skipped", "blocked"}


class StageResult(TypedDict, total=False):
    status: Required[StageStatus]
    required: bool
    manifest: str
    reason: str
    message: str


def stage_status(value: Any) -> StageStatus:
    if isinstance(value, str) and value in _STAGE_STATUS_VALUES:
        return cast(StageStatus, value)
    return "failed"


def result(status: StageStatus, manifest: Path | None = None, **fields: Any) -> StageResult:
    stage: dict[str, Any] = {"status": status, **fields}
    if manifest is not None:
        stage["manifest"] = str(manifest.resolve())
    return cast(StageResult, stage)


def stage_usable(stage: StageResult) -> bool:
    return stage.get("status") in {"complete", "partial"}
