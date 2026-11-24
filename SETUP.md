# EduCAST setup

[Project page](https://darl-genai.github.io/EduCAST/) · [Demo](https://darl-genai.github.io/EduCAST/demo/) · [Code layout](README.md#code-layout)

EduCAST turns teaching requests into narrated
lessons with animations, illustrations, chapter navigation, and interactive practice.

This repository contains the existing website, its Python backend, lesson-generation
pipeline, Remotion template, fonts, character artwork, and tests. Generated course
bundles, local API credentials, execution logs, and development artifacts are excluded.

## Run the website

Use Python 3.10 or later (Debian/Ubuntu: install `python3-venv` first).
Run all commands from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements/base.txt
python -m gui.public --host 127.0.0.1 --port 8091
```

Open `http://127.0.0.1:8091/`. The lesson brief is the home page: a composer
takes the topic, audience, language, and visual style, with the learning goal,
source material, and creative tools behind "Make it your own". Submitting it
reveals the build progress panel in place.

The public application requires a Python server; GitHub Pages alone cannot run
the generation API or local renderers.

Generated bundles are served from `runs/<id>/bundle/` and open in their own
player. Those media files are not part of this source export, so a link to an
earlier example lesson only resolves once its bundle is copied or generated.

## Project site

The repository's top-level `docs/` is the GitHub Pages site: `docs/index.html` is the
project page and `docs/demo/` a static copy of this showcase, published from the
`main` branch. Rebuild the demo after changing anything under `gui/`:

```bash
python scripts/build_pages.py
```

The script reuses `gui.public.public_html`, so the published page
stays in step with the server's public mode, and rewrites the server's absolute
`/assets/...` routes to paths relative to the project site. Because Pages serves
files only, the composer has no generation API to submit to there, so the static
build replaces its footnote with a link back to these instructions.

## Enable lesson generation

Generation additionally requires FFmpeg, a local Manim installation, a Playwright
browser, and the pinned Remotion dependencies. On Debian/Ubuntu:

```bash
sudo apt-get install ffmpeg build-essential python3-dev pkg-config \
  libcairo2-dev libpango1.0-dev fonts-liberation
python -m pip install -r requirements/render.txt
python -m playwright install --with-deps chromium
cd educast/assets/remotion
npm ci
cd ../../..
```

Use Node.js 18 or later for the template. A LaTeX installation is optional for
Manim MathTex; without it, some explanations use plain text. Restart the Python
server from the environment containing the installed rendering tools.

The default model names are recorded in `.env.example`; users need API access
and quota for the selected models. No credentials are bundled with this repository.

## Bring your own OpenAI API key

The composer accepts an OpenAI API key with the lesson request. Public
creation and retry requests require a key and do not fall back to the server's key.
The backend passes it through the job's child-process environment to the official
`https://api.openai.com/v1` endpoint for text, vision, images, and narration.

The credential is removed before writing the lesson request and is not placed in
the command line, job metadata, or browser localStorage. The form clears it after
a successful submission; retries require re-entry. This is server-mediated use:
the hosting server receives the key for the job. Use HTTPS outside localhost and
do not enable request-body/header logging for credential-bearing requests.

Endpoints:

- `GET /api/lessons/config`: form defaults and local rendering capabilities.
- `POST /api/lessons`: lesson fields plus `openai_api_key`; supports `Idempotency-Key`.
- `GET /api/lessons/{id}`: saved progress.
- `POST /api/lessons/{id}/retry`: `openai_api_key` for retrying a saved lesson.

This demo does not implement user accounts or private ownership of generated
bundles. Keep it on localhost or behind appropriate access controls when handling
private lesson content. The separate local Studio exposes job controls and logs:

```bash
python -m gui --runs-dir runs --port 8080
```

## Source map

See the [code layout](README.md#code-layout). Fixed resources live in
`educast/assets/`; agents and the review loop use those resources without changing
the original planning, rendering or repair sequence.

Full pipeline documentation: [docs/development/pipeline.md](docs/development/pipeline.md).

## Tests

```bash
python -m pip install -r requirements/dev.txt
python -m pytest -q tests
```

Browser tests additionally require Playwright and Chromium. Unit tests use
simulated providers or subprocesses; they do not require a real API key.

Bundled font license notices are retained alongside their font files.

## Minimal generation and review

After installing the rendering dependencies above, set `OPENAI_API_KEY` in your
shell or `.env`, then run from this directory:

```bash
python -m educast --request-json examples/minimal_request.json --run-dir runs/minimal
python -m educast.serve runs/minimal/bundle
```

The example generates a narrated Manim equation and an interactive question, with
up to three review/repair rounds. Packaging requires every scene to pass review;
`allow_unreviewed_bundle` remains false. Model output can fail this quality gate.
A fallback renderer is not equivalent to successful native Manim rendering.

Resume individual stages with the same request and run directory using
`--stage 2-render`, `--stage 2-review`, or `--stage 3`. Use `--force` to repeat a
completed stage; use `--no-repair` to inspect an initial render before repair.

For the pinned Python 3.10 environment, install `-r requirements/lock.txt`;
it does not install system libraries, LaTeX, Chromium, or Node.js. Mathematical
rendering requires a LaTeX distribution and `dvisvgm` for full MathTex support.
For example, Debian/Ubuntu packages include `texlive-latex-extra`,
`texlive-fonts-recommended`, and `dvisvgm`.

On restricted hosts where Node cannot open `/dev/null`, the optional adapter
`scripts/node_stdio_pipe.cjs` can be enabled with
`NODE_OPTIONS="--require=$PWD/scripts/node_stdio_pipe.cjs"`.

Existing `EDUHARNESS_*` environment variable names in `.env.example` remain supported.
