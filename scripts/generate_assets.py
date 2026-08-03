#!/usr/bin/env python3
"""Generate generic and GCAI SDR/HDR assets from linear-light artwork.

The source artwork is constructed as float64 Rec.2020 RGB values measured in
cd/m² (nits). SDR files are converted to sRGB. HDR files are encoded with the
SMPTE ST 2084 (PQ) OETF and explicit Rec.2020/PQ CICP metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
DEFAULT_LOGO_SOURCE = ASSETS / "source" / "gcai.avif"
DEFAULT_SIZE = 1024
DEFAULT_PEAK_NITS = 1000.0
SDR_REFERENCE_NITS = 203.0

# SMPTE ST 2084 constants.
PQ_M1 = 2610 / 16384
PQ_M2 = 2523 / 32
PQ_C1 = 3424 / 4096
PQ_C2 = 2413 / 128
PQ_C3 = 2392 / 128

# Linear Rec.2020 (D65) -> XYZ and XYZ -> linear sRGB (D65).
REC2020_TO_XYZ = np.array(
    [
        [0.6369580483, 0.1446169036, 0.1688809752],
        [0.2627002120, 0.6779980715, 0.0593017165],
        [0.0000000000, 0.0280726930, 1.0609850577],
    ],
    dtype=np.float64,
)
XYZ_TO_SRGB = np.array(
    [
        [3.2404542, -1.5371385, -0.4985314],
        [-0.9692660, 1.8760108, 0.0415560],
        [0.0556434, -0.2040259, 1.0572252],
    ],
    dtype=np.float64,
)

# Rec.2020 -> XYZ D50 matrix used by Skia/skcms after chromatic adaptation.
REC2020_TO_XYZ_D50 = np.array(
    [
        [0.6734590, 0.1656610, 0.1251000],
        [0.2790330, 0.6753380, 0.0456288],
        [-0.00193139, 0.0299794, 0.7971620],
    ],
    dtype=np.float64,
)


def pq_oetf(nits: np.ndarray | float) -> np.ndarray:
    """Map absolute luminance in nits to a normalized PQ signal."""

    normalized = np.clip(np.asarray(nits, dtype=np.float64) / 10000.0, 0.0, 1.0)
    powered = np.power(normalized, PQ_M1)
    return np.power((PQ_C1 + PQ_C2 * powered) / (1.0 + PQ_C3 * powered), PQ_M2)


def pq_eotf(signal: np.ndarray | float) -> np.ndarray:
    """Map a normalized PQ signal to absolute luminance in nits."""

    encoded = np.clip(np.asarray(signal, dtype=np.float64), 0.0, 1.0)
    powered = np.power(encoded, 1.0 / PQ_M2)
    numerator = np.maximum(powered - PQ_C1, 0.0)
    denominator = PQ_C2 - PQ_C3 * powered
    return 10000.0 * np.power(numerator / denominator, 1.0 / PQ_M1)


def srgb_eotf(encoded: np.ndarray) -> np.ndarray:
    encoded = np.clip(encoded, 0.0, 1.0)
    return np.where(
        encoded <= 0.04045,
        encoded / 12.92,
        np.power((encoded + 0.055) / 1.055, 2.4),
    )


def resize_linear_rgb(linear_rgb: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Lanczos-resize RGB channels as float32 while values are in linear light."""

    channels = []
    for channel in range(3):
        plane = Image.fromarray(linear_rgb[..., channel].astype(np.float32), mode="F")
        resized = plane.resize(size, resample=Image.Resampling.LANCZOS)
        channels.append(np.asarray(resized, dtype=np.float64))
    return np.stack(channels, axis=-1)


def validate_size(size: int) -> None:
    if size < 512 or size % 2:
        raise ValueError("--size must be an even integer of at least 512")


def mask_to_linear_artwork(mask: np.ndarray, peak_nits: float) -> np.ndarray:
    """Map coverage to an absolute-luminance, float64 Rec.2020 source."""

    background_nits = np.array([1.5, 7.5, 11.0], dtype=np.float64)
    foreground_nits = np.array([peak_nits, peak_nits, peak_nits], dtype=np.float64)
    return background_nits + mask[..., None] * (foreground_nits - background_nits)


def build_generic_linear_artwork(size: int, peak_nits: float) -> np.ndarray:
    """Build a neutral, logo-esque pixel aperture with no brand identity."""

    validate_size(size)
    mask = np.zeros((size, size), dtype=np.float64)
    pattern = (
        "00100",
        "01110",
        "11011",
        "01110",
        "00100",
    )
    block = round(size * 0.118)
    gap = round(size * 0.028)
    total = block * 5 + gap * 4
    left = (size - total) // 2
    top = (size - total) // 2
    stride = block + gap
    for row, bits in enumerate(pattern):
        for column, bit in enumerate(bits):
            if bit == "1":
                x0 = left + column * stride
                y0 = top + row * stride
                mask[y0 : y0 + block, x0 : x0 + block] = 1.0
    return mask_to_linear_artwork(mask, peak_nits)


def build_gcai_linear_artwork(size: int, peak_nits: float, logo_source: Path) -> np.ndarray:
    """Build the optional GCAI variant as float64 linear Rec.2020 nits."""

    validate_size(size)

    if not logo_source.is_file():
        raise FileNotFoundError(f"logo source not found: {logo_source}")

    with Image.open(logo_source) as source_image:
        rgba = np.asarray(source_image.convert("RGBA"), dtype=np.float64) / 255.0

    # Composite transparency over the supplied logo's corner color, decode
    # sRGB, and resize while still in high-precision linear light.
    corner_rgb = np.median(
        np.concatenate(
            (
                rgba[:8, :8, :3].reshape(-1, 3),
                rgba[:8, -8:, :3].reshape(-1, 3),
                rgba[-8:, :8, :3].reshape(-1, 3),
                rgba[-8:, -8:, :3].reshape(-1, 3),
            )
        ),
        axis=0,
    )
    encoded_rgb = rgba[..., :3] * rgba[..., 3:4] + corner_rgb * (1.0 - rgba[..., 3:4])
    linear_srgb = srgb_eotf(encoded_rgb)

    source_height, source_width = linear_srgb.shape[:2]
    target_width = round(size * 0.88)
    target_height = round(target_width * source_height / source_width)
    if target_height > round(size * 0.72):
        target_height = round(size * 0.72)
        target_width = round(target_height * source_width / source_height)
    fitted = resize_linear_rgb(linear_srgb, (target_width, target_height))

    # The supplied artwork is a flat light mark on a flat dark field. Convert
    # its linear luminance into a precise coverage mask, retaining antialiased
    # edge coverage without carrying over its 8-bit transfer encoding.
    luminance = fitted @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)
    border = np.concatenate(
        (luminance[:4].ravel(), luminance[-4:].ravel(), luminance[:, :4].ravel(), luminance[:, -4:].ravel())
    )
    background_luminance = float(np.median(border))
    foreground_luminance = float(np.percentile(luminance, 99.5))
    if foreground_luminance - background_luminance < 0.1:
        raise RuntimeError("logo source does not contain a usable light-on-dark mark")
    fitted_mask = np.clip(
        (luminance - background_luminance) / (foreground_luminance - background_luminance),
        0.0,
        1.0,
    )

    mask = np.zeros((size, size), dtype=np.float64)
    left = (size - target_width) // 2
    top = (size - target_height) // 2
    mask[top : top + target_height, left : left + target_width] = fitted_mask

    return mask_to_linear_artwork(mask, peak_nits)


def rec2020_to_srgb_linear(values: np.ndarray) -> np.ndarray:
    xyz = values @ REC2020_TO_XYZ.T
    return xyz @ XYZ_TO_SRGB.T


def srgb_oetf(linear: np.ndarray) -> np.ndarray:
    linear = np.clip(linear, 0.0, 1.0)
    return np.where(
        linear <= 0.0031308,
        linear * 12.92,
        1.055 * np.power(linear, 1.0 / 2.4) - 0.055,
    )


def quantize_u8(encoded: np.ndarray) -> np.ndarray:
    return np.rint(np.clip(encoded, 0.0, 1.0) * 255.0).astype(np.uint8)


def make_sdr_variants(linear_nits: np.ndarray, peak_nits: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    # Ordinary SDR: the brightest source value lands below encoded maximum.
    normal_linear_2020 = np.clip(linear_nits / peak_nits * 0.78, 0.0, 1.0)
    normal = quantize_u8(srgb_oetf(rec2020_to_srgb_linear(normal_linear_2020)))

    # Max SDR: the same linear artwork receives more exposure and clips at 1.0.
    # It cannot encode values above SDR white because its channel ceiling is 255.
    max_linear_2020 = np.clip(linear_nits / peak_nits * 1.12, 0.0, 1.0)
    maximum = quantize_u8(srgb_oetf(rec2020_to_srgb_linear(max_linear_2020)))

    # ACES-style global tone map from the absolute HDR source back into [0, 1].
    x = np.maximum(linear_nits / SDR_REFERENCE_NITS, 0.0)
    mapped = (x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14)
    peak_x = peak_nits / SDR_REFERENCE_NITS
    peak_mapped = (peak_x * (2.51 * peak_x + 0.03)) / (
        peak_x * (2.43 * peak_x + 0.59) + 0.14
    )
    tone_linear_2020 = np.clip(mapped / peak_mapped, 0.0, 1.0)
    tone_mapped = quantize_u8(srgb_oetf(rec2020_to_srgb_linear(tone_linear_2020)))
    return normal, maximum, tone_mapped


def srgb_profile_bytes() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def save_srgb_png(pixels: np.ndarray, path: Path, icc_profile: bytes) -> None:
    Image.fromarray(pixels, mode="RGB").save(
        path,
        format="PNG",
        compress_level=9,
        optimize=False,
        icc_profile=icc_profile,
    )


def s15fixed16(value: float) -> bytes:
    fixed = int(round(value * 65536.0))
    return struct.pack(">i", fixed)


def pad4(data: bytes) -> bytes:
    return data + b"\0" * ((-len(data)) % 4)


def icc_xyz_tag(x: float, y: float, z: float) -> bytes:
    return b"XYZ \0\0\0\0" + s15fixed16(x) + s15fixed16(y) + s15fixed16(z)


def icc_mluc_tag(text: str) -> bytes:
    encoded = text.encode("utf-16-be")
    record_offset = 28
    return (
        b"mluc\0\0\0\0"
        + struct.pack(">II", 1, 12)
        + b"enUS"
        + struct.pack(">II", len(encoded), record_offset)
        + encoded
    )


def icc_curve_tag() -> bytes:
    # Sampled PQ EOTF. CICP-aware browsers use the CICP tag directly; this
    # curve is a standards-shaped fallback for profile readers that ignore it.
    signal = np.linspace(0.0, 1.0, 4096, dtype=np.float64)
    normalized_luminance = pq_eotf(signal) / 10000.0
    values = np.rint(np.clip(normalized_luminance, 0.0, 1.0) * 65535.0).astype(">u2")
    return b"curv\0\0\0\0" + struct.pack(">I", len(values)) + values.tobytes()


def build_rec2100_pq_icc() -> bytes:
    """Build a self-authored ICC v4 display profile with CICP 9/16/0/1."""

    curve = icc_curve_tag()
    tags: list[tuple[bytes, bytes]] = [
        (b"desc", icc_mluc_tag("Bright Pixels Rec.2100 PQ (1000 nit demo)")),
        (b"cprt", icc_mluc_tag("CC0-1.0; generated by bright-pixels")),
        (b"wtpt", icc_xyz_tag(0.9642, 1.0, 0.8249)),
        (
            b"chad",
            b"sf32\0\0\0\0"
            + b"".join(
                s15fixed16(value)
                for value in (
                    1.0478112,
                    0.0228866,
                    -0.0501270,
                    0.0295424,
                    0.9904844,
                    -0.0170491,
                    -0.0092345,
                    0.0150436,
                    0.7521316,
                )
            ),
        ),
        (b"rXYZ", icc_xyz_tag(*REC2020_TO_XYZ_D50[:, 0])),
        (b"gXYZ", icc_xyz_tag(*REC2020_TO_XYZ_D50[:, 1])),
        (b"bXYZ", icc_xyz_tag(*REC2020_TO_XYZ_D50[:, 2])),
        (b"rTRC", curve),
        (b"gTRC", curve),
        (b"bTRC", curve),
        (b"cicp", b"cicp\0\0\0\0" + bytes((9, 16, 0, 1))),
    ]

    tag_table_size = 4 + len(tags) * 12
    data_offset = 128 + tag_table_size
    payload_locations: dict[bytes, tuple[int, int]] = {}
    payload_blob = bytearray()
    records: list[bytes] = []

    for signature, payload in tags:
        if payload in payload_locations:
            offset, size = payload_locations[payload]
        else:
            offset = data_offset + len(payload_blob)
            size = len(payload)
            payload_locations[payload] = (offset, size)
            payload_blob.extend(pad4(payload))
        records.append(signature + struct.pack(">II", offset, size))

    profile_size = data_offset + len(payload_blob)
    header = bytearray(128)
    struct.pack_into(">I", header, 0, profile_size)
    header[4:8] = b"BPXL"
    header[8:12] = bytes((4, 4, 0, 0))
    header[12:16] = b"mntr"
    header[16:20] = b"RGB "
    header[20:24] = b"XYZ "
    struct.pack_into(">6H", header, 24, 2026, 8, 2, 0, 0, 0)
    header[36:40] = b"acsp"
    header[40:44] = b"APPL"
    struct.pack_into(">I", header, 64, 0)
    header[68:80] = icc_xyz_tag(0.9642, 1.0, 0.8249)[8:20]
    header[80:84] = b"BPXL"

    return bytes(header) + struct.pack(">I", len(tags)) + b"".join(records) + bytes(payload_blob)


def rgb_pq_to_yuv420p10le(rgb_pq: np.ndarray) -> bytes:
    """Convert full-range PQ R'G'B' to full-range BT.2020 non-constant Y'CbCr."""

    red, green, blue = np.moveaxis(rgb_pq, -1, 0)
    luma = 0.2627 * red + 0.6780 * green + 0.0593 * blue
    cb = (blue - luma) / 1.8814 + 0.5
    cr = (red - luma) / 1.4746 + 0.5

    # 4:2:0 chroma is averaged over 2x2 blocks. The artwork grid is aligned to
    # even pixels, so this does not change its geometry.
    cb_420 = cb.reshape(cb.shape[0] // 2, 2, cb.shape[1] // 2, 2).mean(axis=(1, 3))
    cr_420 = cr.reshape(cr.shape[0] // 2, 2, cr.shape[1] // 2, 2).mean(axis=(1, 3))

    def plane(values: np.ndarray) -> bytes:
        return np.rint(np.clip(values, 0.0, 1.0) * 1023.0).astype("<u2").tobytes()

    return plane(luma) + plane(cb_420) + plane(cr_420)


def encode_avif(rgb_pq: np.ndarray, path: Path, scratch: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to encode the 10-bit HDR AVIF")

    height, width = rgb_pq.shape[:2]
    raw_path = scratch / "logo-hdr-pq-yuv420p10le.yuv"
    raw_path.write_bytes(rgb_pq_to_yuv420p10le(rgb_pq))

    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-f",
        "rawvideo",
        "-pixel_format",
        "yuv420p10le",
        "-video_size",
        f"{width}x{height}",
        "-framerate",
        "1",
        "-color_range",
        "pc",
        "-colorspace",
        "bt2020nc",
        "-color_primaries",
        "bt2020",
        "-color_trc",
        "smpte2084",
        "-i",
        str(raw_path),
        "-frames:v",
        "1",
        "-c:v",
        "libsvtav1",
        "-preset",
        "8",
        "-crf",
        "8",
        "-pix_fmt",
        "yuv420p10le",
        "-color_range",
        "pc",
        "-colorspace",
        "bt2020nc",
        "-color_primaries",
        "bt2020",
        "-color_trc",
        "smpte2084",
        "-bsf:v",
        "av1_metadata=color_primaries=9:transfer_characteristics=16:matrix_coefficients=9:color_range=pc:chroma_sample_position=colocated",
        str(path),
    ]
    subprocess.run(command, check=True, cwd=ROOT)


def save_hdr_jpeg(rgb_pq: np.ndarray, path: Path, icc_profile: bytes) -> None:
    pixels = quantize_u8(rgb_pq)
    Image.fromarray(pixels, mode="RGB").save(
        path,
        format="JPEG",
        quality=96,
        subsampling=0,
        progressive=True,
        optimize=True,
        icc_profile=icc_profile,
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


COMPARISON_NAMES = [
    "logo-sdr.png",
    "logo-sdr-max.png",
    "logo-hdr-pq.avif",
    "logo-hdr-pq.jpg",
    "logo-hdr-tonemapped.png",
]


def asset_records(directory: Path) -> dict[str, dict[str, int | str]]:
    return {
        name: {"bytes": (directory / name).stat().st_size, "sha256": sha256(directory / name)}
        for name in COMPARISON_NAMES
    }


def write_manifest(size: int, peak_nits: float, logo_source: Path) -> None:
    generic_records = asset_records(ASSETS)
    gcai_records = asset_records(ASSETS / "gcai")
    manifest = {
        "source": {
            "precision": "float64 linear light",
            "color_primaries": "Rec.2020",
            "units": "cd/m² (nits)",
            "width": size,
            "height": size,
            "peak_nits": peak_nits,
            "sdr_reference_nits": SDR_REFERENCE_NITS,
        },
        "variants": {
            "generic": {
                "artwork": "programmatic 5x5 pixel aperture",
                "assets": generic_records,
            },
            "gcai": {
                "artwork": "assets/source/gcai.avif",
                "artwork_sha256": sha256(logo_source),
                "assets": gcai_records,
            },
        },
        # Kept as a convenient alias for tooling that expects the public/default set.
        "assets": generic_records,
        "icc_profile": {
            "path": "bright-pixels-rec2100-pq.icc",
            "bytes": (ASSETS / "bright-pixels-rec2100-pq.icc").stat().st_size,
            "sha256": sha256(ASSETS / "bright-pixels-rec2100-pq.icc"),
        },
    }
    (ASSETS / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def generate_variant(
    label: str,
    source: np.ndarray,
    output_directory: Path,
    peak_nits: float,
    srgb_icc: bytes,
    hdr_icc: bytes,
) -> None:
    if source.dtype != np.float64 or not np.isfinite(source).all():
        raise RuntimeError(f"{label}: linear source precision check failed")
    output_directory.mkdir(parents=True, exist_ok=True)
    print(
        f"{label}: {source.shape[1]}x{source.shape[0]} float64 Rec.2020 RGB, "
        f"{source.min():.2f}-{source.max():.2f} nits",
        flush=True,
    )
    sdr, sdr_max, tone_mapped = make_sdr_variants(source, peak_nits)
    save_srgb_png(sdr, output_directory / "logo-sdr.png", srgb_icc)
    save_srgb_png(sdr_max, output_directory / "logo-sdr-max.png", srgb_icc)
    save_srgb_png(tone_mapped, output_directory / "logo-hdr-tonemapped.png", srgb_icc)

    rgb_pq = pq_oetf(source)
    save_hdr_jpeg(rgb_pq, output_directory / "logo-hdr-pq.jpg", hdr_icc)
    with tempfile.TemporaryDirectory(prefix=f"bright-pixels-{label.lower()}-") as temporary:
        scratch = Path(temporary)
        np.save(scratch / "linear-source-rec2020-nits.npy", source)
        encode_avif(rgb_pq, output_directory / "logo-hdr-pq.avif", scratch)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE, help="even image dimension (default: 1024)")
    parser.add_argument(
        "--logo-source",
        type=Path,
        default=DEFAULT_LOGO_SOURCE,
        help="light-on-dark source artwork (default: assets/source/gcai.avif)",
    )
    parser.add_argument(
        "--peak-nits",
        type=float,
        default=DEFAULT_PEAK_NITS,
        help="peak logo luminance, 400-1000 recommended (default: 1000)",
    )
    parser.add_argument("--skip-verify", action="store_true", help="generate without running verification")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 400.0 <= args.peak_nits <= 1000.0:
        raise SystemExit("--peak-nits must be between 400 and 1000 for this demo")

    ASSETS.mkdir(parents=True, exist_ok=True)
    logo_source = args.logo_source.expanduser().resolve()
    srgb_icc = srgb_profile_bytes()
    hdr_icc = build_rec2100_pq_icc()
    (ASSETS / "bright-pixels-rec2100-pq.icc").write_bytes(hdr_icc)

    print(f"Optional artwork source: {logo_source}", flush=True)
    generic_source = build_generic_linear_artwork(args.size, args.peak_nits)
    gcai_source = build_gcai_linear_artwork(args.size, args.peak_nits, logo_source)
    generate_variant("Generic", generic_source, ASSETS, args.peak_nits, srgb_icc, hdr_icc)
    generate_variant("GCAI", gcai_source, ASSETS / "gcai", args.peak_nits, srgb_icc, hdr_icc)

    write_manifest(args.size, args.peak_nits, logo_source)
    print("Generated verified-ready generic and GCAI comparison sets.", flush=True)

    if not args.skip_verify:
        print("\nRunning required metadata verification...\n", flush=True)
        subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_assets.py")], check=True, cwd=ROOT)


if __name__ == "__main__":
    main()
