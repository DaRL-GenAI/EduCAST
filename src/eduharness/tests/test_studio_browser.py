"""Browser regressions for the public showcase and its separate Studio desk."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from eduharness.studio.server import serve


@pytest.mark.parametrize('width', [1440, 390])
def test_composer_leads_the_showcase_and_controls_work(tmp_path: Path, width: int) -> None:
    playwright = pytest.importorskip('playwright.sync_api')
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

            # The brief is the first thing on the page; progress stays out of the
            # way until a build exists.
            assert page.locator('#lesson-process').is_hidden()
            starter = page.locator('.starter-chip').first
            topic = starter.get_attribute('data-topic')
            starter.click()
            assert page.locator('#lesson-topic').input_value() == topic
            assert page.locator('#lesson-audience').input_value() == starter.get_attribute('data-audience')
            # Enter submits the composer rather than adding a line to the brief.
            page.locator('#lesson-topic').press('Enter')
            assert '\n' not in page.locator('#lesson-topic').input_value()

            page.locator('#lever-distance').fill('3')
            assert 'Balanced!' in page.locator('#balance-message').inner_text()
            page.locator('#reset-experiment').click()
            assert page.locator('#lever-distance').input_value() == '1.5'

            page.locator('#pipeline-tab-plan').focus()
            page.keyboard.press('End')
            assert page.locator('#pipeline-tab-bundle').get_attribute('aria-selected') == 'true'
            assert 'Watch a little' in page.locator('#pipeline-detail-title').inner_text()

            assert page.locator('#studio').is_hidden()
            page.locator('#new-build').click()
            assert page.locator('#request-form').is_visible()
            assert page.locator('#project-health').inner_text() == 'New request'
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
