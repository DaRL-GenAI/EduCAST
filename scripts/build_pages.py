"""Build the static GitHub Pages copy of the EduCast showcase into docs/.

GitHub Pages serves files only, so the site is the public showcase without the
generation API: `eduharness.studio.public.public_html` already strips the Studio
desk, and this script rewrites the server's absolute `/assets/...` routes into
paths relative to the published project site (https://<owner>.github.io/EduCAST/).

    python scripts/build_pages.py

The composer is the home page, and on Pages it has no backend to submit to, so
the static build swaps in a notice pointing at the local-server instructions.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eduharness.studio.public import public_html  # noqa: E402

STUDIO = ROOT / 'eduharness' / 'studio'
DOCS = ROOT / 'docs'
REPO = 'https://github.com/DaRL-GenAI/EduCAST#run-the-website'

# Files the server exposes under /assets/ but keeps beside index.html.
ROOT_ASSETS = ('app.css', 'landing.js')
# docs/ also holds the hand-written pipeline diagrams, so only the generated
# entries are cleared on rebuild.
GENERATED = ('index.html', 'assets', '.nojekyll')

STATIC_NOTE = (
    '<p class="composer-note">This published page is a static preview: generating a lesson '
    f'needs the EduCast Python server. <a href="{REPO}">Run it locally</a> to build one.</p>'
)


def rewrite_html(html: str) -> str:
    """Point the server's absolute asset routes at their published neighbours."""
    html = html.replace('"/assets/', '"assets/')
    # Nothing can reach /api/lessons from a static host, so say so up front and
    # let app.css drop the runtime "service unavailable" notice that follows it.
    html = re.sub(r'<p class="composer-note">.*?</p>', STATIC_NOTE, html, flags=re.S)
    html = html.replace('<body>', '<body data-static>', 1)
    return html


def main() -> None:
    for name in GENERATED:
        target = DOCS / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    DOCS.mkdir(exist_ok=True)

    assets = DOCS / 'assets'
    shutil.copytree(STUDIO / 'assets', assets, ignore=shutil.ignore_patterns('.DS_Store'))
    for name in ROOT_ASSETS:
        shutil.copy2(STUDIO / name, assets / name)

    (DOCS / 'index.html').write_text(
        rewrite_html(public_html().decode('utf-8')), encoding='utf-8')

    # app.css sits in assets/, so its @font-face URLs lose the /assets/ prefix.
    css = assets / 'app.css'
    css.write_text(css.read_text(encoding='utf-8').replace('url("/assets/', 'url("'), encoding='utf-8')

    # Serve assets verbatim instead of running the files through Jekyll.
    (DOCS / '.nojekyll').write_text('', encoding='utf-8')
    print(f'Built {DOCS.relative_to(ROOT)}/ from {STUDIO.relative_to(ROOT)}/')


if __name__ == '__main__':
    main()
