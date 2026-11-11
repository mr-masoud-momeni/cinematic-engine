from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "assets" / "octo-background" / "octo-background.html"
SVG = ROOT / "assets" / "octo-background" / "octoopus-character.svg"


def find_system_browser() -> str | None:
    """Use an installed Chrome/Edge when Playwright's bundled Chromium is unavailable."""
    candidates = [
        shutil.which("chrome"),
        shutil.which("msedge"),
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


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
            try:
                browser = p.chromium.launch(headless=True)
                print("Using Playwright Chromium.", flush=True)
            except Exception as error:
                system_browser = find_system_browser()
                if not system_browser:
                    raise SystemExit(
                        "Playwright Chromium is not installed and no system Chrome/Edge was found. "
                        "Install Microsoft Edge or Google Chrome, then run this script again. "
                        f"Original browser error: {error}"
                    ) from error
                print(f"Using installed browser: {system_browser}", flush=True)
                browser = p.chromium.launch(
                    headless=True,
                    executable_path=system_browser,
                )

            try:
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
            finally:
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
