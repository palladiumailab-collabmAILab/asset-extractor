"""Final non-destructive audit for the APK -> Blender -> UE probe pipeline."""

from __future__ import annotations

import json
import py_compile
import sys
from pathlib import Path


ROOT = Path(r"C:\Users\palla\Documents\resource\OnmyojiAPK")
PROJECT = Path(r"C:\Users\palla\Documents\astra-blender-lab\JadeLanternGarden")
REPORT = ROOT / "reports" / "apk_conversion_final_check.json"


def check(name, condition, detail):
    return {"check": name, "status": "PASS" if condition else "FAIL", "detail": detail}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    checks = []
    mesh = ROOT / "extracted/extrares_stage_refs/res/Mesh/152015_ffffffffe0e09138.mesh"
    ktx = ROOT / "extracted/extrares_stage_refs/res/Texture/022827_43c8e588395df7f2.ktx"
    gltf = ROOT / "converted/native_format_probe/152015_ffffffffe0e09138_textured.gltf"
    png = ROOT / "converted/native_format_probe/022827_43c8e588395df7f2.png"
    blend = ROOT / "blender/validation/native_format_probe_textured.blend"
    render = ROOT / "blender/validation/native_format_probe_textured_render.png"
    blender_report = ROOT / "blender/validation/native_format_probe_textured_report.json"
    ue_report = PROJECT / "Docs/apk_textured_probe_report.json"
    ue_verify = PROJECT / "Docs/apk_textured_probe_verify_report.json"
    batch_root = ROOT / "converted/batch_restore/q_dashezhandou_all_colorized_v4fixed"
    batch_manifest = batch_root / "batch_manifest.json"
    batch_unresolved = batch_root / "unresolved.json"
    batch_gltf = batch_root / "gltf"
    batch_blend = ROOT / "blender/validation/q_dashezhandou_v4fixed_cao02.blend"
    checks.append(check("source_mesh_present", mesh.is_file(), str(mesh)))
    checks.append(check("source_ktx_present", ktx.is_file(), str(ktx)))
    checks.append(check("colored_gltf_present", gltf.is_file(), str(gltf)))
    checks.append(check("colored_png_present", png.is_file(), str(png)))
    try:
        doc = read_json(gltf)
        images = doc.get("images") or []
        materials = doc.get("materials") or []
        primitives = [p for m in doc.get("meshes") or [] for p in m.get("primitives") or []]
        ok = bool(images and materials and primitives and all("material" in p for p in primitives))
        checks.append(check("gltf_material_image_links", ok, "images={},materials={},primitives={}".format(len(images), len(materials), len(primitives))))
    except Exception as exc:
        checks.append(check("gltf_material_image_links", False, repr(exc)))
    checks.append(check("blender_blend_present", blend.is_file(), str(blend)))
    checks.append(check("blender_render_present", render.is_file(), str(render)))
    try:
        report = read_json(blender_report)
        ok = report.get("materials", 0) >= 2 and report.get("presentation_material") == "NeoXColorizedFallback" and report.get("images", 0) >= 1 and Path(report.get("render", "")).is_file()
        checks.append(check("blender_material_render", ok, json.dumps({k: report.get(k) for k in ("meshes", "materials", "images", "render")}, ensure_ascii=False)))
    except Exception as exc:
        checks.append(check("blender_material_render", False, repr(exc)))
    for label, path in (("ue_import_report", ue_report), ("ue_verify_report", ue_verify)):
        try:
            value = read_json(path)
            checks.append(check(label, value.get("ok") is True, str(path)))
        except Exception as exc:
            checks.append(check(label, False, repr(exc)))
    try:
        batch = read_json(batch_manifest)
        gltf_files = list(batch_gltf.glob("*.gltf"))
        colored = 0
        for path in gltf_files:
            doc = read_json(path)
            if (doc.get("materials") or [{}])[0].get("name") == "NeoXColorizedFallback":
                colored += 1
        ok = (
            batch.get("scene_unique_gim_count") == 95
            and batch.get("scene_model_instance_count") == 210
            and batch.get("converted_mesh_count") == 92
            and len(gltf_files) == 92
            and colored == 92
            and batch_unresolved.is_file()
        )
        checks.append(check("scene_batch_restore", ok, json.dumps({"unique_gim": batch.get("scene_unique_gim_count"), "instances": batch.get("scene_model_instance_count"), "converted": batch.get("converted_mesh_count"), "gltf": len(gltf_files), "colored": colored}, ensure_ascii=False)))
        checks.append(check("v4_batch_blender_import", batch_blend.is_file(), str(batch_blend)))
    except Exception as exc:
        checks.append(check("scene_batch_restore", False, repr(exc)))
    scripts = [
        ROOT / "tools/extract_nxpk.py",
        ROOT / "tools/convert_mesh_to_gltf.py",
        ROOT / "tools/convert_mesh_to_gltf_safe.py",
        ROOT / "tools/find_stage_asset_chain.py",
        ROOT / "tools/build_textured_gltf_sample.py",
        ROOT / "tools/batch_restore_assets.py",
        ROOT / "tools/NeoXtractor-source-v3.2/core/mesh_loader/parsers/new_parser.py",
        ROOT / "tools/NeoXtractor-source-v3.2/core/mesh_converter/formats/gltf.py",
        ROOT / "tools/blender_validate_textured_gltf.py",
        PROJECT / "Tools/Unreal/import_apk_textured_probe.py",
        PROJECT / "Tools/Unreal/verify_apk_textured_probe.py",
    ]
    compile_errors = []
    for script in scripts:
        try:
            py_compile.compile(str(script), doraise=True)
        except Exception as exc:
            compile_errors.append("{}: {}".format(script, exc))
    checks.append(check("conversion_scripts_compile", not compile_errors, "; ".join(compile_errors) or f"{len(scripts)} scripts"))
    result = {
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "overall": "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL",
        "checks": checks,
        "scope": "native NeoX mesh + KTX -> textured glTF/GLB -> Blender -> Unreal probe",
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
