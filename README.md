# HDR image brightness demonstration

A self-contained GitHub Pages demo showing how an HDR image can use physical display headroom while sitting inside an otherwise SDR webpage. The page does not brighten the HDR case with CSS: all comparison images share one rule, and the reliable HDR asset is a real 10-bit AVIF tagged Rec.2020 + PQ (SMPTE ST 2084).

The default artwork is an unbranded geometric mark. Add `?gcai=true` to the page URL to switch every comparison image to the optional GCAI artwork:

```text
http://localhost:8000/
http://localhost:8000/?gcai=true
```

Both sets are generated from high-precision linear-light sources and verified independently.

## Quick start

From the project root:

```bash
python3 -m http.server 8000
```

Then open <http://localhost:8000/> in a current Chrome or Safari browser.

Recent Python releases serve `.avif` as `image/avif`. This project also includes a server that registers the MIME type explicitly:

```bash
python3 scripts/serve.py --port 8000
```

Do not open `index.html` through `file://`. The images themselves may load, but the capability report and asset manifest are intended to run through HTTP or HTTPS.

## What is in the project

```text
index.html
styles.css
script.js
requirements.txt
favicon.svg
favicon.ico
apple-touch-icon.png
scripts/
  generate_assets.py
  generate_social_assets.py
  verify_assets.py
  serve.py
assets/
  logo-sdr.png
  logo-sdr-max.png
  logo-hdr-pq.avif
  logo-hdr-pq.jpg
  logo-hdr-tonemapped.png
  bright-pixels-rec2100-pq.icc
  og-image.png
  manifest.json
  gcai/
    ...the same five comparison files...
  source/
    gcai.avif
```

The five root images are the public, generic set. `assets/gcai/` is selected only when the URL contains `?gcai=true`.

The favicon family and 1200 × 630 Open Graph image use only the generic pixel mark. Regenerate them with:

```bash
python3 scripts/generate_social_assets.py
```

This writes `favicon.svg`, the multi-size `favicon.ico`, `apple-touch-icon.png`, and `assets/og-image.png`. The checked-in page metadata always advertises the unbranded public URL and image; `?gcai=true` does not leak into link previews.

## Comparison files

| File | Encoding | Purpose |
| --- | --- | --- |
| `logo-sdr.png` | 8-bit RGB, sRGB ICC | Ordinary SDR rendering; highlights stop below channel maximum. |
| `logo-sdr-max.png` | 8-bit RGB, sRGB ICC | Highlight channels reach 255 but still cannot exceed SDR reference white. |
| `logo-hdr-pq.avif` | 10-bit AV1, Rec.2020, PQ, full range | Primary HDR demonstration; flat logo highlights target 1,000 nits. |
| `logo-hdr-tonemapped.png` | 8-bit RGB, sRGB ICC | ACES-style tone map of the absolute-luminance HDR source back to SDR. |
| `logo-hdr-pq.jpg` | 8-bit JPEG with a custom Rec.2020/PQ ICC+CICP profile | Experimental reproduction of the LinkedIn-style JPEG mechanism. |

The AVIF uses full-range 10-bit `yuv420p10le` with the valid BT.2020 non-constant-luminance matrix (`bt2020nc`). The JPEG’s embedded ICC profile describes RGB, so its CICP matrix value is `0` (RGB).

## Regenerate everything

Requirements:

- Python 3.10 or newer
- NumPy and Pillow
- FFmpeg with the `libsvtav1` encoder and AVIF muxer
- Optional: ExifTool, ImageMagick, and macOS `sips` for extra reports

Install the Python dependencies if needed:

```bash
python3 -m pip install -r requirements.txt
```

Generate both artwork families and immediately verify them:

```bash
python3 scripts/generate_assets.py
```

The default peak is 1,000 nits. A lower target can be generated within the requested 400–1,000 nit range:

```bash
python3 scripts/generate_assets.py --peak-nits 600
```

The generator performs these steps:

1. Builds a `float64` linear Rec.2020 RGB image whose values are absolute luminance in nits.
2. Creates the generic pixel mark programmatically. For the optional work variant, it decodes the supplied SDR GCAI artwork, constructs its coverage mask in linear light, and maps the mark into the same absolute-luminance source.
3. Converts that source to the ordinary, maximum, and tone-mapped sRGB PNGs.
4. Applies the ST 2084 inverse EOTF to produce PQ code values.
5. Converts PQ R′G′B′ to full-range BT.2020 non-constant Y′CbCr, writes a 10-bit raw frame, and encodes it to AVIF with explicit CICP signaling.
6. Builds a self-authored ICC v4 profile with Rec.2020 colorants, sampled PQ curves, and CICP `9 / 16 / 0 / 1`, then embeds it in the experimental JPEG.
7. Runs `scripts/verify_assets.py` and fails if required metadata, dimensions, ICC tags, or decoded highlight values are wrong.

Intermediate linear arrays and raw YUV frames live in temporary directories and are removed after a successful run. `assets/manifest.json` records sizes and SHA-256 hashes of the final files.

## Verified metadata

Run verification independently at any time:

```bash
python3 scripts/verify_assets.py
```

The verifier calls `ffprobe`, decodes each HDR AVIF through FFmpeg, inspects the JPEG ICC structure itself, and uses Pillow to verify the SDR PNG profiles. The checked-in assets currently report:

```text
codec_name=av1
pix_fmt=yuv420p10le
color_range=pc
color_space=bt2020nc
color_transfer=smpte2084
color_primaries=bt2020

assets/logo-hdr-pq.avif:
decoded 99th-percentile highlight ≈ 998.9 nits

assets/gcai/logo-hdr-pq.avif:
decoded 99th-percentile highlight ≈ 981.2 nits
```

The slight difference in the GCAI result comes from antialiased logo edges and lossy AV1 encoding. Both remain within the verifier’s 800–1,200 nit tolerance around the 1,000-nit target.

For the experimental JPEG, the custom inspector reports:

```text
profile_name: Bright Pixels Rec.2100 PQ (1000 nit demo)
color_primaries: bt2020 (CICP 9)
color_transfer: smpte2084 / PQ (CICP 16)
color_space: rgb (CICP matrix 0)
color_range: full (CICP flag 1)
profile_bytes: 8816
```

Useful manual commands:

```bash
ffprobe -v error \
  -show_entries stream=codec_name,pix_fmt,color_range,color_space,color_transfer,color_primaries \
  -of default=noprint_wrappers=1 \
  assets/logo-hdr-pq.avif

exiftool -G1 -s assets/logo-hdr-pq.avif assets/logo-hdr-pq.jpg
identify -verbose assets/logo-sdr.png
sips -g space -g profile assets/logo-hdr-pq.jpg
```

On macOS, the last command is expected to include:

```text
space: RGB
profile: Bright Pixels Rec.2100 PQ (1000 nit demo)
```

FFprobe does not currently surface CICP stored *inside a JPEG ICC profile*. That is why `verify_assets.py` parses the embedded JPEG ICC tag table directly instead of pretending an unknown FFprobe transfer value is proof of SDR or HDR.

## The CSS control

Every displayed comparison image, including the isolated and reference-white cases, uses the same class:

```css
.demo-image {
  width: 160px;
  height: 160px;
  object-fit: cover;
  filter: none;
  opacity: 1;
  mix-blend-mode: normal;
  transform: none;
}
```

There is no brightness filter, bloom, shadow, animation, gradient, canvas preprocessing, or special compositing on the HDR image. The CSS inspection panel reads the selected element with `getComputedStyle()` so the values can be checked in the page itself.

The plain reference rectangle is exactly:

```css
background: rgb(255, 255, 255);
```

## How to verify the visible effect

Recommended setup:

- A recent MacBook Pro with an XDR display, or another HDR-capable display with working macOS EDR support
- A current Chrome or Safari release
- The browser window placed on the HDR display
- The computer plugged into power when possible
- Low Power Mode disabled
- Display brightness high enough to leave visible headroom
- Moderate ambient light without direct glare

Test procedure:

1. Load the page through HTTP(S), not `file://`.
2. Check the capability panel. `window.matchMedia("(dynamic-range: high)").matches` should ideally be `true`, but this is only an indicator.
3. Compare the four files, then switch the surround among dark gray, mid gray, and white.
4. Hide labels and shuffle the tiles for a blind identification test.
5. Enable isolation mode to put each image in the same screen position.
6. Compare the HDR mark against the plain CSS-white rectangle.
7. Take a normal macOS screenshot and open it beside the live page. The captured copy may flatten or tone-map the brightness difference.
8. Download the AVIF and open it in multiple viewers. Software that ignores the metadata may tone-map it, show it as SDR, or display it incorrectly.

Do not use a screenshot as the only proof. A screenshot records image data after some part of the compositing pipeline; it does not measure the light emitted by the panel. JavaScript cannot report the actual emitted nits either.

## Why results vary

The visible effect depends on more than the file:

- HDR capability and peak brightness of the display
- Browser image-codec and HDR-output support
- macOS EDR compositing behavior
- Current display brightness and available headroom
- Ambient-light adaptation
- Low Power Mode, battery state, and whether the machine is plugged in
- Display reference mode or calibration settings
- Tone mapping performed by the browser or image viewer
- Local-dimming zones on mini-LED displays

Mini-LED local dimming is content-dependent. Large bright regions can consume more power or engage more zones than small highlights, so apparent peak brightness can change with window size and nearby content.

Users on SDR displays can still run every metadata check, inspect the identical CSS, use the controls, and compare the tone-mapped files. They should not expect a physical brightness increase.

## JPEG limitation, documented honestly

`logo-hdr-pq.jpg` is not a normal sRGB JPEG with a misleading filename. Its pixel values are PQ-coded and its embedded ICC profile contains Rec.2020 colorants plus the standardized CICP values `9 / 16 / 0 / 1`.

It is still an experimental carrier:

- Classic JPEG is 8-bit, while the AVIF demonstration is 10-bit.
- Browser support for PQ communicated through an embedded JPEG ICC profile is less consistent than native AVIF CICP support.
- FFprobe identifies the JPEG’s decoded JFIF/Y′CbCr properties but does not expose the ICC CICP fields.
- A viewer that ignores the profile can show the JPEG as dull, washed out, or simply SDR.
- Metadata was verified on this machine; physical panel output was not measured with a luminance meter.

The page therefore uses the AVIF as its primary HDR tile and offers the JPEG as a separate download. No normal SDR JPEG is silently substituted.

The AVIF contains the core HDR signaling needed here—Rec.2020 primaries, PQ transfer, full range, 10-bit samples—and absolute PQ code values targeting 1,000 nits. This FFmpeg path does not add optional HDR10 mastering-display (`mDCV`) or MaxCLL/MaxFALL metadata to the still image, and the demo does not claim that it does.

## Live demo and GitHub Pages

- Public, unbranded demo: <https://dzoba.github.io/bright-pixels/>
- Optional GCAI artwork: <https://dzoba.github.io/bright-pixels/?gcai=true>
- Source: <https://github.com/dzoba/bright-pixels>

The project has no build step and includes `.nojekyll`. GitHub Pages deploys directly from `main` at `/ (root)`. Verify the live AVIF response header with:

```bash
curl -I https://dzoba.github.io/bright-pixels/assets/logo-hdr-pq.avif
```

Look for:

```text
Content-Type: image/avif
```

The local explicit server was tested with both the generic and GCAI AVIFs and returned `Content-type: image/avif`.

## Technical references

- [ITU-R BT.2100](https://www.itu.int/rec/R-REC-BT.2100/) defines Rec.2100 HDR systems including PQ.
- [SMPTE ST 2084](https://ieeexplore.ieee.org/document/7291452) defines the perceptual-quantizer transfer function.
- [ICC CICP tag amendment](https://www.color.org/iccmax/download/CICP_tag_and_type_amendment.pdf) defines the ICC `cicp` tag used by the JPEG attempt.
- [PNG Third Edition](https://www.w3.org/TR/png-3/) documents the same H.273 CICP code-point model for still images.
