#!/usr/bin/env python
"""CPU-first background replacement for OctoEdit using Robust Video Matting.

The official RVM source and MobileNetV3 checkpoint are kept in the local
rvm-test/ folder for this prototype. The source audio is restored with FFmpeg.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
import torch


ROOT = Path(__file__).resolve().parent.parent
RVM_DIR = ROOT / "rvm-test"
DEFAULT_CHECKPOINT = RVM_DIR / "rvm_mobilenetv3.pth"


def parse_color(value: str) -> np.ndarray:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise argparse.ArgumentTypeError(
            "Background must be a 6-digit hex color, e.g. #0a192f"
        )
    try:
        red, green, blue = (
            int(value[index:index + 2], 16) for index in (0, 2, 4)
        )
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Invalid hex color.") from exc
    return np.array([red, green, blue], dtype=np.float32)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replace a video background using Robust Video Matting (CPU)."
    )
    parser.add_argument("input", help="Source video")
    parser.add_argument("output", help="Destination video (MP4)")
    parser.add_argument(
        "--background",
        type=parse_color,
        default=parse_color("#0a192f"),
        help="Solid background color in hex (default: #0a192f)",
    )
    parser.add_argument(
        "--checkpoint",
        default=str(DEFAULT_CHECKPOINT),
        help="Path to the RVM MobileNetV3 checkpoint",
    )
    parser.add_argument(
        "--downsample-ratio",
        type=float,
        default=0.25,
        help="RVM inference scale between 0 and 1 (default: 0.25)",
    )
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--crf", type=int, default=18)
    args = parser.parse_args()

    source = Path(args.input).expanduser().resolve()
    destination = Path(args.output).expanduser().resolve()
    checkpoint = Path(args.checkpoint).expanduser().resolve()

    if not source.is_file():
        parser.error(f"Input video not found: {source}")
    if source == destination:
        parser.error("Input and output paths must be different.")
    if not checkpoint.is_file():
        parser.error(f"RVM checkpoint not found: {checkpoint}")
    if not (0 < args.downsample_ratio <= 1):
        parser.error("--downsample-ratio must be greater than 0 and at most 1.")
    if args.threads < 1:
        parser.error("--threads must be at least 1.")
    if not 0 <= args.crf <= 51:
        parser.error("--crf must be between 0 and 51.")
    if not RVM_DIR.is_dir():
        parser.error(f"RVM source folder not found: {RVM_DIR}")

    destination.parent.mkdir(parents=True, exist_ok=True)

    # Import the official RVM architecture without modifying the old worker.
    sys.path.insert(0, str(RVM_DIR))
    try:
        from model import MattingNetwork
    except ImportError as exc:
        parser.error(f"Could not import the RVM model from {RVM_DIR}: {exc}")

    device = torch.device("cpu")
    torch.set_num_threads(args.threads)

    print("Loading RVM MobileNetV3 on CPU...")
    model = MattingNetwork("mobilenetv3").eval()
    state = torch.load(checkpoint, map_location=device, weights_only=True)
    model.load_state_dict(state)
    model.to(device)

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        parser.error(f"Could not open input video: {source}")

    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = capture.get(cv2.CAP_PROP_FPS)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

    if width < 1 or height < 1:
        capture.release()
        parser.error("Could not read input video dimensions.")
    if not fps or fps <= 0:
        fps = 30.0

    background = args.background.reshape(1, 1, 3)
    recurrent_state = [None] * 4
    processed = 0

    print(f"Input: {width}x{height} @ {fps:.2f} FPS")
    print(f"Frames: {frame_count or 'unknown'}")
    print(f"RVM downsample ratio: {args.downsample_ratio}")
    print("Processing sequentially on CPU...")

    with tempfile.TemporaryDirectory(prefix="octoedit-rvm-") as temp_dir:
        silent_video = Path(temp_dir) / "video-only.mp4"
        writer = cv2.VideoWriter(
            str(silent_video),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height),
        )
        if not writer.isOpened():
            capture.release()
            parser.error(
                "Could not create temporary video. Check OpenCV video codec support."
            )

        try:
            with torch.inference_mode():
                while True:
                    ok, frame_bgr = capture.read()
                    if not ok:
                        break

                    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                    source_tensor = (
                        torch.from_numpy(frame_rgb.copy())
                        .permute(2, 0, 1)
                        .float()
                        .div_(255.0)
                        .unsqueeze(0)
                    )

                    foreground, alpha, *recurrent_state = model(
                        source_tensor,
                        *recurrent_state,
                        downsample_ratio=args.downsample_ratio,
                    )

                    foreground = (
                        foreground[0].permute(1, 2, 0).cpu().numpy()
                    )
                    alpha = alpha[0, 0].cpu().numpy()[..., None]

                    # RVM returns a soft matte; preserve it for hair and fine edges.
                    composite = (
                        foreground * alpha
                        + background * (1.0 - alpha)
                    )
                    composite = np.clip(
                        composite * 255.0, 0, 255
                    ).astype(np.uint8)

                    output_bgr = cv2.cvtColor(
                        composite, cv2.COLOR_RGB2BGR
                    )
                    writer.write(output_bgr)
                    processed += 1

                    if processed % 30 == 0:
                        if frame_count > 0:
                            percent = processed * 100.0 / frame_count
                            print(
                                f"Processed {processed}/{frame_count} "
                                f"frames ({percent:.1f}%)",
                                flush=True,
                            )
                        else:
                            print(
                                f"Processed {processed} frames",
                                flush=True,
                            )
        finally:
            capture.release()
            writer.release()

        if processed == 0:
            raise RuntimeError("No frames were read from the input video.")

        print("Encoding H.264 and restoring original audio with FFmpeg...")
        command = [
            args.ffmpeg,
            "-y",
            "-i", str(silent_video),
            "-i", str(source),
            "-map", "0:v:0",
            "-map", "1:a?",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", str(args.crf),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(destination),
        ]
        subprocess.run(command, check=True)

    print(f"Done: {destination}")
    print(f"Processed {processed} frames.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
