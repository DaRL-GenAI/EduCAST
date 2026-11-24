<div align="center">

# EduCAST: Personalized Educational Video Generation

**A Multi-Agent System for Personalized Educational Video Generation with Closed-Loop Review**

Qingyue Chen*, Aarshdeeep Singh Nandra*, Huaiyuan Yao, Varun Shourie, Rayan Kazi, Hua Wei

**AAAI-27 Demonstration Program**

[🌐 Project Website / GUI](https://darl-genai.github.io/EduCAST/) · [🎬 Video Demo](https://darl-genai.github.io/EduCAST/video/) · [💻 Code](educast/)

</div>

[![Watch the EduCAST demo](docs/static/images/demo-poster.jpg)](https://darl-genai.github.io/EduCAST/video/)

---

### Table of Contents

- [🌟 Overview](#-overview)
- [🚀 Quick Start](#-quick-start)
  - [1. Requirements](#1-requirements)
  - [2. Configure API Keys](#2-configure-api-keys)
  - [3. Run Agents](#3-run-agents)
  - [4. Project Organization](#4-project-organization)
- [🔍 Outputs and Review](#-outputs-and-review)
- [🙏 Acknowledgements](#-acknowledgements)
- [📌 Citation](#-citation)

---

## 🌟 Overview

EduCAST generates narrated educational media from a topic, learner profile, and learning goal. A planner builds the lesson, rendering agents create its scenes, and a visual reviewer checks the results and directs repairs before packaging.

**Key Features**

- 🎬 **Multiple renderers** — Manim animations, Remotion motion graphics, generated illustrations, and interactive exercises.
- 🤖 **Learner-conditioned planning** — scene content and explanations follow the requested audience and learning goal.
- 🔁 **Closed-loop review** — deterministic guards and a VLM reviewer inspect rendered scenes; failed scenes receive targeted repairs and another review.
- 🎧 **Playable lessons** — narration, captions, scene navigation, and interactive practice in one browser player.

![EduCAST pipeline](docs/static/images/pipeline.png)

---

## 🚀 Quick Start

### 1. Requirements

Use **Python 3.10**, **Node.js 18+**, and FFmpeg. On Ubuntu/Debian, install the rendering libraries and LaTeX:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev build-essential pkg-config \
  ffmpeg libcairo2-dev libpango1.0-dev fonts-liberation \
  texlive-latex-extra texlive-fonts-recommended dvisvgm
```

Clone the repository and install the pinned Python environment:

```bash
git clone https://github.com/DaRL-GenAI/EduCAST.git
cd EduCAST
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements/lock.txt
python -m playwright install --with-deps chromium
```

For Remotion scenes, also install its pinned Node dependencies:

```bash
(cd educast/assets/remotion && npm ci)
```

The bundled sample uses Manim and an interactive exercise; it does not require Remotion or image generation. See [SETUP.md](SETUP.md) for GUI deployment and tool overrides.

### 2. Configure API Keys

```bash
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`, or export it in your shell. The sample uses:

| Task | Default model |
| --- | --- |
| Planning and code generation | `gpt-5` |
| Visual review | `gpt-5` |
| Narration | `gpt-4o-mini-tts` |

The full pipeline additionally uses the image models listed in `.env.example` when image generation is enabled. Your API project must have access to the selected models.

### 3. Run Agents

#### (a) Bundled Sample — One Command

```bash
python -m educast --sample
```

This loads [sample_request.json](educast/assets/sample_request.json) and runs **planning → code generation → rendering and narration → visual review and repair → lesson packaging**.

The sample teaches **solving `x + 2 = 5`**, followed by an interactive question about `x + 1 = 4`. It enables narration, up to three reviews per scene, and up to two repairs after failed reviews. Packaging requires every scene to pass the original quality gates; the sample does not bypass review.

Output directory: `runs/sample_algebra/`. Open the finished lesson with:

```bash
python -m educast.serve runs/sample_algebra/bundle
```

Then visit **http://127.0.0.1:8765/**. For a separate run directory:

```bash
python -m educast --sample --run-dir runs/algebra-new
```

#### (b) Your Own Topic

Edit [request.json](request.json), then run:

```bash
python -m educast --request-json request.json
```

Important request fields:

| Field | Purpose |
| --- | --- |
| `topic`, `audience`, `learning_goal` | What to teach and who to teach |
| `source_text` | Source material and lesson instructions |
| `enable_manim`, `enable_remotion`, `enable_image` | Available rendering agents |
| `enable_narration`, `voice` | Spoken narration |
| `max_review_rounds` | Maximum reviews per scene, with repairs between failed reviews |

#### (c) Local GUI

```bash
python -m gui.public --host 127.0.0.1 --port 8091
```

Open **http://127.0.0.1:8091/** and enter your topic and API key.

### 4. Project Organization

```text
EduCAST/
├── requirements/          # Runtime dependencies and pinned Python environment
├── educast/
│   ├── assets/            # Sample request, fonts, templates, and Remotion project
│   ├── agents/            # Planner and rendering/narration agents
│   ├── reviewloop/        # Visual review, targeted repair, and retry loop
│   ├── pipeline.py        # End-to-end orchestration
│   ├── providers/         # API clients and usage accounting
│   └── bundle/            # Media, captions, and browser player
├── gui/                   # GUI server, frontend, and website builder
├── docs/                  # Published project website and demo
└── request.json           # Editable lesson request
```

Generated lessons and API records are saved under `runs/`, which is excluded from Git.

---

## 🔍 Outputs and Review

Each completed run saves:

| Path within the run directory | Contents |
| --- | --- |
| `blueprint/lesson_blueprint.json` | Generated lesson plan |
| `media/` | Rendered videos and narration |
| `rendered_scenes.json` | Scene results and review status |
| `debug/` | Reviewer feedback and repair records |
| `bundle/index.html` | Finished lesson player |
| `result.json`, `usage.json` | Run summary and API usage |

To resume the review/repair stage from a saved run:

```bash
python -m educast --sample --run-dir runs/sample_algebra --stage 2
```

Pinned dependencies and saved requests make the workflow repeatable. Generated content and review scores can vary across API calls; a failed quality gate is reported rather than silently packaged.

---

## 🙏 Acknowledgements

EduCAST builds on [Manim Community](https://www.manim.community/), [Remotion](https://www.remotion.dev/), and [Playwright](https://playwright.dev/python/). See also our [Instructional Agents](https://darl-genai.github.io/instructional_agents_homepage/) project. README organization follows [Code2Video](https://github.com/showlab/Code2Video/).

## 📌 Citation

```bibtex
@inproceedings{chen2027educast,
  title     = {EduCAST: A Multi-Agent System for Personalized Educational Video Generation with Closed-Loop Review},
  author    = {Chen, Qingyue and Nandra, Aarshdeeep Singh and Yao, Huaiyuan and Shourie, Varun and Kazi, Rayan and Wei, Hua},
  booktitle = {Proceedings of the AAAI Conference on Artificial Intelligence (Demonstration Track)},
  year      = {2027}
}
```
