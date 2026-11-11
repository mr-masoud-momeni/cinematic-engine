# Animated Octo background

This scene uses the original Octoopus SVG mascot from `octoopus-motion` and renders it as a 5-second vertical MP4. The scene has a navy gradient, turquoise glow, light beams, floating bubbles, and an Octo entrance with a small body/tentacle movement and eye blinks.

## Requirements

- Python package: `playwright`
- Playwright Chromium browser
- FFmpeg available on PATH

Install once in the project's active Python environment:

```cmd
pip install playwright
python -m playwright install chromium
```

## Render

From the repository root:

```cmd
python tools\\render_octo_background.py
```

Output: `output/octo-background.mp4`

Optional:

```cmd
python tools\\render_octo_background.py --duration 5 --fps 30 --width 720 --height 1280
```

## Use it behind the keyed subject

After rendering, set the existing timeline background source to:

```json
"background": {
  "source": "output/octo-background.mp4",
  "fit": "cover"
}
```

The normal RVM + compositing pipeline then places the person in front of this video. The generated background already contains Octo, so no new timeline layer system is needed.
