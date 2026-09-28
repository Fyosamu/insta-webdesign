# -*- coding: utf-8 -*-
"""Instagram publishing through the official Graph API (the only supported,
ToS-compliant route for automated publishing).

Flow for both media types is the two-step container dance:

  1. POST /{ig-user-id}/media          -> container id
  2. poll  /{ig-user-id}/media?fields=status_code until FINISHED
  3. POST /{ig-user-id}/media_publish  -> media id

Feed images  : image_url + caption            (4:5, 1080x1350)
Reels        : media_type=REELS, video_url    (9:16, 1080x1920)

Required secrets:
  IG_ACCESS_TOKEN  long-lived token from a Business/Creator account
  IG_USER_ID       the IG user id it belongs to
  PUBLIC_BASE      https base URL where the media is reachable by Meta's
                   fetcher - localhost will be rejected.

Safety gate: nothing is published unless APPROVED=1 AND DRY_RUN=0 AND both
secrets are present. Otherwise this reports exactly what would be posted.
"""
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from config import APPROVED, DRY_RUN, IG_ACCESS_TOKEN, IG_USER_ID, PUBLIC_BASE

GRAPH = "https://graph.facebook.com/v21.0"
_SSL = ssl.create_default_context()


class PublishError(RuntimeError):
    pass


def _post(path, fields, timeout=90):
    url = f"{GRAPH}/{path}"
    body = urllib.parse.urlencode(dict(fields, access_token=IG_ACCESS_TOKEN)).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded", "User-Agent": "probe"})
    try:
        with urllib.request.urlopen(req, context=_SSL, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:600]
        raise PublishError(f"{path} -> HTTP {e.code}: {detail}") from None


def _get(path, params, timeout=60):
    qs = urllib.parse.urlencode(dict(params, access_token=IG_ACCESS_TOKEN))
    req = urllib.request.Request(f"{GRAPH}/{path}?{qs}", headers={"User-Agent": "probe"})
    try:
        with urllib.request.urlopen(req, context=_SSL, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:600]
        raise PublishError(f"{path} -> HTTP {e.code}: {detail}") from None


def public_url(rel_path):
    """Absolute https URL for a file inside the repo's published folder."""
    if not PUBLIC_BASE:
        raise PublishError(
            "PUBLIC_BASE is not set. Instagram cannot fetch localhost URLs - "
            "point it at your GitHub Pages base, e.g. "
            "https://<user>.github.io/<repo>")
    rel = rel_path.replace("\\", "/").lstrip("/")
    if rel.startswith("public/"):
        rel = rel[len("public/"):]
    return PUBLIC_BASE.rstrip("/") + "/" + rel


def _ready():
    if not IG_ACCESS_TOKEN or not IG_USER_ID:
        return "IG_ACCESS_TOKEN / IG_USER_ID not set"
    if not PUBLIC_BASE:
        return "PUBLIC_BASE not set"
    # Meta's fetcher runs from its own servers and refuses to reach yours -
    # this used to be a note in the module docstring and nothing more, so a
    # local base would have passed every check and then failed on container
    # creation with a message that does not mention the URL
    if PUBLIC_BASE.startswith(("http://localhost", "http://127.",
                               "http://[::1]")):
        return ("PUBLIC_BASE points at localhost, which Instagram cannot "
                "fetch - use your GitHub Pages base instead")
    return None


def gate():
    """Return a human reason why publishing is blocked, or None when allowed."""
    reason = _ready()
    if reason:
        return reason
    if DRY_RUN:
        return "DRY_RUN=1 (dry run)"
    if not APPROVED:
        return "APPROVED=0 (approval gate not opened)"
    return None


def _wait_container(container_id, tries=60, delay=4):
    for _ in range(tries):
        st = _get(container_id, {"fields": "status_code"})
        code = st.get("status_code")
        if code == "FINISHED":
            return st
        if code in ("ERROR", "EXPIRED"):
            raise PublishError(f"container {container_id} -> {code}")
        time.sleep(delay)
    raise PublishError(f"container {container_id} timed out")


def publish_image(rel_path, caption):
    """Publish one feed image. Returns the Graph API media id."""
    blocked = gate()
    if blocked:
        return {"dry_run": True, "blocked_by": blocked,
                "would_publish": {"kind": "image", "url": rel_path,
                                  "caption": caption}}
    url = public_url(rel_path)
    c = _post(f"{IG_USER_ID}/media", {"image_url": url, "caption": caption})
    _wait_container(c["id"])
    r = _post(f"{IG_USER_ID}/media_publish", {"creation_id": c["id"]})
    return {"dry_run": False, "media_id": r.get("id"), "url": url}


def publish_reel(rel_path, caption, cover_rel=None):
    """Publish one reel. Returns the Graph API media id."""
    blocked = gate()
    if blocked:
        return {"dry_run": True, "blocked_by": blocked,
                "would_publish": {"kind": "reel", "url": rel_path,
                                  "caption": caption}}
    fields = {"media_type": "REELS", "video_url": public_url(rel_path),
              "caption": caption}
    if cover_rel:
        fields["cover_url"] = public_url(cover_rel)
    c = _post(f"{IG_USER_ID}/media", fields)
    _wait_container(c["id"], tries=90, delay=5)
    r = _post(f"{IG_USER_ID}/media_publish", {"creation_id": c["id"]})
    return {"dry_run": False, "media_id": r.get("id"),
            "url": fields["video_url"]}


def check_account():
    """Cheap self-test: is the token valid and is the account professional?"""
    if _ready():
        return {"ok": False, "reason": _ready()}
    try:
        me = _get("me", {"fields": "id,name"})
        acct = _get(IG_USER_ID, {"fields": "username,account_type"})
        return {"ok": True, "name": me.get("name"),
                "username": acct.get("username"),
                "account_type": acct.get("account_type")}
    except PublishError as e:
        return {"ok": False, "reason": str(e)}
