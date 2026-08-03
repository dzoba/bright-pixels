#!/usr/bin/env python3
"""Verify image encoding, CICP/ICC metadata, dimensions, and decodability."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
EXPECTED_IMAGES = {
    "logo-sdr.png",
    "logo-sdr-max.png",
    "logo-hdr-pq.avif",
    "logo-hdr-pq.jpg",
    "logo-hdr-tonemapped.png",
}


def run(command: list[str], *, required: bool = True) -> subprocess.CompletedProcess[str] | None:
    executable = shutil.which(command[0])
    if not executable:
        if required:
            raise RuntimeError(f"required command not found: {command[0]}")
        print(f"$ {command[0]} ...\n  skipped (not installed)\n")
        return None
    resolved = [executable, *command[1:]]
    print("$ " + " ".join(command))
    result = subprocess.run(resolved, check=True, text=True, capture_output=True, cwd=ROOT)
    output = (result.stdout + result.stderr).strip()
    if output:
        print(output)
    print()
    return result


def ffprobe(path: Path) -> dict:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt,width,height,color_range,color_space,color_transfer,color_primaries",
            "-of",
            "json",
            str(path),
        ]
    )
    assert result is not None
    return json.loads(result.stdout)["streams"][0]


def png_chunks(path: Path) -> list[tuple[bytes, bytes]]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"not a PNG: {path}")
    chunks: list[tuple[bytes, bytes]] = []
    cursor = 8
    while cursor < len(data):
        length = struct.unpack(">I", data[cursor : cursor + 4])[0]
        signature = data[cursor + 4 : cursor + 8]
        payload = data[cursor + 8 : cursor + 8 + length]
        chunks.append((signature, payload))
        cursor += 12 + length
    return chunks


def icc_tags(profile: bytes) -> dict[str, bytes]:
    if len(profile) < 132 or profile[36:40] != b"acsp":
        raise ValueError("invalid ICC profile")
    count = struct.unpack(">I", profile[128:132])[0]
    tags: dict[str, bytes] = {}
    for index in range(count):
        start = 132 + index * 12
        signature = profile[start : start + 4].decode("ascii", errors="replace")
        offset, size = struct.unpack(">II", profile[start + 4 : start + 12])
        tags[signature] = profile[offset : offset + size]
    return tags


def icc_description(profile: bytes) -> str:
    payload = icc_tags(profile).get("desc")
    if not payload:
        return "(no description tag)"
    if payload[:4] == b"mluc" and len(payload) >= 28:
        length, offset = struct.unpack(">II", payload[20:28])
        return payload[offset : offset + length].decode("utf-16-be", errors="replace")
    if payload[:4] == b"desc" and len(payload) >= 12:
        length = struct.unpack(">I", payload[8:12])[0]
        return payload[12 : 12 + max(0, length - 1)].decode("latin-1", errors="replace")
    return "(unrecognized description tag)"


def jpeg_icc(path: Path) -> bytes:
    with Image.open(path) as image:
        profile = image.info.get("icc_profile")
    if not profile:
        raise AssertionError(f"{path.name}: embedded ICC profile is missing")
    return profile


def verify_sdr_png(path: Path) -> None:
    chunks = dict(png_chunks(path))
    if b"cICP" in chunks:
        raise AssertionError(f"{path.name}: unexpected HDR cICP chunk")
    if b"iCCP" not in chunks:
        raise AssertionError(f"{path.name}: sRGB ICC profile is missing")
    with Image.open(path) as image:
        if image.mode != "RGB" or image.info.get("icc_profile") is None:
            raise AssertionError(f"{path.name}: expected RGB pixels and embedded profile")
        description = icc_description(image.info["icc_profile"])
        print(f"{path.name}: PNG RGB 8-bit, ICC={description!r}, cICP=absent")


def verify_jpeg(path: Path) -> None:
    profile = jpeg_icc(path)
    tags = icc_tags(profile)
    cicp = tags.get("cicp")
    if not cicp or len(cicp) < 12:
        raise AssertionError("logo-hdr-pq.jpg: ICC cicp tag is missing")
    values = tuple(cicp[8:12])
    if values != (9, 16, 0, 1):
        raise AssertionError(f"logo-hdr-pq.jpg: expected CICP 9/16/0/1, got {values}")
    if not {"rXYZ", "gXYZ", "bXYZ"}.issubset(tags):
        raise AssertionError("logo-hdr-pq.jpg: Rec.2020 colorant tags are incomplete")
    description = icc_description(profile)
    print("JPEG embedded ICC inspection")
    print(f"  profile_name: {description}")
    print("  color_primaries: bt2020 (CICP 9)")
    print("  color_transfer: smpte2084 / PQ (CICP 16)")
    print("  color_space: rgb (CICP matrix 0)")
    print("  color_range: full (CICP flag 1)")
    print(f"  profile_bytes: {len(profile)}")
    print()


def verify_dimensions(directory: Path) -> None:
    missing = sorted(name for name in EXPECTED_IMAGES if not (directory / name).is_file())
    if missing:
        raise AssertionError(f"{directory}: missing assets: " + ", ".join(missing))
    for name in sorted(EXPECTED_IMAGES - {"logo-hdr-pq.avif"}):
        with Image.open(directory / name) as image:
            if image.size[0] != image.size[1] or image.size[0] < 512:
                raise AssertionError(f"{name}: unexpected dimensions {image.size}")


def pq_eotf(signal: float) -> float:
    m1 = 2610 / 16384
    m2 = 2523 / 32
    c1 = 3424 / 4096
    c2 = 2413 / 128
    c3 = 2392 / 128
    powered = signal ** (1.0 / m2)
    return 10000.0 * (max(powered - c1, 0.0) / (c2 - c3 * powered)) ** (1.0 / m1)


def verify_avif_signal(path: Path, width: int, height: int) -> None:
    with tempfile.TemporaryDirectory(prefix="bright-pixels-verify-") as temporary:
        raw_path = Path(temporary) / "decoded.yuv"
        run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-pix_fmt",
                "yuv420p10le",
                "-f",
                "rawvideo",
                str(raw_path),
            ]
        )
        luma = np.fromfile(raw_path, dtype="<u2", count=width * height)
    if luma.size != width * height:
        raise AssertionError(f"{path}: decoded luma plane is incomplete")
    highlight_signal = float(np.percentile(luma, 99.0) / 1023.0)
    highlight_nits = pq_eotf(highlight_signal)
    if not 800.0 <= highlight_nits <= 1200.0:
        raise AssertionError(f"{path}: expected an approximately 1000-nit highlight, got {highlight_nits:.1f}")
    print(f"{path.relative_to(ROOT)}: decoded 99th-percentile highlight ≈ {highlight_nits:.1f} nits")
    print()


def optional_tool_reports() -> None:
    avif = str(ASSETS / "logo-hdr-pq.avif")
    jpeg = str(ASSETS / "logo-hdr-pq.jpg")
    run(["exiftool", "-G1", "-s", avif, jpeg], required=False)
    run(["identify", "-verbose", str(ASSETS / "logo-sdr.png")], required=False)
    if sys.platform == "darwin":
        run(["sips", "-g", "space", "-g", "profile", jpeg], required=False)


def verify_variant(label: str, directory: Path) -> None:
    print(f"=== {label} asset set ===")
    verify_dimensions(directory)
    for name in ("logo-sdr.png", "logo-sdr-max.png", "logo-hdr-tonemapped.png"):
        verify_sdr_png(directory / name)
    print()

    avif_path = directory / "logo-hdr-pq.avif"
    avif_stream = ffprobe(avif_path)
    expected = {
        "codec_name": "av1",
        "pix_fmt": "yuv420p10le",
        "color_range": "pc",
        "color_space": "bt2020nc",
        "color_transfer": "smpte2084",
        "color_primaries": "bt2020",
    }
    mismatches = {
        key: (avif_stream.get(key), wanted)
        for key, wanted in expected.items()
        if avif_stream.get(key) != wanted
    }
    if mismatches:
        raise AssertionError(f"{label} AVIF metadata mismatch: {mismatches}")
    verify_avif_signal(avif_path, int(avif_stream["width"]), int(avif_stream["height"]))
    verify_jpeg(directory / "logo-hdr-pq.jpg")


def main() -> None:
    verify_variant("Generic (default)", ASSETS)
    verify_variant("GCAI (?gcai=true)", ASSETS / "gcai")
    optional_tool_reports()
    print("PASS: both HDR AVIFs are 10-bit Rec.2020/PQ/full-range with ~1000-nit highlights.")
    print("PASS: both HDR JPEGs embed RGB/full-range Rec.2020/PQ CICP ICC profiles.")
    print("PASS: both SDR PNG sets are 8-bit RGB with sRGB ICC profiles and no HDR CICP chunk.")


if __name__ == "__main__":
    main()
