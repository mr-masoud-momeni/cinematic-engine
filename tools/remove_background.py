#!/usr/bin/env python
"""Local CPU-first background replacement for OctoEdit.

Uses MediaPipe Selfie Segmentation to create a person mask, composites the
foreground over a solid BGR background, then uses FFmpeg to encode H.264 and
restore the source audio.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np


def parse_hex_color(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise argparse.ArgumentTypeError("Background must be a 6-digit hex color, e.g. #0a192f")
    try:
        r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Invalid hex color.") from exc
    return b, g, r


def guided_filter_alpha(frame: np.ndarray, alpha: np.ndarray, radius: int = 8, eps: float = 0.01) -> np.ndarray:
    """Refine a soft person mask using image edges as guidance."""
    guide = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    mean_guide = cv2.boxFilter(guide, cv2.CV_32F, (2 * radius + 1, 2 * radius + 1))
    mean_alpha = cv2.boxFilter(alpha, cv2.CV_32F, (2 * radius + 1, 2 * radius + 1))
    corr_guide = cv2.boxFilter(guide * guide, cv2.CV_32F, (2 * radius + 1, 2 * radius + 1))
    corr_guide_alpha = cv2.boxFilter(guide * alpha, cv2.CV_32F, (2 * radius + 1, 2 * radius + 1))
    variance = corr_guide - mean_guide * mean_guide
    covariance = corr_guide_alpha - mean_guide * mean_alpha
    a = covariance / (variance + eps)
    b = mean_alpha - a * mean_guide
    mean_a = cv2.boxFilter(a, cv2.CV_32F, (2 * radius + 1, 2 * radius + 1))
    mean_b = cv2.boxFilter(b, cv2.CV_32F, (2 * radius + 1, 2 * radius + 1))
    refined = mean_a * guide + mean_b
    return np.clip(refined, 0.0, 1.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replace a video background locally with MediaPipe.")
    parser.add_argument("input", help="Source video (MP4/MOV/etc.)")
    parser.add_argument("output", help="Destination MP4")
    parser.add_argument("--background", type=parse_hex_color, default=parse_hex_color("#0a192f"),
                        help="Solid background color in hex (default: #0a192f)")
    parser.add_argument("--threshold", type=float, default=0.12,
                        help="Mask threshold, 0..1 (default: 0.12)")
    parser.add_argument("--feather", type=float, default=0.6,
                        help="Mask edge blur sigma in pixels (default: 0.6)")
    parser.add_argument("--guided-radius", type=int, default=8,
                        help="Guided-filter radius in pixels (default: 8)")
    parser.add_argument("--guided-eps", type=float, default=0.01,
                        help="Guided-filter regularization (default: 0.01)")
    parser.add_argument("--model", type=int, choices=(0, 1), default=0,
                        help="MediaPipe model: 0 general (recommended), 1 landscape")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="FFmpeg executable")
    parser.add_argument("--crf", type=int, default=22, help="H.264 quality (lower is better)")
    args = parser.parse_args()

    source = Path(args.input).expanduser().resolve()
    destination = Path(args.output).expanduser().resolve()
    if not source.is_file():
        parser.error(f"Input video not found: {source}")
    if source == destination:
        parser.error("Input and output paths must be different.")
    if not 0 <= args.threshold < 1:
        parser.error("--threshold must be between 0 and 1.")
    if args.feather < 0:
        parser.error("--feather cannot be negative.")
    if args.guided_radius < 1:
        parser.error("--guided-radius must be at least 1.")
    if args.guided_eps <= 0:
        parser.error("--guided-eps must be positive.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    silent_video = destination.with_name(destination.stem + ".video-only.mp4")

    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        parser.error(f"Could not open video: {source}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if width < 1 or height < 1:
        cap.release()
        parser.error("Could not read video dimensions.")

    writer = cv2.VideoWriter(
        str(silent_video),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        cap.release()
        parser.error("Could not create temporary video. Check OpenCV/codec installation.")

    started = time.time()
    processed = 0
    background = np.empty((height, width, 3), dtype=np.uint8)
    background[:] = args.background

    print(f"OctoEdit background removal: {width}x{height} @ {fps:.2f} fps")
    print("Engine: MediaPipe Selfie Segmentation (CPU)")
    print("Processing sequentially; this may take longer than the clip duration.")

    try:
        with mp.solutions.selfie_segmentation.SelfieSegmentation(
            model_selection=args.model
        ) as segmenter:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = segmenter.process(rgb)
                mask = result.segmentation_mask

                # Keep the mask soft around edges rather than creating a harsh cutout.
                alpha = np.clip(
                    (mask - args.threshold) / max(1e-6, 1.0 - args.threshold),
                    0.0,
                    1.0,
                ).astype(np.float32)
                alpha = cv2.resize(alpha, (width, height), interpolation=cv2.INTER_LINEAR)
                # Refine the matte against real image edges to reduce halos around
                # hair, ears, neck and shoulders.
                alpha = guided_filter_alpha(
                    frame, alpha, radius=args.guided_radius, eps=args.guided_eps
                )
                if args.feather > 0:
                    alpha = cv2.GaussianBlur(alpha, (0, 0), args.feather)
                alpha = alpha[:, :, None]

                composite = (
                    frame.astype(np.float32) * alpha
                    + background.astype(np.float32) * (1.0 - alpha)
                )
                writer.write(np.clip(composite, 0, 255).astype(np.uint8))
                processed += 1

                if processed % max(1, int(fps * 5)) == 0:
                    elapsed = max(0.001, time.time() - started)
                    pct = (processed / frame_count * 100) if frame_count else 0
                    print(f"Processed {processed}/{frame_count or '?'} frames "
                          f"({pct:.1f}%) | {processed / elapsed:.2f} fps")

    finally:
        cap.release()
        writer.release()

    if processed == 0:
        silent_video.unlink(missing_ok=True)
        parser.error("No frames were read from the input video.")

    print("Encoding H.264 and restoring original audio with FFmpeg...")
    command = [
        args.ffmpeg, "-y",
        "-i", str(silent_video),
        "-i", str(source),
        "-map", "0:v:0",
        "-map", "1:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", str(args.crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-shortest",
        "-movflags", "+faststart",
        str(destination),
    ]
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError:
        print("ERROR: FFmpeg was not found. Install FFmpeg and add it to PATH.", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: FFmpeg exited with code {exc.returncode}.", file=sys.stderr)
        return exc.returncode or 1
    finally:
        silent_video.unlink(missing_ok=True)

    elapsed = time.time() - started
    print(f"Done: {destination}")
    print(f"Processed {processed} frames in {elapsed:.1f}s "
          f"({processed / max(elapsed, 0.001):.2f} fps).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
