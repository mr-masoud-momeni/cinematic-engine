#!/usr/bin/env python
"""JSON-driven RVM background replacement and subject compositing for OctoEdit."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def run(command: list[str], label: str) -> None:
    print(f"\\nOctoEdit: {label}", flush=True)
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render background replacement from an OctoEdit timeline JSON."
    )
    parser.add_argument("timeline", nargs="?", default="examples/demo.timeline.json")
    parser.add_argument("--python", default=sys.executable, help="Python executable for RVM")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()

    timeline_path = Path(args.timeline).expanduser().resolve()
    if not timeline_path.is_file():
        parser.error(f"Timeline JSON not found: {timeline_path}")
    try:
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"Could not read timeline JSON: {exc}")

    base = timeline_path.parent
    input_value = timeline.get("input")
    output_value = timeline.get("output")
    bg_cfg = timeline.get("background", {})
    removal = timeline.get("backgroundRemoval", {})
    effects = timeline.get("effects", {})

    if not input_value or not output_value:
        parser.error('Timeline must define "input" and "output".')
    background_value = bg_cfg.get("source")
    if not background_value:
        parser.error('Timeline must define "background": {"source": "..."}.')

    source = resolve(base, input_value)
    background = resolve(base, background_value)
    output = resolve(base, output_value)
    for label, path in (("Input video", source), ("Background", background)):
        if not path.is_file():
            parser.error(f"{label} not found: {path}")
    if source == output:
        parser.error("Input and output paths must be different.")

    rvm_dir = resolve(ROOT, removal.get("rvmDirectory", "rvm-test"))
    checkpoint = resolve(ROOT, removal.get("checkpoint", "rvm-test/rvm_mobilenetv3.pth"))
    inference = rvm_dir / "inference.py"
    for label, path in (("RVM source folder/inference.py", inference), ("RVM checkpoint", checkpoint)):
        if not path.is_file():
            parser.error(f"{label} not found: {path}")

    variant = removal.get("variant", "mobilenetv3")
    device = removal.get("device", "cpu")
    downsample = float(removal.get("downsampleRatio", 0.25))
    if not 0 < downsample <= 1:
        parser.error("backgroundRemoval.downsampleRatio must be > 0 and <= 1.")

    output.parent.mkdir(parents=True, exist_ok=True)
    effect_args: list[str] = []
    rim = effects.get("rimLight", {})
    shadow = effects.get("shadow", {})
    grade = effects.get("colorGrade", {})

    if rim.get("enabled", True):
        effect_args += ["--rim-strength", str(float(rim.get("strength", 0.22)))]
        if rim.get("color"):
            effect_args += ["--rim-color", str(rim["color"])]
    else:
        effect_args += ["--rim-strength", "0"]
    if shadow.get("enabled", True):
        effect_args += [
            "--shadow-strength", str(float(shadow.get("strength", 0.22))),
            "--shadow-blur", str(float(shadow.get("blur", 25))),
            "--shadow-x", str(int(shadow.get("offsetX", 0))),
            "--shadow-y", str(int(shadow.get("offsetY", 12))),
        ]
    else:
        effect_args += ["--shadow-strength", "0"]
    if grade.get("enabled", True):
        effect_args += [
            "--warmth", str(float(grade.get("warmth", 0.04))),
            "--contrast", str(float(grade.get("contrast", 1.03))),
            "--saturation", str(float(grade.get("saturation", 0.96))),
        ]
    else:
        effect_args += ["--warmth", "0", "--contrast", "1", "--saturation", "1"]

    integration_script = ROOT / "tools" / "subject_integration.py"
    edge_softness = float(effects.get("edgeSoftness", 0.8))
    cinematic = effects.get("cinematic", {})
    cinematic_enabled = cinematic.get("enabled", True)
    cinematic_args = [
        "--vignette", str(float(cinematic.get("vignette", 0.18) if cinematic_enabled else 0)),
        "--grain", str(float(cinematic.get("grain", 2.0) if cinematic_enabled else 0)),
        "--sharpen", str(float(cinematic.get("sharpen", 0.18) if cinematic_enabled else 0)),
        "--bloom", str(float(cinematic.get("bloom", 0.08) if cinematic_enabled else 0)),
    ]
    crf = int(timeline.get("render", {}).get("crf", 19))

    with tempfile.TemporaryDirectory(prefix="octoedit-rvm-") as temp_dir:
        alpha_path = Path(temp_dir) / "rvm-alpha.mp4"
        rvm_command = [
            args.python, str(inference),
            "--variant", variant,
            "--checkpoint", str(checkpoint),
            "--device", device,
            "--input-source", str(source),
            "--output-alpha", str(alpha_path),
            "--output-type", "video",
            "--downsample-ratio", str(downsample),
            "--seq-chunk", str(int(removal.get("sequenceChunk", 1))),
            "--num-workers", str(int(removal.get("workers", 0))),
        ]
        run(rvm_command, "1/2 — generating RVM alpha matte")
        if not alpha_path.is_file() or alpha_path.stat().st_size == 0:
            raise RuntimeError("RVM did not produce an alpha video.")

        composite_command = [
            args.python, str(integration_script),
            str(source), str(alpha_path), str(background), str(output),
            "--ffmpeg", args.ffmpeg,
            "--crf", str(crf),
            "--edge-softness", str(edge_softness),
            *effect_args,
            *cinematic_args,
        ]
        run(composite_command, "2/2 — compositing subject and background")

    print(f"\\nOctoEdit: background render complete: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
