<div align="center">

# EduCAST: A Multi-Agent System for Personalized Educational Video Generation with Closed-Loop Review

**AAAI-27 Demonstration Program**

[**Project page · all resources**](https://darl-genai.github.io/EduCAST/) · [**Demo**](https://darl-genai.github.io/EduCAST/demo/) · [**Source code**](src/) · [**Instructional Agents**](https://darl-genai.github.io/instructional_agents_homepage/)

</div>

EduCAST turns a topic, a learner profile, and a learning goal into a narrated lesson with
animations, illustrations, and interactive practice. An instructional planner writes a
learner-conditioned lesson plan, a visual designer turns each scene into animation code or an
image prompt, a rendering engine produces narrated media, and a VLM reviewer checks every scene
and repairs only the ones that fail.

![EduCAST pipeline](docs/static/images/pipeline.png)

## Repository layout

| Path | What it is | Published at |
| --- | --- | --- |
| [`docs/index.html`](docs/index.html) | Project page | <https://darl-genai.github.io/EduCAST/> |
| [`docs/demo/`](docs/demo/) | Static build of the lesson composer and showcase | <https://darl-genai.github.io/EduCAST/demo/> |
| [`src/`](src/) | Source code: the EduHarness system, the legacy pipeline, baselines, notebooks | |

GitHub Pages serves `docs/` from the `main` branch. The demo is generated; rebuild it after
changing the website under `src/eduharness/eduharness/studio/`:

```bash
cd src/eduharness
python scripts/build_pages.py      # writes ../../docs/demo/
```

## Run EduCAST locally

The online demo cannot generate lessons, because that needs the Python server and local
renderers. To run it yourself:

```bash
cd src/eduharness
python -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt
python -m eduharness.studio.public --host 127.0.0.1 --port 8091
```

Then open <http://127.0.0.1:8091/>. Full setup, including the renderers (FFmpeg, Manim,
Playwright, Remotion) and the bring-your-own-key API, is in
[`src/eduharness/README.md`](src/eduharness/README.md).

## Related projects

- [Instructional Agents](https://github.com/DaRL-GenAI/instructional_agents) (EACL 2026): multi-agent course generation, from learning objectives and syllabus to slides, scripts, and assessments. [Project page](https://darl-genai.github.io/instructional_agents_homepage/)
- [Instructional Agents Studio](https://github.com/DaRL-GenAI/instructional_agents_studio): the course-building app for instructors, `npx instructional-agents`.

## Citation

```bibtex
@inproceedings{chen2027educast,
  title     = {EduCAST: A Multi-Agent System for Personalized Educational Video Generation with Closed-Loop Review},
  author    = {Chen, Qingyue and Nandra, Aarshdeeep Singh and Yao, Huaiyuan and Shourie, Varun and Kazi, Rayan and Wei, Hua},
  booktitle = {Proceedings of the AAAI Conference on Artificial Intelligence (Demonstration Track)},
  year      = {2027}
}
```
