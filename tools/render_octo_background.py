from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "assets" / "octo-background" / "octo-background.html"
SVG = ROOT / "assets" / "octo-background" / "octoopus-character.svg"


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the 5-second animated Octo background to MP4.")
    parser.add_argument("--output", default="output/octo-background.mp4")
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=1280)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--crf", type=int, default=18)
    args = parser.parse_args()

    if not HTML.exists() or not SVG.exists():
        raise SystemExit("Octo background HTML/SVG assets are missing.")
    if args.width <= 0 or args.height <= 0 or args.fps <= 0 or args.duration <= 0:
        raise SystemExit("Width, height, fps and duration must be positive.")

    page_html = HTML.read_text(encoding="utf-8").replace(
        "<!-- OCTO_SVG -->", SVG.read_text(encoding="utf-8")
    )
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)

    total_frames = round(args.fps * args.duration)
    with tempfile.TemporaryDirectory(prefix="octo-bg-") as temp:
        frames = Path(temp)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": args.width, "height": args.height},
                device_scale_factor=1,
                reduced_motion="reduce",
            )
            page.set_content(page_html, wait_until="load")
            page.evaluate("""() => {
                document.getAnimations().forEach(animation => {
                    animation.pause();
                    animation.currentTime = 0;
                });
                window.renderAt(0);
            }""")
            for frame in range(total_frames):
                t = frame / args.fps
                page.evaluate("""(t) => {
                    document.getAnimations().forEach(animation => {
                        animation.currentTime = t * 1000;
                    });
                    window.renderAt(t);
                }""", t)
                page.screenshot(path=str(frames / f"frame_{frame:06d}.png"))
                if frame % args.fps == 0:
                    print(f"Rendering {frame}/{total_frames} frames", flush=True)
            browser.close()

        command = [
            "ffmpeg", "-y", "-framerate", str(args.fps),
            "-i", str(frames / "frame_%06d.png"),
            "-frames:v", str(total_frames),
            "-c:v", "libx264", "-preset", "veryfast",
            "-crf", str(args.crf), "-pix_fmt", "yuv420p",
            "-an", "-movflags", "+faststart", str(output),
        ]
        subprocess.run(command, check=True)
    print(f"Done: {output}")


if __name__ == "__main__":
    main()
