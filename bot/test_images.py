# -*- coding: utf-8 -*-
"""The transport retries, and says which of two identical-looking failures.

    python test_images.py

`images._get` had no second attempt anywhere. On a run where the stock host
refused a connection or dropped a clip halfway, `pexels_photo` and
`pexels_video` turned that into `[]`, `fetch_to` turned that into
"no image found for query", and the reel was skipped - so a network blip
and a genuinely bad search query were indistinguishable, and only one of
them is worth rewriting. The daily schedule never returns for what it
skipped, so the hole just appears in the day's output.

This drives `_get` and `fetch_to` against a local server that fails the way
a real one does: a status worth retrying, a status that is a settled
answer, and a body that is simply too small to use.
"""
import io
import os
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

import images  # noqa: E402
from PIL import Image  # noqa: E402

images.RETRY_DELAY = 0          # the backoff is not what is under test

FAILURES = []


def check(name, ok, detail=""):
    print(f"  [{'ok' if ok else 'FAIL'}] {name}"
          + (f"  - {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


# ------------------------------------------------------------------ mock --
def _jpeg():
    """A real image, big enough to clear fetch_to's 8KB floor."""
    im = Image.new("RGB", (640, 640))
    px = im.load()
    for y in range(0, 640, 4):
        for x in range(0, 640, 4):
            for dy in range(4):
                for dx in range(4):
                    px[x + dx, y + dy] = ((x * 7 + y * 3) % 256,
                                          (x ^ y) % 256,
                                          (x * 5 - y) % 256)
    import io as _io
    buf = _io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return buf.getvalue()


BODY = _jpeg()
TINY = b"too small to be an image"


class Handler(BaseHTTPRequestHandler):
    hits = {}
    fail_first = {}       # path -> how many 500s before it starts working

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        Handler.hits[path] = Handler.hits.get(path, 0) + 1
        n = Handler.hits[path]

        if path == "/gone":
            self._reply(404, b"")
        elif path == "/dead":
            self._reply(503, b"")
        elif path == "/tiny":
            self._reply(200, TINY)
        elif n <= Handler.fail_first.get(path, 0):
            self._reply(500, b"")
        else:
            self._reply(200, BODY)

    def _reply(self, code, body):
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)


def start():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


# ------------------------------------------------------------------ tests --
def main():
    srv, base = start()
    u = lambda p: base + p            # noqa: E731

    print("1. what counts as worth another attempt")
    import http.client
    import urllib.error
    check("a half-read body is transient",
          images._transient(http.client.IncompleteRead(b"abc", 100)))
    check("a refused connection is transient",
          images._transient(urllib.error.URLError(ConnectionError())))
    check("503 is transient",
          images._transient(urllib.error.HTTPError(u("/x"), 503, "no", {}, None)))
    check("429 is transient",
          images._transient(urllib.error.HTTPError(u("/x"), 429, "no", {}, None)))
    check("404 is NOT transient - it is an answer",
          not images._transient(
              urllib.error.HTTPError(u("/x"), 404, "no", {}, None)))
    check("400 is NOT transient",
          not images._transient(
              urllib.error.HTTPError(u("/x"), 400, "no", {}, None)))

    print("\n2. a status worth retrying is retried, then succeeds")
    Handler.hits.clear()
    Handler.fail_first["/flaky"] = 2
    body = images._get(u("/flaky"), {}, attempts=3)
    check("returned a full body on the third attempt", len(body) >= 8000,
          f"{len(body)} bytes")
    check("took exactly three requests", Handler.hits["/flaky"] == 3,
          f"{Handler.hits.get('/flaky')}")

    print("\n3. a status that is an answer is not retried")
    Handler.hits.clear()
    try:
        images._get(u("/gone"), {}, attempts=3)
        check("404 raises", False, "no exception")
    except Exception as e:
        check("404 raises", True)
        check("the exception carries the status",
              getattr(e, "code", None) == 404, str(e))
    check("asked exactly once", Handler.hits.get("/gone") == 1,
          f"{Handler.hits.get('/gone')} request(s)")

    print("\n4. a status worth retrying still gives up eventually")
    Handler.hits.clear()
    try:
        images._get(u("/dead"), {}, attempts=3)
        check("503 raises after the attempts run out", False, "no exception")
    except Exception:
        check("503 raises after the attempts run out", True)
    check("tried exactly the attempts allowed", Handler.hits.get("/dead") == 3,
          f"{Handler.hits.get('/dead')} request(s)")

    print("\n5. fetch_to distinguishes the two ways it can fail")
    work = tempfile.mkdtemp(prefix="images_test_")
    try:
        silent_pinterest = images.pinterest
        silent_pexels = images.pexels_photo
        silent_poll = images.pollinations
        try:
            images.pinterest = lambda *a, **k: []
            images.pexels_photo = lambda *a, **k: []
            images.pollinations = lambda *a, **k: None
            try:
                images.fetch_to("a quiet query",
                                os.path.join(work, "a.jpg"))
                check("silent sources raise", False, "no exception")
            except images.ImageError as e:
                check("silent sources are reported as unanswered",
                      "no source answered" in str(e), str(e))

            images.pinterest = lambda *a, **k: [u("/tiny")]
            images.pexels_photo = lambda *a, **k: [u("/tiny")]
            try:
                images.fetch_to("a bad query",
                                os.path.join(work, "b.jpg"))
                check("unusable candidates raise", False, "no exception")
            except images.ImageError as e:
                check("usable-looking sources that yield nothing are "
                      "reported as no image found",
                      "no image found" in str(e)
                      and "no source answered" not in str(e), str(e))

            print("\n6. a flaky candidate is retried inside the chain")
            Handler.hits.clear()
            Handler.fail_first["/flaky"] = 2
            images.pinterest = lambda *a, **k: [u("/flaky")]
            images.pexels_photo = lambda *a, **k: []
            images.pollinations = lambda *a, **k: None
            dest = os.path.join(work, "c.jpg")
            try:
                name = images.fetch_to("a query that works",
                                       dest, portrait=False)
                check("fetched and saved an image", os.path.isfile(dest),
                      "file missing")
                check("reported the source that answered it", name == "pinterest",
                      str(name))
                with Image.open(dest) as im:
                    im.verify()
                check("the saved file is a readable image", True)
            except Exception as e:
                check("fetched and saved an image", False, str(e))
        finally:
            images.pinterest = silent_pinterest
            images.pexels_photo = silent_pexels
            images.pollinations = silent_poll
    finally:
        shutil.rmtree(work, ignore_errors=True)

    srv.shutdown()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
