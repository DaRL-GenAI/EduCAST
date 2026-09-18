"""Tiny static server with HTTP Range support for previewing an EduBundle.

`python -m http.server` cannot serve byte ranges, so browsers cannot seek inside
the mp4 files (and overlay triggers after a seek never fire). Usage:

    python -m eduharness.serve runs/<id>/bundle [--port 8765]
"""

from __future__ import annotations

import argparse
import os
import re
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


class RangeHandler(SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler + single-range GET (enough for <video>/<audio>)."""

    def guess_type(self, path):
        """Say utf-8 for text: pages carry τ, ×, — and default to latin-1 without it."""
        kind = super().guess_type(path)
        if kind.startswith("text/") and "charset=" not in kind:
            return f"{kind}; charset=utf-8"
        return kind

    def send_head(self):
        path = self.translate_path(self.path)
        header = self.headers.get("Range")
        if not header or os.path.isdir(path) or not os.path.isfile(path):
            return super().send_head()
        match = _RANGE.match(header.strip())
        if not match:
            return super().send_head()
        size = os.path.getsize(path)
        start_s, end_s = match.groups()
        if start_s:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
        else:  # suffix range: last N bytes
            start = max(0, size - int(end_s or 0))
            end = size - 1
        if start >= size or start > end:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None
        end = min(end, size - 1)
        fh = open(path, "rb")
        self.send_response(HTTPStatus.PARTIAL_CONTENT)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        fh.seek(start)
        self._range_left = end - start + 1
        return fh

    def copyfile(self, source, outputfile):
        left = getattr(self, "_range_left", None)
        if left is None:
            return super().copyfile(source, outputfile)
        while left > 0:
            chunk = source.read(min(65536, left))
            if not chunk:
                break
            outputfile.write(chunk)
            left -= len(chunk)
        self._range_left = None

    def end_headers(self):
        if "Accept-Ranges" not in self._headers_buffer_text():
            self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def _headers_buffer_text(self) -> str:
        try:
            return b"".join(self._headers_buffer).decode("latin-1")
        except Exception:
            return ""

    def log_message(self, format, *args):  # quieter than the default
        if os.environ.get("EDUHARNESS_SERVE_VERBOSE"):
            super().log_message(format, *args)


def serve(directory: str | Path, port: int = 8765, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    handler = partial(RangeHandler, directory=str(directory))
    return ThreadingHTTPServer((host, port), handler)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="eduharness.serve")
    p.add_argument("directory", nargs="?", default=".")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="127.0.0.1")
    args = p.parse_args(argv)
    directory = Path(args.directory).resolve()
    if not (directory / "index.html").is_file():
        raise SystemExit(f"{directory} has no index.html — point this at runs/<id>/bundle")
    server = serve(directory, args.port, args.host)
    print(f"Serving {directory} at http://{args.host}:{server.server_port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
