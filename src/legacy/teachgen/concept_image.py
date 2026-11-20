#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
concept_image.py — Turn a concept into a polished, PPT-sized teaching illustration.

Two-step pipeline (mirrors how a careful designer works):
  STEP 1.  A GPT *text* model expands your short concept into a detailed,
           well-structured ENGLISH image prompt (composition, labels, style,
           colour palette, layout, aspect ratio).
  STEP 2.  That prompt is sent to OpenAI's IMAGE API (gpt-image-1) to render
           a high-quality educational diagram, saved as PNG.

WHY TWO STEPS
-------------
Image models follow a rich, explicit English prompt far better than a terse
phrase like "explain photosynthesis". Letting a language model write the
prompt first reliably yields cleaner composition, correct labels, and a
consistent house style.

SETUP
-----
    pip install openai pillow
    export OPENAI_API_KEY="sk-..."

USAGE
-----
    # Simplest: one concept in, one PNG out
    python concept_image.py --concept "How photosynthesis works"

    # Control audience, style and output path
    python concept_image.py \
        --concept "The water cycle" \
        --audience "middle-school students" \
        --style "flat vector infographic, friendly, labelled" \
        -o water_cycle.png

    # Just print the generated prompt without spending image credits
    python concept_image.py --concept "Neural network basics" --dry-run

    # Bring your own prompt, skip step 1 entirely
    python concept_image.py --raw-prompt "A clean isometric diagram of ..."

NOTE ON SIZE
------------
gpt-image-2 supports 1024x1024, 1536x1024 (landscape), 1024x1536 (portrait).
For PPT (16:9) we request the landscape 1536x1024 (3:2) and can optionally
pad/crop to an exact 16:9 canvas with --exact-169 (needs Pillow).
"""

import argparse
import base64
import os
import sys
import textwrap

try:
    from openai import OpenAI
except ImportError:
    sys.exit("Missing dependency. Run: pip install openai")


# ----------------------------------------------------------------------
# STEP 1 — expand a concept into a detailed English image prompt via GPT
# ----------------------------------------------------------------------
PROMPT_SYSTEM = textwrap.dedent("""\
    You are an expert visual-explainer and art director. Given a teaching
    concept, you write ONE detailed English prompt for a text-to-image model
    that will produce a single polished, presentation-ready educational
    illustration (a slide-sized diagram).

    Your prompt MUST specify, in flowing prose (not a list):
      - The core idea to depict and the key labelled parts/steps.
      - A clear LEFT-TO-RIGHT or TOP-TO-BOTTOM visual flow with arrows.
      - Concrete, simple iconography/metaphors that make the idea intuitive.
      - Readable, correctly-spelled text labels for each element (keep labels
        SHORT — 1-3 words — and few, since image models mangle long text).
      - A cohesive, modern style: flat vector / clean infographic, generous
        whitespace, a restrained palette (name 2-3 hex-like colours), soft
        shadows, rounded shapes.
      - Landscape 3:2 / 16:9 composition suitable for a slide, light cream or
        white background, no photorealism, no clutter, no watermark.

    Output ONLY the final image prompt as a single paragraph. No preamble,
    no quotes, no markdown.
""")


def build_user_brief(concept: str, audience: str, style: str) -> str:
    brief = f"Concept to illustrate: {concept}\n"
    if audience:
        brief += f"Target audience: {audience}\n"
    if style:
        brief += f"Preferred visual style: {style}\n"
    brief += ("Produce the detailed English image prompt now.")
    return brief


def generate_prompt(client: OpenAI, concept: str, audience: str,
                    style: str, text_model: str) -> str:
    """STEP 1: ask a GPT text model to write the image prompt."""
    resp = client.chat.completions.create(
        model=text_model,
        messages=[
            {"role": "system", "content": PROMPT_SYSTEM},
            {"role": "user", "content": build_user_brief(concept, audience, style)},
        ],
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()


# ----------------------------------------------------------------------
# STEP 2 — render the image from the prompt via the image API
# ----------------------------------------------------------------------
def generate_image(client: OpenAI, prompt: str, image_model: str,
                   size: str, quality: str) -> bytes:
    """STEP 2: call the image API and return raw PNG bytes."""
    result = client.images.generate(
        model=image_model,
        prompt=prompt,
        size=size,           # "1536x1024" = landscape, closest to 16:9
        quality=quality,     # "low" | "medium" | "high" for gpt-image-1
        n=1,
    )
    b64 = result.data[0].b64_json
    if b64:
        return base64.b64decode(b64)
    # Some models/endpoints return a URL instead of b64; fetch it.
    import urllib.request
    url = result.data[0].url
    with urllib.request.urlopen(url) as r:
        return r.read()


# ----------------------------------------------------------------------
# Optional: pad/crop the 3:2 render to an exact 16:9 canvas
# ----------------------------------------------------------------------
def to_exact_169(png_bytes: bytes, target=(1280, 720)) -> bytes:
    """Letterbox/crop the image onto an exact 16:9 canvas (needs Pillow)."""
    from io import BytesIO
    from PIL import Image
    img = Image.open(BytesIO(png_bytes)).convert("RGB")
    tw, th = target
    # scale to cover, then center-crop to 16:9
    scale = max(tw / img.width, th / img.height)
    new = img.resize((round(img.width * scale), round(img.height * scale)))
    left = (new.width - tw) // 2
    top = (new.height - th) // 2
    cropped = new.crop((left, top, left + tw, top + th))
    out = BytesIO()
    cropped.save(out, format="PNG")
    return out.getvalue()


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Two-step: GPT writes an English prompt, then renders a "
                    "PPT-sized teaching illustration.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--concept", help="the concept to illustrate")
    src.add_argument("--raw-prompt", help="skip step 1; use this image prompt directly")

    ap.add_argument("--audience", default="", help="e.g. 'high-school students'")
    ap.add_argument("--style", default="",
                    help="visual style hint, e.g. 'flat vector infographic'")
    ap.add_argument("-o", "--output", default="concept.png", help="output PNG path")

    ap.add_argument("--text-model", default="gpt-4o-mini",
                    help="GPT text model for step 1 (default: gpt-4o-mini)")
    ap.add_argument("--image-model", default="gpt-image-2",
                    help="image model for step 2 (default: gpt-image-2)")
    ap.add_argument("--size", default="1536x1024",
                    choices=["1536x1024", "1024x1024", "1024x1536"],
                    help="image size; 1536x1024 is landscape, closest to 16:9")
    ap.add_argument("--quality", default="high",
                    choices=["low", "medium", "high"],
                    help="render quality (cost/latency tradeoff)")
    ap.add_argument("--exact-169", action="store_true",
                    help="post-process to an exact 1280x720 16:9 PNG (needs Pillow)")
    ap.add_argument("--dry-run", action="store_true",
                    help="only do step 1 and print the prompt; no image call")
    args = ap.parse_args()

    # API key check happens lazily so --dry-run with --raw-prompt could skip it,
    # but generate_prompt and generate_image both need the client.
    need_client = not (args.raw_prompt and args.dry_run)
    client = None
    if need_client:
        if not os.environ.get("OPENAI_API_KEY"):
            sys.exit("Set OPENAI_API_KEY in your environment first.")
        client = OpenAI()

    # ---- STEP 1: get the image prompt ----
    if args.raw_prompt:
        image_prompt = args.raw_prompt
        print("[step 1] using raw prompt supplied by user\n")
    else:
        print("[step 1] asking GPT to write a detailed English image prompt...")
        image_prompt = generate_prompt(
            client, args.concept, args.audience, args.style, args.text_model)

    print("----- IMAGE PROMPT -----")
    print(image_prompt)
    print("------------------------\n")

    if args.dry_run:
        print("[dry-run] stopping before the image API call.")
        return

    # ---- STEP 2: render the image ----
    print(f"[step 2] rendering with {args.image_model} at {args.size} "
          f"(quality={args.quality})...")
    png = generate_image(client, image_prompt, args.image_model,
                         args.size, args.quality)

    if args.exact_169:
        print("[post] padding/cropping to exact 16:9 (1280x720)...")
        png = to_exact_169(png)

    with open(args.output, "wb") as f:
        f.write(png)
    print(f"Saved -> {args.output}  ({len(png)//1024} KB)")


if __name__ == "__main__":
    main()
