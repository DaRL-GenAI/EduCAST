"""Build the static GitHub Pages copy of the EduCast showcase into docs/.

GitHub Pages serves files only, so the site is the public showcase without the
generation API: `eduharness.studio.public.public_html` already strips the Studio
panel and swaps in showcase.js, and this script additionally rewrites the
server's absolute `/assets/...` routes into paths relative to the published
project site (https://<owner>.github.io/EduCAST/).

    python scripts/build_pages.py

The lesson players stay unavailable until the `runs/*/bundle` media is copied
into docs/runs/; landing.js and more-lessons.js already degrade to the authored
summaries when a bundle manifest is missing.
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

# Files the server exposes under /assets/ but keeps beside index.html.
ROOT_ASSETS = ('app.css', 'landing.js')
# docs/ also holds the hand-written pipeline diagrams, so only the generated
# entries are cleared on rebuild.
GENERATED = ('index.html', 'new-lesson.html', 'more-lessons.html', 'assets', '.nojekyll')


def rewrite_html(html: str) -> str:
    """Point the server's absolute routes at their published neighbours."""
    html = html.replace('"/assets/', '"assets/')
    html = re.sub(r'"/(new-lesson|more-lessons)"', r'"\1.html"', html)
    html = html.replace('"/runs/', '"runs/')
    html = html.replace('"/#', '"./#')
    html = re.sub(r'"/"', '"./"', html)
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

    # The two secondary pages are served from /new-lesson and /more-lessons.
    for name in ('new-lesson.html', 'more-lessons.html'):
        page = assets / name
        (DOCS / name).write_text(rewrite_html(page.read_text(encoding='utf-8')), encoding='utf-8')
        page.unlink()

    (DOCS / 'index.html').write_text(
        rewrite_html(public_html().decode('utf-8')), encoding='utf-8')

    # app.css sits in assets/, so its @font-face URLs lose the /assets/ prefix.
    css = assets / 'app.css'
    css.write_text(css.read_text(encoding='utf-8').replace('url("/assets/', 'url("'), encoding='utf-8')

    # The bundle fetches resolve against the published page, not the domain root.
    for name in ('landing.js', 'more-lessons.js'):
        script = assets / name
        script.write_text(script.read_text(encoding='utf-8').replace('`/runs/', '`runs/'), encoding='utf-8')

    # Serve assets verbatim instead of running the files through Jekyll.
    (DOCS / '.nojekyll').write_text('', encoding='utf-8')
    print(f'Built {DOCS.relative_to(ROOT)}/ from {STUDIO.relative_to(ROOT)}/')


if __name__ == '__main__':
    main()
