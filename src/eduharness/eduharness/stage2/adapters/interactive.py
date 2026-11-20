"""Interactive (JS) tool adapter — Executor fills template parameters only."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from pydantic import BaseModel, Field

from ...providers.base import Provider
from ...schema import InteractiveParams, SceneBrief, StyleConfig, SuccessCondition
from ...templates import registry

SYSTEM = """\
You are the Executor Agent for interactive teaching nodes.
You NEVER write JavaScript/HTML/React. You ONLY fill parameters for a
pre-approved parameterized template so the runtime cannot crash.

Fill values that make the exercise genuinely test the scene's learning point:
- Use the numbers/terms from the narration and brief (not generic placeholders).
- The starting state must require the student to act (unbalanced lever,
  shuffled items, empty blanks).
- Text is short, student-facing and in the lesson language. `instruction`
  tells the student exactly what to do; `hint` helps without giving the answer.
- Respect every constraint in the parameter schema (ranges, distinct choices,
  same multiset, target inside range).
"""


class _FillOut(BaseModel):
    template: str
    parameters: dict = Field(default_factory=dict)
    instruction: str = ""


def fill_interactive(
    provider: Provider,
    brief: SceneBrief,
    style: StyleConfig,
    *,
    feedback: str = "",
    prior_params: dict | None = None,
    repair_ops: list | None = None,
) -> InteractiveParams:
    template_id = brief.template or "multiple_choice"
    if template_id not in registry.list_templates():
        template_id = "multiple_choice"
    spec = registry.load_template(template_id)
    # Interactive nodes are their own practice surface.  The shared board is
    # reserved for rendered teaching media and must not frame the controls.
    teaching_layout: dict = {}
    raw_schema = json.loads(
        (registry.SCHEMAS_DIR / f"{template_id}.json").read_text(encoding="utf-8")
    ).get("parameters_schema", {})
    elements = "\n".join(f"  - {e}" for e in brief.key_elements) or "  (none listed)"

    prompt = f"""\
SCENE: {brief.id} — {brief.title}
NARRATION: {brief.narration}
VISUAL BRIEF: {brief.visual_brief}
KEY ELEMENTS:
{elements}
TEMPLATE: {template_id} — {spec.description}
TEMPLATE HINT FROM THE PLANNER: {brief.template_hint or "(none)"}
PRACTICE PANEL CONTENT:
- Title/instruction: {brief.title}
- The trusted panel owns its own layout; do not add board chrome or reveal a footer answer.

PARAMETERS (name: meaning):
{json.dumps(raw_schema, ensure_ascii=False, indent=2)}
VALIDATION SCHEMA (must satisfy):
{json.dumps(spec.parameters_schema, ensure_ascii=False)}
DEFAULTS (for reference only — replace with lesson-specific values):
{json.dumps(spec.defaults, ensure_ascii=False)}

Return JSON with keys: template ("{template_id}"), parameters, instruction.
"""
    if prior_params:
        prompt += (
            "\nPRIOR PARAMS (edit minimally; keep unchanged keys identical):\n"
            + json.dumps(prior_params, ensure_ascii=False, indent=2)
            + "\n"
        )
    if repair_ops:
        prompt += "\nSTRUCTURED REPAIR OPS (apply these precisely):\n"
        for op in repair_ops:
            dump = op.model_dump() if hasattr(op, "model_dump") else op
            prompt += f"- {dump}\n"
    if feedback:
        prompt += f"\nPREVIOUS REVIEW FEEDBACK:\n{feedback}\n"

    last_warnings: list[str] = []
    params: dict = {}
    for _ in range(2):
        raw = provider.chat_json(prompt, _FillOut, system=SYSTEM, max_tokens=3000)
        params, warnings = registry.normalize_params(template_id, raw.parameters)
        instruction = (raw.instruction or params.get("instruction") or "").strip()
        if not any("defaults restored" in w for w in warnings):
            return _finish(template_id, params, instruction, warnings, teaching_layout)
        last_warnings = warnings
        prompt += (
            "\nYOUR PREVIOUS PARAMETERS WERE REJECTED BY THE VALIDATOR:\n"
            f"{warnings[0][:900]}\nReturn corrected parameters that satisfy the schema.\n"
        )
    return _finish(template_id, params, str(params.get("instruction", "")), last_warnings, teaching_layout)


def _finish(
    template_id: str,
    params: dict,
    instruction: str,
    warnings: list[str],
    teaching_layout: dict | None = None,
) -> InteractiveParams:
    trusted_condition = registry.success_condition_for(template_id)
    return InteractiveParams(
        template=template_id,
        parameters=params,
        success_condition=SuccessCondition.model_validate(trusted_condition),
        instruction=instruction or str(params.get("instruction") or params.get("prompt") or ""),
        normalization_warnings=warnings,
        teaching_layout=teaching_layout or {},
    )


def write_interactive_json(params: InteractiveParams, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "template": params.template,
        "parameters": params.parameters,
        "success_condition": params.success_condition.model_dump(),
        "instruction": params.instruction,
        "normalization_warnings": params.normalization_warnings,
    }
    teaching_layout = params.teaching_layout
    if teaching_layout:
        payload["teaching_layout"] = teaching_layout
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def render_preview_html(
    params: InteractiveParams,
    style: StyleConfig,
    out_html: Path,
) -> Path:
    """Render the exact standalone practice runtime used by the final player."""
    out_html.parent.mkdir(parents=True, exist_ok=True)
    runtime_src = Path(__file__).resolve().parents[2] / "stage3" / "interactive_runtime.js"
    runtime_dst = out_html.parent / "interactive-runtime.js"
    runtime_dst.write_text(runtime_src.read_text(encoding="utf-8"), encoding="utf-8")
    p = style.palette
    preview_payload = {
        "template": params.template,
        "parameters": params.parameters,
        "success_condition": params.success_condition.model_dump(),
        "instruction": params.instruction,
    }
    teaching_layout = params.teaching_layout
    if teaching_layout:
        preview_payload["teaching_layout"] = teaching_layout
    payload = json.dumps(preview_payload, ensure_ascii=False).replace("</", "<\\/")
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
  :root {{ --bg:{p.background}; --primary:{p.primary}; --secondary:{p.secondary};
          --text:{p.text}; --muted:{p.muted}; --danger:{p.danger};
          --pad:{style.layout.safe_padding}; --font:"{escape(style.typography.font_family)}";
          --base-size:{style.typography.base_size}; --heading-scale:{style.typography.heading_scale};
          --layout-title-ratio:{style.layout.title_ratio};
          --layout-content-top:{style.layout.content_top_ratio};
          --layout-content-bottom:{style.layout.content_bottom_ratio};
          --layout-text-ratio:{style.layout.text_ratio};
          --layout-visual-ratio:{style.layout.visual_ratio};
          --layout-gap-ratio:{style.layout.content_gap_ratio}; }}
  * {{ box-sizing:border-box; }}
  html, body {{ margin:0; width:{style.layout.width}px; height:{style.layout.height}px; overflow:hidden; }}
  body {{ font-family:var(--font),"Liberation Sans",sans-serif; font-size:var(--base-size);
         background:var(--bg); color:var(--text); }}
  #stage {{ position:relative; width:100%; height:100%; }}
  #interactive {{ position:absolute; inset:0; padding:var(--pad); overflow:hidden;
                  container-type:size; container-name:stage; }}
</style></head>
<body><main id="stage"><div id="interactive"></div></main>
<script id="config" type="application/json">{payload}</script>
<script src="./interactive-runtime.js"></script>
<script>
  const config = JSON.parse(document.getElementById("config").textContent);
  window.EduHarnessInteractive.mountInteractive(
    document.getElementById("interactive"), config, {{onSuccess: () => {{}}}}
  );
</script>
</body></html>"""
    out_html.write_text(html, encoding="utf-8")
    return out_html
