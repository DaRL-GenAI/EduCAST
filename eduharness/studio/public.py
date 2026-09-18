"""Public showcase and a dedicated lesson-creation API backed by Studio jobs.

Run behind a Cloudflare Tunnel:
    python -m eduharness.studio.public --port 8091
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import threading
import uuid
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
import re
from urllib.parse import unquote, urlparse

from ..serve import RangeHandler, ThreadingHTTPServer
from ..schema import HarnessRequest
from .server import (
    StudioHandler, _atomic_json, _capabilities, _default_request, _read_json,
    _run_dir, _run_summary, _start_job, normalize_user_api_key,
)

ASSET_DIR = Path(__file__).resolve().parent
RUNS_ROOT = ASSET_DIR.parents[1] / 'runs'
# The three finished lessons on the home page, plus the newer preview builds
# listed on /more-lessons. Membership only makes a bundle servable; whether a
# lesson reads as finished or as a preview comes from its bundle/warnings.json.
FEATURED_RUNS = frozenset({'quadratics', 'lever_v2_backup', 'ohms_law',
                           'binary', 'photosynthesis'})
_CREATE_LOCK = threading.Lock()


def public_html() -> bytes:
    html = (ASSET_DIR / 'index.html').read_text(encoding='utf-8')
    html = re.sub(r'<section\b[^>]*\bid="studio"[^>]*>.*?(?=</main>)', '', html, flags=re.S)
    html = re.sub(r'<a href="#studio">.*?</a>', '', html, flags=re.S)
    html = re.sub(r'<span class="connection" id="connection">.*?</span></span>', '', html, flags=re.S)
    html = re.sub(r'<button\b(?=[^>]*\bid="refresh")[^>]*>.*?</button>', '', html, flags=re.S)
    links = {
        'new-build': ('/new-lesson', 'button primary', 'New lesson ↗'),
        'hero-new-build': ('/new-lesson', 'text-button', 'Make something new ↗'),
        'pipeline-new-build': ('/new-lesson', 'button primary large', 'Create your lesson ↗'),
    }
    for element_id, (href, css, label) in links.items():
        pattern = rf'<button\b(?=[^>]*\bid="{element_id}")[^>]*>.*?</button>'
        html = re.sub(pattern, f'<a id="{element_id}" href="{href}" class="{css}">{label}</a>', html, flags=re.S)
    html = re.sub(r'<script src="/assets/app\.js[^\"]*"></script>',
                  '<script src="/assets/showcase.js?v=20260910"></script>', html)
    return html.encode('utf-8')


def _within_file(root: Path, relative: str) -> Path | None:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _api_available() -> bool:
    # Public generation is available with the visitor's own API key.
    return True


def _public_run(runs_root: Path, run_id: str) -> Path | None:
    try:
        run_dir = _run_dir(runs_root, run_id)
    except ValueError:
        return None
    return run_dir if (run_dir / '.studio' / 'public.json').is_file() else None


def _launch_lesson(runs_root: Path, run_id: str, api_key: str = "") -> None:
    try:
        _start_job(runs_root, run_id, 'all', api_key=api_key)
    except OSError:
        _atomic_json(runs_root / run_id / '.studio' / 'job.json', {
            'status': 'failed', 'stage': 'all', 'exit_code': None,
            'finished_at': datetime.now(timezone.utc).isoformat(),
        })


def _lesson_summary(run_dir: Path) -> dict:
    run = _run_summary(run_dir)
    job = run.get('job') or {}
    counts = run['counts']
    if job.get('status') == 'running':
        status = 'running'
    elif run['bundle_ready'] and not run['warnings'] and not counts['needs_review']:
        status = 'ready'
    elif job.get('status') == 'interrupted':
        status = 'interrupted'
    elif counts['needs_review'] or counts['review_errors'] or run['warnings']:
        status = 'needs_attention'
    elif job.get('status') == 'failed':
        status = 'failed'
    else:
        status = 'interrupted'
    phase = (run.get('run_state') or {}).get('stage')
    stage = {'1': 'Plan', '2-prepare': 'Prepare', '2-render': 'Render', '2-review': 'Review', '3': 'Bundle'}.get(phase)
    if status == 'ready':
        stage = 'Complete'
    elif not stage:
        stage = 'Plan' if not counts['planned'] else 'Bundle' if counts['passed'] == counts['total'] else 'Prepare'
    messages = {
        'running': 'Your lesson is being generated. You can leave this page and return later.',
        'ready': 'Your lesson is ready to explore.',
        'needs_attention': 'Some scenes still need review or repair. Retry generation to try again.',
        'failed': 'Generation stopped before the lesson was complete. You can retry with the same request.',
        'interrupted': 'Generation was interrupted. You can retry with the same request.',
    }
    return {
        'id': run['id'], 'topic': run['topic'], 'status': status, 'stage': stage,
        'message': messages[status], 'counts': counts, 'updated_at': run['updated_at'],
        'bundle_url': run['bundle_url'],
    }


class PublicHandler(RangeHandler):
    server_version = 'EduCastShowcase/1.0'
    runs_root: Path = RUNS_ROOT

    def public_path(self) -> Path | None:
        path = unquote(urlparse(self.path).path)
        assets = {'/assets/app.css': 'app.css', '/assets/landing.js': 'landing.js'}
        if path in {'/new-lesson', '/new-lesson/'}:
            return _within_file(ASSET_DIR / 'assets', 'new-lesson.html')
        if path in {'/more-lessons', '/more-lessons/'}:
            return _within_file(ASSET_DIR / 'assets', 'more-lessons.html')
        if path in assets:
            return _within_file(ASSET_DIR, assets[path])
        if path.startswith('/assets/'):
            return _within_file(ASSET_DIR / 'assets', path.removeprefix('/assets/'))
        match = re.fullmatch(r'/runs/([^/]+)/bundle/(.+)', path)
        if match and (match[1] in FEATURED_RUNS or _public_run(self.runs_root, match[1]) is not None):
            return _within_file(self.runs_root / match[1] / 'bundle', match[2])
        return None

    def translate_path(self, path: str) -> str:
        resolved = self.public_path()
        return str(resolved) if resolved else str(ASSET_DIR / '__not_public__')

    def send_head(self):
        if urlparse(self.path).path in {'/', '/index.html'}:
            data = public_html()
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            return BytesIO(data)
        if self.public_path() is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return None
        return super().send_head()

    def _send_json(self, payload, status=200):
        StudioHandler._send_json(self, payload, status)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == '/api/lessons/config':
            capabilities = _capabilities()
            for capability in capabilities:
                if capability.get('id') in {'image', 'narration'}:
                    capability['available'] = True
            self._send_json({
                'available': _api_available(),
                'defaults': {k: v for k, v in _default_request().items() if k != 'request_id'},
                'capabilities': capabilities,
                'user_api_key': True,
            })
            return
        match = re.fullmatch(r'/api/lessons/([0-9A-Za-z_-]+)', path)
        if match:
            run_dir = _public_run(self.runs_root, match[1])
            if run_dir is None:
                self._send_json({'error': 'Lesson not found.'}, 404)
            else:
                self._send_json({'lesson': _lesson_summary(run_dir)})
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        retry = re.fullmatch(r'/api/lessons/([0-9A-Za-z_-]+)/retry', path)
        if path != '/api/lessons' and not retry:
            self._send_json({'error': 'Endpoint not found.'}, 404)
            return
        try:
            body = StudioHandler._body(self)
            raw_api_key = body.pop('openai_api_key', '')
            try:
                api_key = normalize_user_api_key(raw_api_key)
            except ValueError:
                self._send_json({'error': 'Enter your own valid OpenAI API key to generate or retry a lesson.'}, 400)
                return
            if retry:
                run_dir = _public_run(self.runs_root, retry[1])
                if run_dir is None:
                    self._send_json({'error': 'Lesson not found.'}, 404)
                    return
                current = _lesson_summary(run_dir)
                if current['status'] not in {'running', 'ready'}:
                    _launch_lesson(self.runs_root, run_dir.name, api_key=api_key)
                self._send_json({'lesson': _lesson_summary(run_dir)}, 202)
                return
            if not isinstance(body.get('topic'), str) or not body['topic'].strip():
                self._send_json({'error': 'Please enter a lesson topic.'}, 400)
                return
            key = self.headers.get('Idempotency-Key', '').strip() or uuid.uuid4().hex
            if len(key) > 128:
                self._send_json({'error': 'Invalid submission identifier.'}, 400)
                return
            run_id = 'web_' + hashlib.sha256(key.encode()).hexdigest()[:24]
            request = HarnessRequest.model_validate({
                **body, 'topic': body['topic'].strip(), 'request_id': run_id,
                'allow_unreviewed_bundle': False,
            })
            canonical = json.dumps(request.model_dump(), sort_keys=True, ensure_ascii=True)
            fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
            with _CREATE_LOCK:
                run_dir = _run_dir(self.runs_root, run_id)
                marker = run_dir / '.studio' / 'public.json'
                if run_dir.exists():
                    previous = _read_json(marker, {})
                    if previous.get('request_hash') != fingerprint:
                        self._send_json({'error': 'This submission was already used for a different lesson. Start a new request.'}, 409)
                        return
                    self._send_json({'lesson': _lesson_summary(run_dir)}, 200)
                    return
                run_dir.mkdir(parents=True)
                _atomic_json(run_dir / 'request.json', request.model_dump())
                _atomic_json(marker, {
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'request_hash': fingerprint,
                })
                _launch_lesson(self.runs_root, run_id, api_key=api_key)
            self._send_json({'lesson': _lesson_summary(run_dir)}, 202)
        except ValueError:
            self._send_json({'error': 'Please check the lesson fields and try again.'}, 400)
        except RuntimeError:
            self._send_json({'error': 'This lesson already has an active generation job.'}, 409)
        except Exception:
            self._send_json({'error': 'Could not submit the lesson. Please try again.'}, 500)


def serve(*, runs_root: Path = RUNS_ROOT, host: str = '127.0.0.1', port: int = 8091):
    class Handler(PublicHandler):
        pass
    Handler.runs_root = runs_root.resolve()
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8091)
    args = parser.parse_args()
    server = serve(host=args.host, port=args.port)
    print(f'EduCast public showcase → http://{args.host}:{server.server_port}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
