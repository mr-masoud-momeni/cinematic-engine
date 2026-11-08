# OctoEdit — prototype 0.1

A local-first, JSON-driven video editing prototype for Octoopus. It uses Node.js to translate a timeline into an FFmpeg render. No video upload or cloud processing is involved.

## Requirements

- Node.js 20+
- FFmpeg available on PATH
- An FFmpeg build with `libx264` and `libass`
- Python 3.11 (64-bit) for the optional background-removal worker

Check the base installation:

```bash
node --version
ffmpeg -version
ffmpeg -filters | findstr subtitles
```

## Quick start (Windows)

1. Put your source video in `examples/raw.mp4`.
2. Edit `examples/demo.timeline.json` (especially `input`, `output`, and event times).
3. From the project folder run:

```bash
npm run render
```

The rendered video is written to `examples/output/octoedit-demo.mp4`.

## Background removal (experimental, CPU-first)

This branch adds an offline MediaPipe Selfie Segmentation worker. It runs locally on CPU, replaces the background with a solid color, and restores the original audio with FFmpeg. The first test should be a short clip (about 5 seconds), not the full one-minute video.

Install the Python dependencies once:

```bash
py -3.11 -m venv .venv
.venv\\Scripts\\activate
python -m pip install --upgrade pip
pip install -r requirements-background-removal.txt
```

Run a five-second test clip (first create `test-5s.mp4` with FFmpeg, or use any short source clip):

```bash
npm run remove-bg -- test-5s.mp4 test-5s-navy.mp4 --background "#0a192f"
```

Or run the worker directly:

```bash
python tools/remove_background.py test-5s.mp4 test-5s-navy.mp4 --background "#0a192f"
```

The worker prints its measured processing FPS and elapsed time. It does not use the GPU. The model is bundled with the MediaPipe Python package; no model training or cloud upload is needed. Quality and speed still need to be measured on the target computer. Hair and fine edges may need further refinement.

Optional settings:

- `--threshold 0.12`: mask cutoff; lower keeps more edge detail but may leave background artifacts.
- `--feather 1.2`: soften the mask edge.
- `--model 0`: general model (default); `1` selects the landscape model.
- `--crf 22`: final H.264 quality.

## Timeline format

- `input`, `output`: paths relative to the timeline JSON file.
- `style`: ASS font, size, colors and default vertical margin.
- `grade`: contrast, brightness and saturation for the initial cinematic treatment.
- `events`: timed actions. Supported in this prototype:
  - `title`: `start`, `end`, `text`, optional `position` (`top`, `middle`, `bottom`), `fontSize`, `color`, `bold`, `marginV`.
  - `zoom`: `start`, `end`, optional `amount` (e.g. `1.07` for a subtle 7% zoom).
- `render`: optional FFmpeg preset, CRF and custom FFmpeg executable path.

## Important prototype limits

- Natural-language instructions are not parsed automatically yet. For this first milestone, we translate them into JSON so the render engine can be tested independently.
- Persian font rendering depends on a font installed on the machine and a libass-enabled FFmpeg build. Set `style.font` to the exact installed font family (for example, IranYekan if installed).
- The main renderer currently crops to a centered 9:16 frame. Subject-aware reframing, automatic captions, audio ducking, transitions, and a visual GUI are later milestones.
- Background removal is experimental and currently outputs a solid-color background; gradient/image backgrounds and tighter integration into the JSON timeline are next steps.

## Next milestone

Test background removal on a real short talking-head clip, inspect the edges and measured CPU speed, then integrate the feature into the JSON timeline.
