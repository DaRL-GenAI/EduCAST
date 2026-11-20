"""Pack a finished EduBundle into ONE self-contained HTML file.

Every video, image, narration mp3, interactive config and the manifest are
inlined (base64 data URIs / JSON), so the page plays from a plain file open,
an e-mail attachment or a static host that cannot serve byte ranges — nothing
is fetched at runtime. The shell and player logic are the same ones the served
bundle uses; `window.EDUHARNESS_INLINE` is what makes the player read the
embedded copies instead of fetching.

    python -m eduharness.preview runs/<id>     # → runs/<id>/bundle/preview_standalone.html
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
from html import escape
from pathlib import Path

from .stage3.player import PLAYER_JS, RUNTIME_PATH, shell_html


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def build_standalone(run_dir: Path, out: Path | None = None, *, note: str = "") -> Path:
    bundle = run_dir / "bundle"
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    inline: dict[str, object] = {}

    def embed(rel: str | None) -> str | None:
        if not rel:
            return rel
        return _data_uri(bundle / rel)

    for item in manifest["timeline"]:
        item["src"] = embed(item.get("src"))
        item["audio_src"] = embed(item.get("audio_src"))
        if item.get("config_src"):
            inline[item["config_src"]] = json.loads(
                (bundle / item["config_src"]).read_text(encoding="utf-8")
            )
        for overlay in item.get("overlays", []):
            overlay["audio_src"] = embed(overlay.get("audio_src"))
            inline[overlay["config_src"]] = json.loads(
                (bundle / overlay["config_src"]).read_text(encoding="utf-8")
            )
    inline["./manifest.json"] = manifest

    payload = json.dumps(inline, ensure_ascii=False).replace("</", "<\\/")
    runtime_js = RUNTIME_PATH.read_text(encoding="utf-8")
    scripts = (
        f'  <script id="eduharness-inline" type="application/json">{payload}</script>\n'
        '  <script>window.EDUHARNESS_INLINE = '
        'JSON.parse(document.getElementById("eduharness-inline").textContent);</script>\n'
        f"  <script>{runtime_js}</script>\n"
        f"  <script>{PLAYER_JS}</script>\n"
        '  <script>window.EduHarnessPlayer.startAmbient();'
        ' window.EduHarnessPlayer.startPlayer("./manifest.json");</script>\n'
    )
    body_prefix = f'  <div id="preview-note">{escape(note)}</div>\n' if note else ""
    html = shell_html(
        manifest.get("topic", "Lesson"),
        body_prefix=body_prefix,
        scripts=scripts,
        footer_right="Standalone preview",
    )
    out = out or (bundle / "preview_standalone.html")
    out.write_text(html, encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="eduharness.preview")
    p.add_argument("run_dir")
    p.add_argument("--out", default=None)
    p.add_argument("--note", default="")
    args = p.parse_args(argv)
    out = build_standalone(Path(args.run_dir), Path(args.out) if args.out else None, note=args.note)
    print(f"Standalone preview → {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
