"""Small, dependency-free media probes shared by all extraction stages.

The probe deliberately answers only what can be established from a bounded
prefix.  It is a classifier, not a decoder: callers that need stronger
evidence should open the payload with Pillow, PyAV, or the game-specific
decoder after this step.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _result(format_id: str, family: str, mime: str, method: str = "magic") -> dict[str, Any]:
    return {
        "format": format_id,
        "family": family,
        "mime": mime,
        "method": method,
    }


def probe_bytes(sample: bytes) -> dict[str, Any]:
    """Classify a payload from its first bytes.

    Format ids are intentionally stable because they are persisted in run
    manifests and consumed by the minimal restore verifier.
    """

    if sample.startswith(b"NXPK"):
        return _result("nxpk", "archive", "application/x-neox-nxpk")
    if sample.startswith(b"PK\x03\x04"):
        return _result("zip", "archive", "application/zip")

    if sample.startswith(b"\x89PNG\r\n\x1a\n"):
        return _result("png", "image", "image/png")
    if sample.startswith(b"\xff\xd8\xff"):
        return _result("jpeg", "image", "image/jpeg")
    if sample.startswith((b"GIF87a", b"GIF89a")):
        return _result("gif", "image", "image/gif")
    if sample.startswith(b"BM"):
        return _result("bmp", "image", "image/bmp")
    if sample.startswith((b"II*\x00", b"MM\x00*")):
        return _result("tiff", "image", "image/tiff")
    if len(sample) >= 12 and sample[:4] == b"RIFF" and sample[8:12] == b"WEBP":
        return _result("webp", "image", "image/webp")
    if sample.startswith(b"DDS "):
        return _result("dds", "texture", "image/vnd-ms.dds")
    if sample.startswith(b"\xabKTX 11\xbb\r\n\x1a\n"):
        return _result("ktx", "texture", "image/ktx")
    if sample.startswith(b"\xabKTX 20\xbb\r\n\x1a\n"):
        return _result("ktx2", "texture", "image/ktx2")
    if sample.startswith(b"PVR\x03") or (
        len(sample) >= 52 and sample[:4] == b"\x03\x00\x00\x00"
    ):
        return _result("pvr", "texture", "image/x-pvr")

    if len(sample) >= 12 and sample[4:8] == b"ftyp":
        return _result("iso-bmff", "video", "video/mp4")
    if len(sample) >= 12 and sample[:4] == b"RIFF" and sample[8:12] == b"AVI ":
        return _result("avi", "video", "video/x-msvideo")
    if sample.startswith(b"\x1a\x45\xdf\xa3"):
        return _result("ebml", "video", "video/x-matroska")
    if sample.startswith(b"OggS"):
        return _result("ogg", "audio", "audio/ogg")
    if sample.startswith(b"FSB"):
        return _result("fsb", "audio", "audio/x-fsb")

    if sample.startswith(b"glTF"):
        return _result("glb", "3d", "model/gltf-binary")
    if sample.startswith(b"UnityFS"):
        return _result("unity3d", "3d-container", "application/octet-stream")
    if sample.startswith(b"\x34\x80\xc8\xbb"):
        return _result("neox-mesh", "3d", "application/x-neox-mesh")
    if sample.startswith(b"Kaydara FBX Binary"):
        return _result("fbx", "3d", "application/octet-stream")

    stripped = sample.lstrip()
    if stripped.startswith(b"<"):
        if b"<Material" in sample or b">Material" in sample:
            return _result("xml-material", "material", "application/xml", "xml-signature")
        if b"AnimationConfig" in sample or b"<Track" in sample:
            return _result("xml-animation", "animation", "application/xml", "xml-signature")
        if b"<Scene" in sample:
            return _result("xml-scene", "scene", "application/xml", "xml-signature")
        if b"<?xml" in sample or b"<NeoX" in sample:
            return _result("xml", "document", "application/xml", "xml-signature")
    if stripped.startswith(b"{"):
        return _result("json", "document", "application/json", "json-signature")

    return _result("unknown", "unknown", "application/octet-stream", "none")


def probe_file(path: Path, read_bytes: int = 4096) -> dict[str, Any]:
    """Probe a regular file without reading it in full."""

    with path.open("rb") as handle:
        return probe_bytes(handle.read(read_bytes))
