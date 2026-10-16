# -*- coding: utf-8 -*-
"""Drive the Graph API publish sequence against a mock - no credentials.

    python test_publish.py

`publish_image` / `publish_reel` have never actually run: every real run
stopped at the gate for want of a token, so only the "blocked" branch was
ever exercised. This stands up an HTTP server shaped like the Graph API
and walks the whole container dance:

    POST /{ig}/media         -> container id
    GET  /{ig}/container?..  -> PENDING, then FINISHED
    POST /{ig}/media_publish -> media id

The mock also resolves the media URL it is handed, the way Meta's server
does before it will report FINISHED, so a wrong or unreachable URL fails
here instead of at 2am on the first scheduled run. It recognises the path
rather than following it, so the suite does not depend on the network or
on which day is currently deployed.

Env is set before `config` is imported - those values are read once at
import time and cannot be changed afterwards.
"""
import io
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

os.environ["IG_ACCESS_TOKEN"] = "TEST_TOKEN_NOT_REAL"
os.environ["IG_USER_ID"] = "17841400000000001"
os.environ["PUBLIC_BASE"] = os.environ.get(
    "PUBLIC_BASE", "https://fyosamu.github.io/insta-webdesign")
os.environ["DRY_RUN"] = "0"
os.environ["APPROVED"] = "1"

FAILURES = []


def check(name, ok, detail=""):
    print(f"  [{'ok' if ok else 'FAIL'}] {name}"
          + (f"  - {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


# ------------------------------------------------------------------ mock --
class Graph(BaseHTTPRequestHandler):
    """A small stand-in for graph.facebook.com.

    Media reachability is decided by the *path* the URL carries, never by
    following it. Fetching the real base would tie this test to whichever
    day happens to be deployed, and deploy-pages 404s yesterday's directory
    the moment a new run lands - the suite would break overnight.
    """
    seen = []                 # every request, as (method, path, fields)
    containers = {}           # id -> {"polls": n, "fetched": [...]}
    known = set()             # media paths treated as published and reachable
    public_base = ""          # the base under test; its path is stripped
    fetch_media = True        # "GET" the media URL the way Meta does
    status_after = 2          # PENDING this many times before FINISHED
    force_status = None       # set to "ERROR" to exercise the failure path
    fetch_error = None
    account_type = "BUSINESS"   # what the `check` CLI asserts against

    def log_message(self, *a):
        pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8", "replace") if n else ""
        return dict(urllib.parse.parse_qsl(raw))

    @staticmethod
    def _route(raw_path):
        """Path as the Graph API sees it - the version prefix is transport."""
        p = urllib.parse.urlparse(raw_path).path.strip("/")
        return p[len("v21.0/"):] if p.startswith("v21.0/") else p

    def _reply(self, obj, code=200):
        blob = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def _can_fetch(self, url):
        """Meta refuses media it cannot GET - here, by recognised path.

        The URL is never followed, so the answer does not depend on the
        network or on what is currently deployed to Pages. The base's own
        path component is stripped first: `public/<day>/x.jpg` becomes
        `<day>/x.jpg`, which is what `known` holds.
        """
        if not url:
            return True
        try:
            rel = urllib.parse.urlparse(url).path.lstrip("/")
            prefix = urllib.parse.urlparse(Graph.public_base).path.strip("/")
            if prefix and rel.startswith(prefix + "/"):
                rel = rel[len(prefix) + 1:]
        except Exception as e:
            Graph.fetch_error = str(e)
            return False
        if rel not in Graph.known:
            Graph.fetch_error = f"404 {url}"
            return False
        return True

    def do_POST(self):
        fields = self._body()
        path = self._route(self.path)
        Graph.seen.append(("POST", path, fields))
        tail = path.rsplit("/", 1)[-1]

        if tail == "media":
            urls = [fields.get("image_url"), fields.get("video_url"),
                    fields.get("cover_url")]
            ok = Graph.fetch_media and all(self._can_fetch(u) for u in urls if u)
            cid = f"container_{len(Graph.containers) + 1}"
            Graph.containers[cid] = {"polls": 0, "fetched": [u for u in urls if u],
                                     "reachable": ok}
            self._reply({"id": cid})
        elif tail == "media_publish":
            cid = fields.get("creation_id")
            if cid not in Graph.containers:
                self._reply({"error": {"message": "unknown container"}}, 400)
                return
            if not Graph.containers[cid]["reachable"]:
                self._reply({"error": {"message": "media unreachable"}}, 400)
                return
            self._reply({"id": f"published_{len(Graph.containers)}"})
        else:
            self._reply({"error": {"message": f"no route /{path}"}}, 404)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = self._route(self.path)
        Graph.seen.append(("GET", path,
                           dict(urllib.parse.parse_qsl(parsed.query))))

        if path == "me":
            self._reply({"id": "1", "name": "Test User"})
            return
        cid = path.rsplit("/", 1)[-1]
        # sections 6 and 7 drive ids that were never created, to reach the
        # ERROR and timeout branches without waiting on a real container
        if Graph.force_status:
            self._reply({"id": cid, "status_code": Graph.force_status})
            return
        if cid in Graph.containers:
            c = Graph.containers[cid]
            c["polls"] += 1
            if not c["reachable"]:
                code = "ERROR"
            elif c["polls"] <= Graph.status_after:
                code = "PENDING"
            else:
                code = "FINISHED"
            self._reply({"id": cid, "status_code": code})
            return
        # /{ig-user-id}?fields=username,account_type
        self._reply({"username": "akhob59",
                     "account_type": Graph.account_type})


def start():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Graph)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v21.0"


# ------------------------------------------------------------------ tests --
def main():
    srv, base = start()
    import instagram
    instagram.GRAPH = base          # point the module at the mock
    Graph.public_base = instagram.PUBLIC_BASE
    Graph.known.update({
        "2026-09-27/post01.jpg",
        "2026-09-27/reel01.mp4",
        "2026-09-27/reel01_cover.jpg",
    })

    print("1. account self-test")
    acct = instagram.check_account()
    check("check_account sees a professional account",
          acct.get("ok") and acct.get("account_type") == "BUSINESS", str(acct))
    print("        ->", acct)

    # The README hands this command to a human, so it has to behave the way
    # the README says it does - especially the exit code, which is the only
    # thing anyone will look at when it runs unattended.
    print("\n1b. python instagram.py check (the command the README hands out)")
    code = instagram._cli(["instagram.py", "check"])
    check("exits 0 on a healthy professional account", code == 0,
          f"exit {code}")

    Graph.account_type = "PERSONAL"
    try:
        code = instagram._cli(["instagram.py", "check"])
        check("exits 1 for a personal account", code == 1, f"exit {code}")
    finally:
        Graph.account_type = "BUSINESS"

    code = instagram._cli(["instagram.py", "bogus"])
    check("an unknown subcommand exits 2 and prints usage", code == 2,
          f"exit {code}")

    print("\n2. the gate is OPEN (so the branches below really run)")
    check("gate() returns None", instagram.gate() is None, str(instagram.gate()))

    print("\n3. feed image: container -> poll -> publish")
    Graph.seen.clear()
    res = instagram.publish_image("public/2026-09-27/post01.jpg", "cap")
    check("returns dry_run False", res.get("dry_run") is False, str(res))
    check("got a media id", bool(res.get("media_id")), str(res))
    check("media id is real-looking", str(res.get("media_id", "")).startswith("published_"))
    post_paths = [p for m, p, f in Graph.seen if m == "POST"]
    check("posted /media then /media_publish",
          post_paths == [f"{os.environ['IG_USER_ID']}/media",
                         f"{os.environ['IG_USER_ID']}/media_publish"],
          str(post_paths))
    polls = [f for m, p, f in Graph.seen
             if m == "GET" and p.startswith("container_")]
    check("polled the container before publishing", len(polls) >= 2, f"{len(polls)} polls")
    # the image URL must be the public one, not the repo-relative path
    sent = [f for m, p, f in Graph.seen if m == "POST" and p.endswith("/media")]
    check("image_url is absolute https", sent and
          sent[0]["image_url"].startswith("https://")
          and "post01.jpg" in sent[0]["image_url"], str(sent[0].get("image_url")))
    print("        ->", res)

    print("\n4. reel: media_type REELS + cover")
    Graph.seen.clear()
    res = instagram.publish_reel("public/2026-09-27/reel01.mp4", "cap",
                                 cover_rel="public/2026-09-27/reel01_cover.jpg")
    check("got a media id", bool(res.get("media_id")), str(res))
    sent = [f for m, p, f in Graph.seen if m == "POST" and p.endswith("/media")]
    check("media_type is REELS", sent and sent[0].get("media_type") == "REELS")
    check("cover_url sent", sent and bool(sent[0].get("cover_url")))
    check("video_url sent", sent and sent[0]["video_url"].endswith(".mp4"))

    print("\n5. Meta could not fetch the media -> fail before publishing")
    Graph.containers.clear()
    Graph.seen.clear()
    try:
        instagram.publish_image("public/1999-01-01/nope.jpg", "cap")
        check("an unreachable image raises", False, "returned instead")
    except instagram.PublishError as e:
        check("an unreachable image raises", True)
        print("        ->", str(e)[:130])
    tails = [p.rsplit("/", 1)[-1] for m, p, f in Graph.seen if m == "POST"]
    check("media_publish was never called",
          "media_publish" not in tails, str(tails))

    print("\n6. container reports ERROR -> PublishError")
    Graph.containers.clear()
    Graph.force_status = "ERROR"
    try:
        instagram._wait_container("container_x", tries=3, delay=0)
        check("ERROR raises", False, "returned instead")
    except instagram.PublishError as e:
        check("ERROR raises", True)
        print("        ->", e)
    Graph.force_status = None

    print("\n7. container never finishes -> times out instead of hanging")
    Graph.force_status = "PENDING"
    t0 = time.time()
    try:
        instagram._wait_container("container_y", tries=3, delay=0)
        check("timeout raises", False, "returned instead")
    except instagram.PublishError as e:
        check("timeout raises after 3 tries", "timed out" in str(e), str(e))
        check("gave up quickly", time.time() - t0 < 5)
    Graph.force_status = None

    print("\n8. public_url shapes (what Meta's fetcher is pointed at)")
    u = instagram.public_url("public/2026-09-27/post01.jpg")
    check("strips the public/ prefix",
          u == f"{os.environ['PUBLIC_BASE']}/2026-09-27/post01.jpg", u)
    check("is https", u.startswith("https://"), u)
    check("never localhost",
          "localhost" not in u and "127.0.0.1" not in u, u)
    check("no doubled slash", "//" not in u[len("https://"):], u)
    check("backslashes normalised",
          instagram.public_url("public\\x.jpg").endswith("/x.jpg"))

    print("\n9. the gate still closes on every single condition")
    for label, setup, expect in (
        ("DRY_RUN=1", dict(DRY_RUN=True), "DRY_RUN"),
        ("APPROVED=0", dict(APPROVED=False), "APPROVED"),
        ("no token", dict(IG_ACCESS_TOKEN=""), "not set"),
        ("no user id", dict(IG_USER_ID=""), "not set"),
        ("no PUBLIC_BASE", dict(PUBLIC_BASE=""), "PUBLIC_BASE"),
        ("localhost PUBLIC_BASE",
         dict(PUBLIC_BASE="http://localhost:8000"), "localhost"),
    ):
        saved = {k: getattr(instagram, k) for k in setup}
        for k, v in setup.items():
            setattr(instagram, k, v)
        # both probes must run while the mutation is in place - restoring
        # in between silently re-opens the gate and the second call
        # publishes for real against the mock
        reason = instagram.gate()
        attempt = instagram.publish_image("public/2026-09-27/post01.jpg", "c")
        for k, v in saved.items():
            setattr(instagram, k, v)
        check(f"blocked by {label}", reason is not None and expect in reason,
              str(reason))
        check(f"no API call made for {label}",
              attempt.get("dry_run") is True, str(attempt)[:120])

    print("\n10. every request carried the access token")
    Graph.seen.clear()
    instagram.check_account()
    tokens = {f.get("access_token") for m, p, f in Graph.seen if m in ("GET", "POST")}
    check("token attached to every call", tokens == {"TEST_TOKEN_NOT_REAL"},
          str(tokens))

    srv.shutdown()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}")
        for f in FAILURES:
            print("   -", f)
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
