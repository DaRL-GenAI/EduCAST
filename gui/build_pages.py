"""Build the static GitHub Pages copy of the EduCast showcase into docs/demo/.

GitHub Pages serves files only, so the site is the public showcase without the
generation API: `gui.public.public_html` already strips the Studio
desk, and this script rewrites the server's absolute `/assets/...` routes into
paths relative to the published project site (https://<owner>.github.io/EduCAST/).

    python -m gui.build_pages          # from the repository root

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

from gui.public import public_html

STUDIO = ROOT / 'gui'
# Publish the GUI at the project root and retain its assets under /demo/.
SITE = ROOT / 'docs'
DOCS = SITE / 'demo'
REPO = 'https://github.com/DaRL-GenAI/EduCAST/tree/main#-quick-start'

# Files the server exposes under /assets/ but keeps beside index.html.
ROOT_ASSETS = ('app.css', 'landing.js')
# Only the generated entries are cleared on rebuild.
GENERATED = ('index.html', 'assets')

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



def publish_gui_home() -> None:
    """Publish the original GUI as the project home, with demo/code resources."""
    html = (DOCS / 'index.html').read_text(encoding='utf-8')
    html = html.replace('"assets/', '"./demo/assets/')
    html = re.sub(r'\s*<a href="\.\./"[^>]*><span class="nav-desktop">Project page</span><span class="nav-mobile">Resources</span></a>', '', html)
    links = ('<nav class="project-resources" aria-label="Project resources">'
             '<a class="button primary" href="./video/">'
             '<span aria-hidden="true">&#9654;</span> Watch demo</a>'
             '<a class="button" href="https://github.com/DaRL-GenAI/EduCAST">GitHub '
             '<span aria-hidden="true">&#8599;</span></a></nav>')
    html = html.replace('</head>', '<link rel="canonical" href="https://darl-genai.github.io/EduCAST/">'
                        '<style>.project-resources{display:flex;justify-content:center;flex-wrap:wrap;gap:12px;margin:22px 0 0}'
                        '.project-resources .button{min-height:44px;padding:11px 22px;font-size:13px}</style></head>')
    paper_header = (
        '<div class="paper-header">'
        '<h1 class="paper-title"><span class="paper-name">EduCAST</span>A Multi-Agent System for Personalized Educational Video Generation with Closed-Loop Review</h1>'
        '<p class="paper-authors"><span>Qingyue Chen<sup>*</sup>,</span> '
        '<span>Aarshdeeep Singh Nandra<sup>*</sup>,</span> '
        '<span>Huaiyuan Yao<sup>*</sup>,</span> <span>Varun Shourie,</span> '
        '<span>Rayan Kazi,</span> <span>Hua Wei</span></p>'
        '<p class="paper-affiliation">Arizona State University</p>'
        '<p class="paper-equal">* Equal contribution</p></div>')
    html = html.replace('<div class="compose-intro">', '<div class="compose-intro">' + paper_header, 1)
    html = html.replace('</head>', '<link rel="stylesheet" href="./static/styles/project.css?v=20261120-polish2"></head>')
    html = re.sub(r'<h1>(Start with a little.*?)</h1>', r'<h2 class="curiosity-title">\1</h2>', html, count=1, flags=re.S)
    html = re.sub(r'(<p class="compose-lede">.*?</p>)', lambda m: m.group(1) + links, html, count=1, flags=re.S)
    (SITE / 'index.html').write_text('\n'.join(line.rstrip() for line in html.splitlines()) + '\n', encoding='utf-8')


def main() -> None:
    for name in GENERATED:
        target = DOCS / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    DOCS.mkdir(parents=True, exist_ok=True)

    assets = DOCS / 'assets'
    shutil.copytree(STUDIO / 'assets', assets, ignore=shutil.ignore_patterns('.DS_Store'))
    for name in ROOT_ASSETS:
        shutil.copy2(STUDIO / name, assets / name)

    (DOCS / 'index.html').write_text(
        rewrite_html(public_html().decode('utf-8')), encoding='utf-8')

    # app.css sits in assets/, so its @font-face URLs lose the /assets/ prefix.
    css = assets / 'app.css'
    css.write_text(css.read_text(encoding='utf-8').replace('url("/assets/', 'url("'), encoding='utf-8')

    publish_gui_home()

    # Serve assets verbatim instead of running the files through Jekyll.
    (SITE / '.nojekyll').write_text('', encoding='utf-8')
    print(f'Built {DOCS} from {STUDIO.relative_to(ROOT)}/')


if __name__ == '__main__':
    main()
