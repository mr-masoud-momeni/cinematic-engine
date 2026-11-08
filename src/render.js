import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const timelinePath = path.resolve(process.argv[2] ?? path.join(ROOT, 'examples/demo.timeline.json'));

function fail(message) {
  console.error(`\nOctoEdit: ${message}\n`);
  process.exit(1);
}

function secondsToAss(value) {
  const cs = Math.max(0, Math.round(Number(value) * 100));
  const h = Math.floor(cs / 360000);
  const m = Math.floor((cs % 360000) / 6000);
  const s = Math.floor((cs % 6000) / 100);
  const c = cs % 100;
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(c).padStart(2, '0')}`;
}

function assEscape(value) {
  return String(value).replace(/\\/g, '\\\\').replace(/{/g, '\\{').replace(/}/g, '\\}').replace(/\r?\n/g, '\\N');
}

function validate(t) {
  if (!t || typeof t !== 'object') fail('Timeline must be a JSON object.');
  if (!t.input || !t.output) fail('Timeline needs both "input" and "output" paths.');
  if (!fs.existsSync(path.resolve(path.dirname(timelinePath), t.input))) fail(`Input video not found: ${t.input}`);
  if (!Array.isArray(t.events)) fail('"events" must be an array.');
  for (const [i, e] of t.events.entries()) {
    if (!['title', 'zoom'].includes(e.type)) fail(`Event ${i + 1}: unsupported type "${e.type}". Use title or zoom.`);
    if (!Number.isFinite(e.start) || !Number.isFinite(e.end) || e.start < 0 || e.end <= e.start) fail(`Event ${i + 1}: start/end times are invalid.`);
    if (e.type === 'title' && !e.text) fail(`Event ${i + 1}: title text is missing.`);
    if (e.type === 'zoom' && (e.amount ?? 1.08) < 1) fail(`Event ${i + 1}: zoom amount must be >= 1.`);
  }
}

function buildAss(t, assPath) {
  const style = t.style ?? {};
  const font = style.font ?? 'Arial';
  const fontSize = style.fontSize ?? 64;
  const primary = style.textColor ?? '&H00FFFFFF';
  const outline = style.outlineColor ?? '&H00F1FA41';
  const marginV = style.marginV ?? 220;
  const header = `[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Octo,${font},${fontSize},${primary},&H000000FF,${outline},&H900A192F,0,0,0,0,100,100,0,0,1,2,1,2,80,80,${marginV},1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n`;
  const lines = t.events.filter(e => e.type === 'title').map(e => {
    const align = e.position === 'top' ? 8 : e.position === 'middle' ? 5 : 2;
    const size = e.fontSize ?? fontSize;
    const color = e.color ?? primary;
    const bold = e.bold === false ? 0 : 1;
    const tags = `{\\an${align}\\fs${size}\\c${color}\\b${bold}\\fad(180,180)}`;
    return `Dialogue: 0,${secondsToAss(e.start)},${secondsToAss(e.end)},Octo,,0,0,${e.marginV ?? marginV},,${tags}${assEscape(e.text)}`;
  });
  fs.writeFileSync(assPath, header + lines.join('\n') + '\n', 'utf8');
}

function ffmpegFilterPath(p) {
  return path.resolve(p).replace(/\\/g, '/').replace(/:/g, '\\:').replace(/'/g, "\\'");
}

function buildZoomExpression(events) {
  const zooms = events.filter(e => e.type === 'zoom');
  if (!zooms.length) return '1';
  return '1+' + zooms.map(e => `${Math.max(0, (e.amount ?? 1.08) - 1).toFixed(4)}*between(t,${e.start},${e.end})`).join('+');
}

function main() {
  if (!fs.existsSync(timelinePath)) fail(`Timeline not found: ${timelinePath}`);
  const t = JSON.parse(fs.readFileSync(timelinePath, 'utf8'));
  validate(t);

  const input = path.resolve(path.dirname(timelinePath), t.input);
  const output = path.resolve(path.dirname(timelinePath), t.output);
  fs.mkdirSync(path.dirname(output), { recursive: true });
  const assPath = path.join(path.dirname(output), `${path.basename(output, path.extname(output))}.titles.ass`);
  buildAss(t, assPath);

  const grade = t.grade ?? {};
  const contrast = grade.contrast ?? 1.12;
  const brightness = grade.brightness ?? -0.025;
  const saturation = grade.saturation ?? 0.92;
  const zoom = buildZoomExpression(t.events);
  const vf = [
    'scale=1080:1920:force_original_aspect_ratio=increase',
    'crop=1080:1920',
    `scale=w='ceil(iw*(${zoom})/2)*2':h='ceil(ih*(${zoom})/2)*2':eval=frame`,
    'crop=1080:1920',
    `eq=contrast=${contrast}:brightness=${brightness}:saturation=${saturation}`,
    `subtitles='${ffmpegFilterPath(assPath)}'`
  ].join(',');

  const args = [
    '-y', '-i', input,
    '-vf', vf,
    '-c:v', 'libx264', '-preset', t.render?.preset ?? 'veryfast', '-crf', String(t.render?.crf ?? 21),
    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart',
    output
  ];

  console.log('OctoEdit: rendering locally...');
  console.log(`Input:  ${input}`);
  console.log(`Output: ${output}`);
  const result = spawnSync(t.render?.ffmpegPath ?? 'ffmpeg', args, { stdio: 'inherit' });
  if (result.error) fail(`Could not start FFmpeg: ${result.error.message}. Install FFmpeg and ensure it is on PATH.`);
  if (result.status !== 0) fail(`FFmpeg exited with code ${result.status}. Check that your FFmpeg build includes libass and libx264.`);
  console.log('\nOctoEdit: done.');
}

main();
