import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from careerviet.cv import CVService
from careerviet.cv_runtime import run_provider
from careerviet.evaluation_runtime import EvaluationProviderConfig


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_total_deadline_cancels_real_slow_provider(repo, phase):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            try:
                if phase == "headers":
                    time.sleep(0.8)
                self.send_response(200)
                self.send_header("Content-Length", "80")
                self.end_headers()
                for _ in range(80):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.02)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    s = CVService(repo)
    cv = s.create("v1", ["ev1"], language="en")
    config = EvaluationProviderConfig(
        endpoint=f"http://127.0.0.1:{server.server_port}/chat/completions",
        model="synthetic", api_key="synthetic", allow_loopback_http=True,
        timeout_seconds=0.15,
    )
    try:
        started = time.monotonic()
        with pytest.raises(RuntimeError):
            run_provider(s, cv.id, config, consent=True)
        elapsed = time.monotonic() - started
        assert elapsed < 0.55, f"deadline overrun: {elapsed:.3f}s"
        with repo.connect() as db:
            assert db.execute("SELECT count(*) FROM cv_revisions").fetchone()[0] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
