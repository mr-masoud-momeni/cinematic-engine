# OctoEdit — prototype 0.1

A local-first, JSON-driven video editing prototype for Octoopus. Rendering runs locally; footage is not uploaded.

## Requirements

- Node.js 20+
- FFmpeg on PATH, with `libx264` and `libass`
- Python 3.11 (64-bit)
- The official RVM source folder and MobileNetV3 checkpoint in `rvm-test/`
- The RVM Python environment/dependencies installed locally

## Standard timeline render

1. Put the source video in `examples/raw.mp4`.
2. Edit `examples/demo.timeline.json`.
3. Run from the project root:

```bash
npm run render
```

## RVM background replacement

The RVM pipeline is now driven by the same timeline JSON. It creates the alpha matte in a temporary folder, composites the original footage over the selected image/video background, restores source audio, and removes temporary files automatically.

Activate the Python 3.11 RVM environment first (for example, `.venv-rvm`), then set these timeline fields:

- `backgroundRemoval`: RVM variant, checkpoint, CPU device and downsample ratio.
- `background.source`: image or video path, relative to the project root.
- `effects`: rim light, shadow, subject color grade and edge softness.

Run:

```bash
npm run render-bg
```

Or pass another timeline:

```bash
npm run render-bg -- examples/my.timeline.json
```

The current example expects `examples/raw.mp4`, `examples/background.png`, and the local `rvm-test/` folder with `inference.py` and `rvm_mobilenetv3.pth`. The alpha video is temporary; it is not necessary to create or manage it manually.

The legacy MediaPipe worker remains available as a separate fallback:

```bash
npm run remove-bg -- input.mp4 output.mp4 --background "#0a192f"
```

## Timeline format

- `input`, `output`: paths relative to the timeline JSON file.
- `style`: ASS font, size, colors and default vertical margin.
- `grade`: global FFmpeg contrast, brightness and saturation.
- `backgroundRemoval`: RVM engine configuration.
- `background`: selected image/video background.
- `effects`: optional subject integration effects and strengths.
- `events`: timed `title` and `zoom` actions.
- `render`: output quality settings.

## Current limitations

- Natural-language instructions are not parsed automatically yet; the timeline JSON is the editing instruction format.
- RVM and compositing currently run sequentially on CPU. Processing can be slower than real time.
- The background image/video is cover-scaled to the source frame. The `fit` value is descriptive for now; only cover behavior is implemented.
- Subject-aware relighting is still an approximation: rim light and soft shadow are generic matte-based effects.
- Persian text rendering depends on an installed font and an FFmpeg build with libass.
