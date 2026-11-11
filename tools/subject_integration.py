#!/usr/bin/env python
"""Cinematic subject integration for OctoEdit.

Inputs:
  - original: the source video, used as the clean foreground
  - alpha: a grayscale/alpha video exported by RVM
  - background: a still image or a video

This first version intentionally keeps segmentation separate from compositing.
"""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np


def hex_color(value: str) -> np.ndarray:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise argparse.ArgumentTypeError("Color must be a 6-digit hex value.")
    try:
        rgb = [int(value[i:i + 2], 16) for i in (0, 2, 4)]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Invalid hex color.") from exc
    return np.array(rgb[::-1], dtype=np.float32)


def cover(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    h, w = frame.shape[:2]
    scale = max(width / w, height / h)
    resized = cv2.resize(frame, (int(round(w * scale)), int(round(h * scale))), interpolation=cv2.INTER_LINEAR)
    y = max(0, (resized.shape[0] - height) // 2)
    x = max(0, (resized.shape[1] - width) // 2)
    return resized[y:y + height, x:x + width]


def main() -> int:
    p = argparse.ArgumentParser(description="Composite an RVM matte into a cinematic background.")
    p.add_argument("input", help="Original foreground video")
    p.add_argument("alpha", help="Grayscale alpha video exported by RVM")
    p.add_argument("background", help="Background image or video")
    p.add_argument("output", help="Output MP4")
    p.add_argument("--rim-strength", type=float, default=0.22, help="Edge light intensity, 0..1")
    p.add_argument("--rim-color", type=hex_color, default=None, help="RGB hex; default samples the background")
    p.add_argument("--shadow-strength", type=float, default=0.22, help="Soft cast shadow intensity, 0..1")
    p.add_argument("--shadow-blur", type=float, default=25.0, help="Shadow Gaussian blur radius")
    p.add_argument("--shadow-x", type=int, default=0, help="Shadow horizontal offset in pixels")
    p.add_argument("--shadow-y", type=int, default=12, help="Shadow vertical offset in pixels")
    p.add_argument("--warmth", type=float, default=0.04, help="Warm/cool grade amount, -0.2..0.2")
    p.add_argument("--contrast", type=float, default=1.03, help="Foreground contrast")
    p.add_argument("--saturation", type=float, default=0.96, help="Foreground saturation")
    p.add_argument("--edge-softness", type=float, default=0.8, help="Matte feather in pixels")
    p.add_argument("--vignette", type=float, default=0.18, help="Cinematic edge darkening, 0..1")
    p.add_argument("--grain", type=float, default=2.0, help="Fine film grain intensity, 0..20")
    p.add_argument("--sharpen", type=float, default=0.18, help="Unsharp-mask amount, 0..2")
    p.add_argument("--bloom", type=float, default=0.08, help="Soft highlight bloom, 0..1")
    p.add_argument("--cinematic-grade", type=float, default=0.0, help="Global cool-shadow/warm-highlight grade, 0..1")
    p.add_argument("--ffmpeg", default="ffmpeg")
    p.add_argument("--crf", type=int, default=19)
    a = p.parse_args()

    src_path, alpha_path = Path(a.input), Path(a.alpha)
    bg_path, out_path = Path(a.background), Path(a.output)
    for path in (src_path, alpha_path, bg_path):
        if not path.is_file():
            p.error(f"File not found: {path}")
    for name, value in (("rim-strength", a.rim_strength), ("shadow-strength", a.shadow_strength)):
        if not 0 <= value <= 1:
            p.error(f"--{name} must be between 0 and 1.")
    if a.edge_softness < 0 or a.shadow_blur < 0:
        p.error("Blur/softness values cannot be negative.")
    if not 0 <= a.vignette <= 1 or not 0 <= a.bloom <= 1:
        p.error("Vignette and bloom must be between 0 and 1.")
    if not 0 <= a.grain <= 20 or not 0 <= a.sharpen <= 2:
        p.error("Grain must be 0..20 and sharpen must be 0..2.")
    if not 0 <= a.cinematic_grade <= 1:
        p.error("Cinematic grade must be between 0 and 1.")

    source = cv2.VideoCapture(str(src_path))
    matte = cv2.VideoCapture(str(alpha_path))
    if not source.isOpened() or not matte.isOpened():
        p.error("Could not open source or alpha video.")
    width = int(source.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(source.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = source.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(source.get(cv2.CAP_PROP_FRAME_COUNT))
    if width < 1 or height < 1:
        p.error("Invalid source video dimensions.")

    bg_image = cv2.imread(str(bg_path), cv2.IMREAD_COLOR)
    bg_video = None if bg_image is not None else cv2.VideoCapture(str(bg_path))
    if bg_image is None and (bg_video is None or not bg_video.isOpened()):
        p.error("Background must be a readable image or video.")
    if bg_image is not None:
        bg_image = cover(bg_image, width, height)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame_no = 0
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    nx = (xx - (width - 1) / 2) / max(1.0, width / 2)
    ny = (yy - (height - 1) / 2) / max(1.0, height / 2)
    vignette_mask = np.clip(1.0 - a.vignette * np.clip((nx * nx + ny * ny) / 1.35, 0, 1), 0.0, 1.0)[..., None]
    rng = np.random.default_rng(2026)
    with tempfile.TemporaryDirectory(prefix="octoedit-integrate-") as temp:
        silent = Path(temp) / "integrated.mp4"
        writer = cv2.VideoWriter(str(silent), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
        if not writer.isOpened():
            p.error("Could not initialize temporary video writer.")
        try:
            while True:
                ok, fg = source.read()
                if not ok:
                    break
                ok_a, alpha_frame = matte.read()
                if not ok_a:
                    raise RuntimeError("Alpha video ended before the source video.")
                if bg_image is not None:
                    bg = bg_image
                else:
                    ok_bg, bg = bg_video.read()
                    if not ok_bg:
                        bg_video.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ok_bg, bg = bg_video.read()
                        if not ok_bg:
                            raise RuntimeError("Could not read background video.")
                    bg = cover(bg, width, height)

                if alpha_frame.ndim == 3:
                    alpha = cv2.cvtColor(alpha_frame, cv2.COLOR_BGR2GRAY)
                else:
                    alpha = alpha_frame
                if alpha.shape[:2] != (height, width):
                    alpha = cv2.resize(alpha, (width, height), interpolation=cv2.INTER_LINEAR)
                alpha = alpha.astype(np.float32) / 255.0
                if a.edge_softness > 0:
                    alpha = cv2.GaussianBlur(alpha, (0, 0), a.edge_softness)
                alpha = np.clip(alpha, 0.0, 1.0)[..., None]

                fg_f = fg.astype(np.float32)
                bg_f = bg.astype(np.float32)

                # Subtle cinematic grade on the subject only.
                hsv = cv2.cvtColor(np.clip(fg_f, 0, 255).astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
                hsv[..., 1] *= a.saturation
                graded = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)
                graded = (graded - 127.5) * a.contrast + 127.5
                warmth = a.warmth * 255.0
                graded[..., 2] += warmth
                graded[..., 0] -= warmth
                graded = np.clip(graded, 0, 255)

                # Soft offset shadow behind the subject.
                shadow = alpha[..., 0]
                matrix = np.float32([[1, 0, a.shadow_x], [0, 1, a.shadow_y]])
                shadow = cv2.warpAffine(shadow, matrix, (width, height), borderValue=0)
                if a.shadow_blur > 0:
                    shadow = cv2.GaussianBlur(shadow, (0, 0), a.shadow_blur)
                shadow = np.clip(shadow * a.shadow_strength, 0, 0.85)[..., None]
                composed_bg = bg_f * (1.0 - shadow)

                # Edge light: a narrow matte boundary tinted by the environment.
                if a.rim_strength > 0:
                    matte_u8 = np.clip(alpha[..., 0] * 255, 0, 255).astype(np.uint8)
                    dilated = cv2.dilate(matte_u8, np.ones((5, 5), np.uint8))
                    eroded = cv2.erode(matte_u8, np.ones((5, 5), np.uint8))
                    edge = ((dilated.astype(np.float32) - eroded.astype(np.float32)) / 255.0)
                    edge *= (alpha[..., 0] > 0.04) & (alpha[..., 0] < 0.98)
                    if a.rim_color is None:
                        rim = np.mean(bg_f.reshape(-1, 3), axis=0)
                    else:
                        rim = a.rim_color
                    rim_layer = edge[..., None] * rim.reshape(1, 1, 3) * a.rim_strength
                    graded = np.clip(graded + rim_layer, 0, 255)

                result = graded * alpha + composed_bg * (1.0 - alpha)

                # Apply a visible cool-shadow / warm-highlight look to the complete frame.
                if a.cinematic_grade > 0:
                    luminance = cv2.cvtColor(np.clip(result, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
                    shadows = (1.0 - luminance)[..., None]
                    highlights_mask = luminance[..., None]
                    result[..., 0] += shadows[..., 0] * (18.0 * a.cinematic_grade)
                    result[..., 2] += highlights_mask[..., 0] * (13.0 * a.cinematic_grade)
                    result = np.clip((result - 127.5) * (1.0 + 0.10 * a.cinematic_grade) + 127.5, 0, 255)

                # Apply the cinematic finish to the complete frame, not just the subject.
                if a.bloom > 0:
                    highlights = np.maximum(result - 170.0, 0.0)
                    glow = cv2.GaussianBlur(highlights, (0, 0), max(2.0, min(width, height) * 0.012))
                    result = np.clip(result + glow * (a.bloom / 2.5), 0, 255)
                if a.sharpen > 0:
                    soft = cv2.GaussianBlur(result, (0, 0), 1.0)
                    result = np.clip(result + (result - soft) * a.sharpen, 0, 255)
                if a.vignette > 0:
                    result *= vignette_mask
                if a.grain > 0:
                    noise = rng.normal(0.0, a.grain, (height, width, 1)).astype(np.float32)
                    result = np.clip(result + noise, 0, 255)

                writer.write(np.clip(result, 0, 255).astype(np.uint8))
                frame_no += 1
                if frame_no % 30 == 0:
                    suffix = f"/{total}" if total > 0 else ""
                    print(f"Integrated {frame_no}{suffix} frames", flush=True)
        finally:
            source.release()
            matte.release()
            if bg_video is not None:
                bg_video.release()
            writer.release()

        if frame_no == 0:
            raise RuntimeError("No source frames were processed.")
        cmd = [
            a.ffmpeg, "-y", "-i", str(silent), "-i", str(src_path),
            "-map", "0:v:0", "-map", "1:a?", "-c:v", "libx264",
            "-preset", "ultrafast", "-crf", str(a.crf), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
            str(out_path),
        ]
        subprocess.run(cmd, check=True)
    print(f"Done: {out_path} ({frame_no} frames)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
