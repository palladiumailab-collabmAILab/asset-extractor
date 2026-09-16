"""Configuration-driven orchestration for the complete asset workflow."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from .backends import BackendRequest, extract_with_backend
from .classification import classify_manifest_entries
from .common import atomic_write_json, sha256_file, tool_metadata, utc_now
from .errors import ExtractionError
from .matcher import build_match_manifest
from .schema import SchemaContractError, validate_document
from .visual import compare_images


class PipelineError(ExtractionError):
    """A configuration or stage error in the unified pipeline."""


def _path(value: Any, base: Path, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise PipelineError(f"{field} must be a non-empty path")
    candidate = Path(value).expanduser()
    return (base / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise PipelineError(f"{label} must be a JSON object")
    return document


def _load_config(path: Path) -> dict[str, Any]:
    document = _load_json_object(path, "pipeline config")
    try:
        errors = validate_document(document, "pipeline-config")
    except SchemaContractError:
        # A packaged/minimal runtime may not ship jsonschema or the repository
        # schemas. Preserve a useful structural guard in that environment.
        errors = []
        allowed = {
            "sources",
            "acquisition",
            "dictionary",
            "backend",
            "game_profile",
            "profile",
            "best_effort",
            "neoxtractor_root",
            "neoxtractor_config",
            "neox_tools_root",
            "backend_python",
            "textured",
            "references",
        }
        unexpected = sorted(set(document) - allowed)
        if unexpected:
            errors.append(f"pipeline-config has unexpected keys: {', '.join(unexpected)}")
        if (document.get("sources") is None) == (document.get("acquisition") is None):
            errors.append("pipeline-config requires exactly one of sources or acquisition")
    if errors:
        raise PipelineError("invalid pipeline config: " + "; ".join(errors))
    return document


def _run_python(script: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
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


def _result(status: str, manifest: Path | None = None, **fields: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"status": status, **fields}
    if manifest is not None:
        result["manifest"] = str(manifest.resolve())
    return result


def _source_paths(
    config: dict[str, Any], config_dir: Path, run_root: Path
) -> tuple[list[Path], dict[str, Any]]:
    sources = config.get("sources")
    acquisition = config.get("acquisition")
    if sources is not None and acquisition is not None:
        raise PipelineError("configure either sources or acquisition, not both")
    if sources is not None:
        if not isinstance(sources, list) or not sources:
            raise PipelineError("sources must be a non-empty array")
        source_paths = [_path(value, config_dir, "sources[]") for value in sources]
        missing = [str(path) for path in source_paths if not path.is_file()]
        if missing:
            raise PipelineError(f"source file is missing: {missing[0]}")
        return source_paths, _result(
            "complete", source_count=len(source_paths), method="configured-sources"
        )
    if not isinstance(acquisition, dict):
        raise PipelineError("configure sources or acquisition")

    script = Path(__file__).resolve().parents[2] / "pull_bluestacks_snapshot.py"
    acquisition_root = run_root / "acquisition"
    arguments = [
        "--output",
        str(acquisition_root),
        "--adb",
        str(acquisition.get("adb", "adb")),
        "--serial",
        str(acquisition.get("serial", "127.0.0.1:5555")),
        "--package",
        str(acquisition.get("package", "com.netease.onmyoji")),
    ]
    for raw_root in acquisition.get("remote_roots", []):
        if not isinstance(raw_root, str):
            raise PipelineError("acquisition.remote_roots[] must be a NAME=/PATH string")
        arguments.extend(("--remote-root", raw_root))
    if acquisition.get("include_installed_apks", False):
        arguments.append("--include-installed-apks")
    for key, option in (
        ("max_files", "--max-files"),
        ("max_file_bytes", "--max-file-bytes"),
        ("max_total_bytes", "--max-total-bytes"),
    ):
        if key in acquisition:
            arguments.extend((option, str(acquisition[key])))
    completed = _run_python(script, arguments)
    manifest = acquisition_root / "snapshot-manifest.json"
    if not manifest.is_file():
        raise PipelineError(
            f"BlueStacks acquisition produced no manifest: {completed.stderr.strip() or completed.stdout.strip()}"
        )
    document = _load_json_object(manifest, "BlueStacks snapshot manifest")
    if document.get("status") != "complete":
        raise PipelineError("BlueStacks acquisition is incomplete; extraction was not started")
    files = document.get("files")
    if not isinstance(files, list) or not files:
        raise PipelineError("BlueStacks acquisition completed without files")
    paths: list[Path] = []
    acquisition_root = acquisition_root.resolve()
    for row in files:
        if not isinstance(row, dict):
            raise PipelineError("BlueStacks acquisition files[] must contain objects")
        raw_local_path = row.get("local_path")
        if not isinstance(raw_local_path, str) or not raw_local_path.strip():
            raise PipelineError("BlueStacks acquisition file has no local_path")
        local_path = Path(raw_local_path)
        if local_path.is_absolute():
            raise PipelineError("BlueStacks acquisition local_path must be relative")
        candidate = acquisition_root / local_path
        current = candidate
        while current != acquisition_root:
            if current.is_symlink():
                raise PipelineError(
                    f"BlueStacks acquisition path contains a symlink: {raw_local_path}"
                )
            current = current.parent
        resolved_path = candidate.resolve()
        try:
            resolved_path.relative_to(acquisition_root)
        except ValueError as exc:
            raise PipelineError(
                f"BlueStacks acquisition path escapes snapshot root: {raw_local_path}"
            ) from exc
        if not resolved_path.is_file() or resolved_path.is_symlink():
            raise PipelineError(
                f"BlueStacks acquisition file is missing or unsafe: {resolved_path}"
            )
        expected_bytes = row.get("bytes")
        expected_sha256 = row.get("sha256")
        actual_bytes = resolved_path.stat().st_size
        actual_sha256 = sha256_file(resolved_path)
        if actual_bytes != expected_bytes or actual_sha256 != expected_sha256:
            raise PipelineError(
                f"BlueStacks acquisition file changed after capture: {resolved_path}"
            )
        paths.append(resolved_path)
    return paths, _result(
        "complete" if completed.returncode == 0 else "partial",
        manifest,
        method="adb-pull-read-only",
        source_count=len(paths),
        returncode=completed.returncode,
    )


def _build_assets_manifest(classification: dict[str, Any], output: Path) -> dict[str, Any]:
    assets = []
    for index, row in enumerate(classification.get("outputs", [])):
        if not isinstance(row, dict):
            continue
        assets.append(
            {
                "input_index": index,
                "asset_id": row.get("asset_id") or row.get("sha256"),
                "logical_path": row.get("logical_path") or row.get("path"),
                "logical_path_status": row.get("logical_path_status"),
                "asset_type": row.get("category", "unknown"),
                "path": row.get("path"),
                "output_path": row.get("path"),
                "sha256": row.get("sha256"),
                "bytes": row.get("bytes"),
                "classification": row.get("evidence"),
            }
        )
    document = {
        "schema_version": 1,
        "operation": "build-assets-for-matching",
        "created_at": utc_now(),
        "source_classification": str(output.parent.joinpath("type-classification.json").resolve()),
        "assets": assets,
    }
    atomic_write_json(output, document)
    return document


def _write_publication_inputs(
    run_root: Path,
    extraction: dict[str, Any],
    source_manifest: Path,
) -> None:
    """Bridge the normalized extraction manifest into the existing NeoX stage."""

    raw_manifest = {
        "schema_version": 1,
        "stage": "raw-extraction",
        "status": extraction.get("status"),
        "source_manifest": str(source_manifest.resolve()),
        "entry_count": len(extraction.get("entries", [])),
        "outputs": extraction.get("entries", []),
        "raw_outputs_immutable": True,
    }
    atomic_write_json(run_root / "raw-extraction-manifest.json", raw_manifest)
    atomic_write_json(
        run_root / "differential.json",
        {
            "schema_version": 1,
            "stage": "differential",
            "status": "not-run",
            "reason": "single configured backend pipeline; differential backend comparison is opt-in",
        },
    )


def _request_for_sources(
    config: dict[str, Any], config_dir: Path, sources: Iterable[Path], output: Path
) -> BackendRequest:
    return BackendRequest(
        source_paths=tuple(sources),
        output=output,
        backend=str(config.get("backend", "builtin")),
        game_profile=str(config.get("game_profile", "onmyoji")),
        profile=str(config.get("profile", "auto")),
        strict=not bool(config.get("best_effort", False)),
        neoxtractor_root=_path(config["neoxtractor_root"], config_dir, "neoxtractor_root")
        if config.get("neoxtractor_root")
        else None,
        neoxtractor_config=_path(config["neoxtractor_config"], config_dir, "neoxtractor_config")
        if config.get("neoxtractor_config")
        else None,
        neox_tools_root=_path(config["neox_tools_root"], config_dir, "neox_tools_root")
        if config.get("neox_tools_root")
        else None,
        backend_python=_path(config["backend_python"], config_dir, "backend_python")
        if config.get("backend_python")
        else None,
    )


def _request_for_source(
    config: dict[str, Any], config_dir: Path, source: Path, output: Path
) -> BackendRequest:
    return _request_for_sources(config, config_dir, (source,), output)


def _rebase_entries(
    manifest: dict[str, Any],
    source_run: Path,
    combined_root: Path,
    source_input_index: int,
) -> list[dict[str, Any]]:
    outputs = manifest.get("outputs")
    declared_root = outputs.get("directory") if isinstance(outputs, dict) else None
    old_root = Path(str(declared_root)).resolve() if declared_root else source_run.resolve()
    rebased: list[dict[str, Any]] = []
    for raw in manifest.get("entries", []):
        if not isinstance(raw, dict):
            continue
        if not raw.get("output_path") or raw.get("status") in {"failed", "error"}:
            continue
        entry = dict(raw)
        output_path = Path(str(entry.get("output_path", "")))
        actual = (old_root / output_path).resolve()
        try:
            entry["output_path"] = actual.relative_to(combined_root.resolve()).as_posix()
        except ValueError as exc:
            raise PipelineError(
                f"backend output escaped combined extraction root: {actual}"
            ) from exc
        entry["source_input_index"] = source_input_index
        rebased.append(entry)
    return rebased


def _extract_sources(
    config: dict[str, Any], config_dir: Path, sources: list[Path], output: Path
) -> dict[str, Any]:
    """Run one builtin request or one isolated dedicated request per source."""

    backend = str(config.get("backend", "builtin"))
    if backend == "builtin" or len(sources) == 1:
        return extract_with_backend(_request_for_sources(config, config_dir, sources, output), None)

    combined_entries: list[dict[str, Any]] = []
    source_runs: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, source in enumerate(sources):
        source_run = output / f"source-{index:04d}"
        manifest = extract_with_backend(
            _request_for_source(config, config_dir, source, source_run), None
        )
        combined_entries.extend(_rebase_entries(manifest, source_run, output, index))
        source_info = manifest.get("source")
        manifest_name = (
            "backend-run-manifest.json"
            if (source_run / "backend-run-manifest.json").is_file()
            else "run-manifest.json"
        )
        source_runs.append(
            {
                "source": str(source.resolve()),
                "manifest": str((source_run / manifest_name).resolve()),
                "sha256_before": source_info.get("sha256_before")
                if isinstance(source_info, dict)
                else None,
                "sha256_after": source_info.get("sha256_after")
                if isinstance(source_info, dict)
                else None,
                "unchanged": source_info.get("unchanged")
                if isinstance(source_info, dict)
                else None,
                "status": manifest.get("status"),
            }
        )
        failures.extend(manifest.get("failures", []))
    status = (
        "complete"
        if combined_entries and not failures
        else "partial"
        if combined_entries
        else "failed"
    )
    combined = {
        "schema_version": 1,
        "operation": "extract-backend-collection",
        "created_at": utc_now(),
        "status": status,
        "tool": tool_metadata(),
        "backend": backend,
        "source_count": len(source_runs),
        "sources": source_runs,
        "output_directory": str(output.resolve()),
        "entries": combined_entries,
        "failures": failures,
        "claims": [
            {
                "claim": "dedicated backend outputs were rebased into one pipeline run",
                "certainty": "fact",
            }
        ],
    }
    atomic_write_json(output / "backend-runs-manifest.json", combined)
    return combined


def _run_textured_stage(run_root: Path, config_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    source_tree = _path(config.get("source_tree"), config_dir, "textured.source_tree")
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
            ("--catalog-run", str(_path(catalog, config_dir, "textured.catalog_runs[]")))
        )
    if config.get("allow_equivalent_material_duplicates", False):
        arguments.append("--allow-equivalent-material-duplicates")
    for mesh_sha in config.get("only_mesh_sha256", []):
        arguments.extend(("--only-mesh-sha256", str(mesh_sha)))
    if config.get("material_overrides"):
        arguments.extend(
            (
                "--material-overrides",
                str(_path(config["material_overrides"], config_dir, "textured.material_overrides")),
            )
        )
    if config.get("runtime_python"):
        arguments.extend(
            (
                "--runtime-python",
                str(_path(config["runtime_python"], config_dir, "textured.runtime_python")),
            )
        )
    completed = _run_python(script, arguments)
    manifest = output / "textured-static-manifest.json"
    if not manifest.is_file():
        return _result(
            "failed",
            returncode=completed.returncode,
            error=completed.stderr.strip() or completed.stdout.strip(),
        )
    document = json.loads(manifest.read_text(encoding="utf-8"))
    return _result(str(document.get("status", "failed")), manifest, returncode=completed.returncode)


def _run_render_stage(
    run_root: Path, textured: dict[str, Any]
) -> tuple[dict[str, Any], list[Path]]:
    if textured.get("status") not in {"complete", "partial"} or not textured.get("manifest"):
        return _result("skipped", reason="textured stage did not publish a manifest"), []
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
        completed = _run_python(script, [str(source), str(target)])
        if completed.returncode == 0 and target.is_file():
            rendered.append(target)
        else:
            failures.append(completed.stderr.strip() or f"renderer failed: {source}")
    status = "complete" if rendered and not failures else "partial" if rendered else "failed"
    return _result(
        status, output=str(render_root.resolve()), rendered=len(rendered), failures=failures
    ), rendered


def _run_visual_stage(config: Any, config_dir: Path, rendered: Iterable[Path]) -> dict[str, Any]:
    if config is None:
        return _result("skipped", reason="no reference images configured")
    if not isinstance(config, list) or not config:
        return _result("failed", reason="references must be a non-empty array")
    candidates = list(rendered)
    results: list[dict[str, Any]] = []
    for index, raw in enumerate(config):
        if isinstance(raw, str):
            reference = _path(raw, config_dir, f"references[{index}]")
            selected_candidates = candidates
        elif isinstance(raw, dict):
            reference = _path(raw.get("path"), config_dir, f"references[{index}].path")
            configured = raw.get("candidates")
            selected_candidates = (
                [
                    _path(item, config_dir, f"references[{index}].candidates[]")
                    for item in configured
                ]
                if isinstance(configured, list)
                else candidates
            )
        else:
            raise PipelineError(f"references[{index}] must be a path or object")
        if not reference.is_file():
            raise PipelineError(f"reference image is missing: {reference}")
        comparisons = [
            compare_images(reference, candidate)
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
    status = (
        "complete"
        if results and all(item["accepted"] is not None for item in results)
        else "partial"
    )
    return _result(
        status,
        count=len(results),
        results=results,
        policy="ranking evidence; never rewrites UV/material bindings",
    )


def run_pipeline(config_path: Path, output: Path) -> dict[str, Any]:
    config_path = config_path.resolve()
    output = output.resolve()
    if output.exists():
        raise PipelineError(f"pipeline output already exists: {output}")
    config = _load_config(config_path)
    output.mkdir(parents=True)
    config_dir = config_path.parent
    stages: dict[str, Any] = {}
    try:
        sources, acquisition = _source_paths(config, config_dir, output)
        stages["acquisition"] = acquisition
        extraction = _extract_sources(config, config_dir, sources, output / "extraction")
        extraction_manifest = next(
            (
                output / "extraction" / filename
                for filename in (
                    "run-manifest.json",
                    "backend-run-manifest.json",
                    "backend-runs-manifest.json",
                )
                if (output / "extraction" / filename).is_file()
            ),
            output / "extraction" / "run-manifest.json",
        )
        stages["extraction"] = _result(
            str(extraction.get("status", "failed")),
            extraction_manifest,
            entries=len(extraction.get("entries", [])),
        )
        _write_publication_inputs(output, extraction, extraction_manifest)
        classification = classify_manifest_entries(
            run_root=output,
            source_manifest=extraction,
            output_manifest=output / "type-classification.json",
            raw_manifest=output / "raw-extraction-manifest.json",
            source_output_root=output / "extraction",
        )
        stages["classification"] = _result(
            str(classification.get("status", "failed")),
            output / "type-classification.json",
            counts=classification.get("counts", {}),
        )
        _build_assets_manifest(classification, output / "assets.json")
        dictionary = config.get("dictionary")
        if dictionary:
            dictionary_path = _path(dictionary, config_dir, "dictionary")
            match = build_match_manifest(dictionary_path, output / "assets.json")
            atomic_write_json(output / "match-manifest.json", match)
            stages["matching"] = _result(
                "complete", output / "match-manifest.json", summary=match["summary"]
            )
        else:
            stages["matching"] = _result("skipped", reason="no dictionary configured")
        textured_config = config.get("textured")
        if textured_config is not None:
            if not isinstance(textured_config, dict):
                raise PipelineError("textured must be an object")
            stages["textured"] = _run_textured_stage(output, config_dir, textured_config)
        else:
            stages["textured"] = _result("skipped", reason="no NeoX publication configuration")
        stages["rendering"], rendered = _run_render_stage(output, stages["textured"])
        stages["visual"] = _run_visual_stage(config.get("references"), config_dir, rendered)
        required = [
            "acquisition",
            "extraction",
            "classification",
            "matching",
            "textured",
            "rendering",
            "visual",
        ]
        status = (
            "complete"
            if all(stages[name].get("status") == "complete" for name in required)
            else "partial"
        )
    except (OSError, PipelineError, ExtractionError, ValueError, json.JSONDecodeError) as exc:
        stages["error"] = {"status": "failed", "message": str(exc)}
        status = "failed"
    manifest = {
        "schema_version": 1,
        "operation": "asset-extraction-pipeline",
        "created_at": utc_now(),
        "status": status,
        "config": {"path": str(config_path), "sha256": sha256_file(config_path)},
        "tool": tool_metadata(),
        "stages": stages,
        "policy": {
            "raw_inputs_read_only": True,
            "reference_images_rank_candidates_only": True,
            "ambiguous_results_remain_unresolved": True,
        },
    }
    atomic_write_json(output / "pipeline-manifest.json", manifest)
    return manifest
