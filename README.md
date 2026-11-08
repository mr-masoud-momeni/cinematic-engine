# OctoEdit — prototype 0.1

A local-first, JSON-driven video editing prototype for Octoopus. The first version deliberately keeps the scope small: vertical 9:16 output, a basic cinematic grade, timed title overlays, and timed zooms. It uses Node.js to translate a timeline into an FFmpeg render. No upload or cloud processing is involved.

## Requirements

- Node.js 20+
- FFmpeg available on PATH
- An FFmpeg build with `libx264` and `libass`

Check the installation:

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
- Persian font rendering depends on a font installed on the machine and a libass-enabled FFmpeg build. The default font is only a placeholder; set `style.font` to the exact installed font family (for example, IranYekan if installed).
- This first renderer crops to a centered 9:16 frame. Subject-aware reframing, background removal, automatic captions, audio ducking, transitions, and a visual GUI are later milestones.

## Next milestone

Render one real 30–45 second talking-head clip, inspect the crop and Persian typography, then lock a reusable Octoopus visual preset before adding more edit commands.
