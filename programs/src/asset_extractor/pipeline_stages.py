"""Concrete optional pipeline stage implementations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .errors import PipelineError
from .pipeline_contracts import StageResult, StageStatus, result, stage_status
from .pipeline_runner import PythonRunner, run_python
from .pipeline_support import path
from .visual import compare_images


def run_textured_stage(
    run_root: Path,
    config_dir: Path,
    config: dict[str, Any],
    *,
    runner: PythonRunner = run_python,
) -> StageResult:
    source_tree = path(config.get("source_tree"), config_dir, "textured.source_tree")
    script = Path(__file__).resolve().parents[2] / "prepare_textured_pilot.py"
    output = run_root / "textured"
    arguments = [
        "--run-root",
        str(run_root),
        "--output",
        str(output),
        "--source-tree",
        str(source_tree),
    ]
    for catalog in config.get("catalog_runs", []):
        arguments.extend(
            ("--catalog-run", str(path(catalog, config_dir, "textured.catalog_runs[]")))
        )
    if config.get("allow_equivalent_material_duplicates", False):
        arguments.append("--allow-equivalent-material-duplicates")
    for mesh_sha in config.get("only_mesh_sha256", []):
        arguments.extend(("--only-mesh-sha256", str(mesh_sha)))
    if config.get("material_overrides"):
        arguments.extend(
            (
                "--material-overrides",
                str(path(config["material_overrides"], config_dir, "textured.material_overrides")),
            )
        )
    if config.get("runtime_python"):
        arguments.extend(
            (
                "--runtime-python",
                str(path(config["runtime_python"], config_dir, "textured.runtime_python")),
            )
        )
    completed = runner(script, arguments)
    manifest = output / "textured-static-manifest.json"
    if not manifest.is_file():
        return result(
            "failed",
            returncode=completed.returncode,
            error=completed.stderr.strip() or completed.stdout.strip(),
        )
    document = json.loads(manifest.read_text(encoding="utf-8"))
    return result(stage_status(document.get("status")), manifest, returncode=completed.returncode)


def run_render_stage(
    run_root: Path,
    textured: StageResult,
    *,
    runner: PythonRunner = run_python,
) -> tuple[StageResult, list[Path]]:
    if textured.get("status") not in {"complete", "partial"} or not textured.get("manifest"):
        return result("skipped", reason="textured stage did not publish a manifest"), []
    document = json.loads(Path(str(textured["manifest"])).read_text(encoding="utf-8"))
    script = Path(__file__).resolve().parents[2] / "render_gltf_snapshot.py"
    render_root = run_root / "renders"
    rendered: list[Path] = []
    failures: list[str] = []
    for index, model in enumerate(document.get("models", [])):
        if not isinstance(model, dict) or model.get("status") != "converted":
            continue
        source = Path(str(model.get("output", ""))).resolve()
        try:
            source.relative_to(run_root.resolve())
        except ValueError:
            failures.append(f"model escaped pipeline run root: {source}")
            continue
        if not source.is_file():
            failures.append(f"missing model: {source}")
            continue
        target = render_root / f"{index:04d}-{source.stem}.png"
        completed = runner(script, [str(source), str(target)])
        if completed.returncode == 0 and target.is_file():
            rendered.append(target)
        else:
            failures.append(completed.stderr.strip() or f"renderer failed: {source}")
    status: StageStatus = (
        "complete" if rendered and not failures else "partial" if rendered else "failed"
    )
    return result(
        status, output=str(render_root.resolve()), rendered=len(rendered), failures=failures
    ), rendered


def run_visual_stage(
    config: Any,
    config_dir: Path,
    rendered: Iterable[Path],
    *,
    comparator: Any = compare_images,
) -> StageResult:
    if config is None:
        return result("skipped", reason="no reference images configured")
    if not isinstance(config, list) or not config:
        return result("failed", reason="references must be a non-empty array")
    candidates = list(rendered)
    results: list[dict[str, Any]] = []
    for index, raw in enumerate(config):
        if isinstance(raw, str):
            reference = path(raw, config_dir, f"references[{index}]")
            selected_candidates = candidates
        elif isinstance(raw, dict):
            reference = path(raw.get("path"), config_dir, f"references[{index}].path")
            configured = raw.get("candidates")
            selected_candidates = (
                [path(item, config_dir, f"references[{index}].candidates[]") for item in configured]
                if isinstance(configured, list)
                else candidates
            )
        else:
            raise PipelineError(f"references[{index}] must be a path or object")
        if not reference.is_file():
            raise PipelineError(f"reference image is missing: {reference}")
        comparisons = [
            comparator(reference, candidate)
            for candidate in selected_candidates
            if candidate.is_file()
        ]
        scored = [item for item in comparisons if item.get("status") == "scored"]
        ranked = sorted(scored, key=lambda item: float(item.get("score", 0.0)), reverse=True)
        best = ranked[0] if ranked else None
        second = ranked[1] if len(ranked) > 1 else None
        margin = (
            round(float(best["score"]) - float(second["score"]), 6)
            if best is not None and second is not None
            else None
        )
        accepted_ranked = [item for item in ranked if item.get("accepted") is True]
        decision = (
            accepted_ranked[0]
            if accepted_ranked
            and best is accepted_ranked[0]
            and (second is None or (margin is not None and margin >= 0.05))
            else None
        )
        results.append(
            {
                "reference": str(reference.resolve()),
                "comparisons": comparisons,
                "best": best,
                "accepted": decision,
                "margin": margin,
            }
        )
    status: StageStatus = (
        "complete"
        if results and all(item["accepted"] is not None for item in results)
        else "partial"
    )
    return result(
        status,
        count=len(results),
        results=results,
        policy="ranking evidence; never rewrites UV/material bindings",
    )
