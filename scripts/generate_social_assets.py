#!/usr/bin/env python3
"""Generate the generic favicon family and Open Graph share image."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

CARBON = "#101412"
GRAPHITE = "#202724"
LINE = "#3b4641"
BONE = "#f2f0e9"
MUTED = "#aab5af"
CALIBRATION_BLUE = "#8ed1ff"
SIGNAL_ORANGE = "#ff8a63"
PAPER = "#f4f3ee"

PIXEL_MARK = (
    "00100",
    "01110",
    "11011",
    "01110",
    "00100",
)


def first_existing(paths: tuple[str, ...]) -> Path | None:
    for candidate in paths:
        path = Path(candidate)
        if path.is_file():
            return path
    return None


DISPLAY_FONT = first_existing(
    (
        "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    )
)
BODY_FONT = first_existing(
    (
        "/System/Library/Fonts/Avenir Next.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
)
MONO_FONT = first_existing(
    (
        "/System/Library/Fonts/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    )
)


def load_font(path: Path | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if path is None:
        return ImageFont.load_default(size=size)
    return ImageFont.truetype(path, size=size)


def draw_pixel_mark(
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    cell: int,
    gap: int,
    color: str,
) -> None:
    stride = cell + gap
    for row, bits in enumerate(PIXEL_MARK):
        for column, bit in enumerate(bits):
            if bit == "1":
                x0 = left + column * stride
                y0 = top + row * stride
                draw.rectangle((x0, y0, x0 + cell - 1, y0 + cell - 1), fill=color)


def icon_canvas(size: int) -> Image.Image:
    image = Image.new("RGB", (size, size), CARBON)
    draw = ImageDraw.Draw(image)
    cell = max(2, round(size * 0.118))
    gap = max(1, round(size * 0.028))
    mark_size = cell * 5 + gap * 4
    offset = (size - mark_size) // 2
    draw_pixel_mark(draw, offset, offset, cell, gap, BONE)
    rule_height = max(1, round(size * 0.028))
    draw.rectangle((0, 0, size - 1, rule_height - 1), fill=SIGNAL_ORANGE)
    return image


def write_favicon_svg(path: Path) -> None:
    cell = 12
    gap = 3
    mark_size = cell * 5 + gap * 4
    offset = (96 - mark_size) // 2
    rectangles: list[str] = []
    for row, bits in enumerate(PIXEL_MARK):
        for column, bit in enumerate(bits):
            if bit == "1":
                x = offset + column * (cell + gap)
                y = offset + row * (cell + gap)
                rectangles.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}"/>')
    svg = "\n".join(
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" role="img" aria-label="Bright Pixels mark">',
            f'  <rect width="96" height="96" fill="{CARBON}"/>',
            f'  <rect width="96" height="3" fill="{SIGNAL_ORANGE}"/>',
            f'  <g fill="{BONE}">',
            *(f"    {rectangle}" for rectangle in rectangles),
            "  </g>",
            "</svg>",
            "",
        )
    )
    path.write_text(svg, encoding="utf-8")


def generate_icons() -> None:
    write_favicon_svg(ROOT / "favicon.svg")

    master = icon_canvas(256)
    master.save(
        ROOT / "favicon.ico",
        format="ICO",
        sizes=((16, 16), (32, 32), (48, 48)),
    )
    icon_canvas(180).save(ROOT / "apple-touch-icon.png", format="PNG", optimize=True)


def draw_text_with_tracking(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: str,
    tracking: int,
) -> None:
    x, y = position
    for character in text:
        draw.text((x, y), character, font=font, fill=fill)
        advance = draw.textlength(character, font=font)
        x += round(advance) + tracking


def generate_open_graph_image() -> None:
    width, height = 1200, 630
    image = Image.new("RGB", (width, height), CARBON)
    draw = ImageDraw.Draw(image)

    display = load_font(DISPLAY_FONT, 83)
    display_small = load_font(DISPLAY_FONT, 68)
    body = load_font(BODY_FONT, 22)
    utility = load_font(MONO_FONT, 17)
    utility_small = load_font(MONO_FONT, 14)

    # Calibration frame and scale ticks.
    draw.rectangle((24, 24, width - 25, height - 25), outline=LINE, width=2)
    draw.rectangle((64, 56, 248, 63), fill=SIGNAL_ORANGE)
    for index in range(17):
        x = 64 + index * 32
        tick_height = 12 if index % 4 == 0 else 6
        draw.line((x, height - 55, x, height - 55 - tick_height), fill=LINE, width=2)

    draw_text_with_tracking(
        draw,
        (64, 78),
        "DISPLAY FIELD TEST 001",
        utility_small,
        CALIBRATION_BLUE,
        2,
    )

    title_x = 64
    draw.text((title_x, 116), "HDR IMAGE", font=display, fill=BONE, spacing=0)
    draw.text((title_x, 198), "BRIGHTNESS", font=display, fill=BONE, spacing=0)
    draw.text((title_x, 280), "DEMONSTRATION", font=display_small, fill=BONE, spacing=0)

    draw.text(
        (64, 392),
        "One image is genuinely encoded as HDR.\nNo CSS brightness tricks.",
        font=body,
        fill=MUTED,
        spacing=9,
    )
    draw_text_with_tracking(
        draw,
        (64, 501),
        "REC.2020  /  PQ  /  1,000 NIT TARGET",
        utility,
        CALIBRATION_BLUE,
        1,
    )

    # A literal light image frame containing the generic pixel mark.
    tile_left, tile_top, tile_size = 824, 104, 296
    draw.rectangle(
        (tile_left, tile_top, tile_left + tile_size, tile_top + tile_size),
        fill=PAPER,
    )
    inset = 24
    draw.rectangle(
        (
            tile_left + inset,
            tile_top + inset,
            tile_left + tile_size - inset,
            tile_top + tile_size - inset,
        ),
        fill=GRAPHITE,
    )
    mark_cell, mark_gap = 29, 7
    mark_size = mark_cell * 5 + mark_gap * 4
    mark_left = tile_left + (tile_size - mark_size) // 2
    mark_top = tile_top + (tile_size - mark_size) // 2
    draw_pixel_mark(draw, mark_left, mark_top, mark_cell, mark_gap, BONE)

    draw.text((824, 426), "4.9×", font=display, fill=SIGNAL_ORANGE)
    draw.text(
        (975, 448),
        "1,000 NIT HDR\n÷ 203 NIT SDR",
        font=utility_small,
        fill=MUTED,
        spacing=5,
    )

    draw_text_with_tracking(
        draw,
        (824, 540),
        "BRIGHT PIXELS",
        utility_small,
        BONE,
        3,
    )

    image.save(ASSETS / "og-image.png", format="PNG", optimize=True)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    generate_icons()
    generate_open_graph_image()
    print("Generated favicon.svg")
    print("Generated favicon.ico (16, 32, 48 px)")
    print("Generated apple-touch-icon.png (180 × 180)")
    print("Generated assets/og-image.png (1200 × 630)")


if __name__ == "__main__":
    main()
