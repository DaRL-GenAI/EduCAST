"""Browser regressions for the public showcase and its separate Studio desk."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from eduharness.schema import Manifest
from eduharness.stage3.player import write_player
from eduharness.studio.server import serve


@pytest.mark.parametrize('width', [1440, 390])
def test_demo_switch_stays_in_showcase_and_controls_work(tmp_path: Path, width: int) -> None:
    playwright = pytest.importorskip('playwright.sync_api')
    # Self-contained example fixtures exercise the real embedded player offline.
    for run, topic in [('quadratics', 'Quadratic Functions'), ('lever_v2_backup', 'Torque and Lever Balance'), ('ohms_law', 'Ohm’s Law')]:
        bundle = tmp_path / run / 'bundle'
        bundle.mkdir(parents=True)
        manifest = Manifest.model_validate({
            'bundle_id': run, 'topic': topic, 'style': {}, 'total_duration': 3600,
            'timeline': [{'id': 'intro', 'type': 'image', 'src': 'cover.svg',
                          'title': topic, 'duration': 3600, 'narration': 'Explore this lesson.'}],
        })
        (bundle / 'manifest.json').write_text(manifest.model_dump_json())
        (bundle / 'cover.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#e6eade"/></svg>')
        write_player(bundle, manifest)
    server = serve(runs_root=tmp_path, host='127.0.0.1', port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with playwright.sync_playwright() as runtime:
            try:
                browser = runtime.chromium.launch(args=['--no-sandbox'])
            except Exception as exc:
                pytest.skip(f'Chromium is unavailable: {exc}')
            page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            page.goto(f'http://127.0.0.1:{server.server_port}/', wait_until='networkidle')
            page.locator('#connection.online').wait_for(state='attached')
            assert page.locator('.demo-card').first.get_attribute('data-run') == 'quadratics'
            page.frame_locator('#demo-frame').locator('#topic').filter(has_text='Quadratic').wait_for()
            page.locator('#lever-distance').fill('3')
            assert 'Balanced!' in page.locator('#balance-message').inner_text()
            page.locator('#reset-experiment').click()
            assert page.locator('#lever-distance').input_value() == '1.5'
            # A state refresh used to bind the Studio handler to demo cards too.
            page.evaluate("document.getElementById('refresh').click()")
            page.wait_for_timeout(250)
            card = page.locator('#demo-tab-ohm')
            card.scroll_into_view_if_needed()
            before = page.evaluate('scrollY')
            card.click()
            frame = page.frame_locator('#demo-frame')
            frame.locator('#topic').filter(has_text='Ohm').wait_for()
            page.wait_for_timeout(300)
            assert page.locator('#studio').is_hidden()
            assert abs(page.evaluate('scrollY') - before) <= 2
            assert '/ohms_law/bundle/' in page.locator('#demo-frame').get_attribute('src')
            assert '/ohms_law/bundle/' in page.locator('#demo-open').get_attribute('href')
            card.press('ArrowLeft')
            frame.locator('#topic').filter(has_text='Torque').wait_for()
            assert page.locator('#demo-tab-lever').get_attribute('aria-selected') == 'true'
            assert page.locator('#demo-tab-ohm').get_attribute('aria-selected') == 'false'
            page.locator('#pipeline-tab-plan').focus()
            page.keyboard.press('End')
            assert page.locator('#pipeline-tab-bundle').get_attribute('aria-selected') == 'true'
            assert 'Watch a little' in page.locator('#pipeline-detail-title').inner_text()
            page.locator('#new-build').click()
            assert page.locator('#request-form').is_visible()
            assert page.locator('#project-health').inner_text() == 'New request'
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
