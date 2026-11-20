# Stable Remotion project used by Stage 2.

## One-time setup (local Mac)

```bash
cd remotion_template
npm install
npx remotion browser ensure
```

All `@remotion/*` and `remotion` packages are **pinned to the same version**
(4.0.200). Do **not** `npm install` Remotion at the repository root — that
causes version conflicts and the
`Visited http://localhost:3000/index.html but got no response` failure.

## How EduHarness uses it

The adapter renders **in-place** from this folder:

```text
npx remotion render src/index.ts SceneBeat <out.mp4> --props=<scene_props.json> --concurrency=1
```

Scene props (title, bullets, style) are passed via `--props`, not by rewriting
source files. Renders are serialized with a lock file so Chromium pools do not
collide across scenes.

If Remotion/Node/Chrome is unavailable, Stage 2 falls back to a styled ffmpeg
slide and records `render_mode: ffmpeg-slide-fallback`.
