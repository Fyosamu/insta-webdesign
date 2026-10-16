# -*- coding: utf-8 -*-
"""Persisted state: which hooks/captions have already been published.

Keeps the account from ever posting the same hook twice. Stored as plain
JSON so it can be committed back to the repo after each run (Actions cannot
write to your disk, only to the repository).
"""
import json
import os
import threading

LOCK = threading.Lock()

DEFAULT = {
    "hooks": [],        # every hook already used, any format
    "published": [],    # {"kind": "post"|"reel", "id": ..., "at": ..., "file": ...}
    "counters": {"post": 0, "reel": 0},
    "dates": {},        # "YYYY-MM-DD": {"post": n, "reel": n}
}


def _path(state_path):
    return state_path or os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "state", "seen.json")


def load(state_path=None):
    p = _path(state_path)
    if not os.path.exists(p):
        data = json.loads(json.dumps(DEFAULT))
    else:
        try:
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
        except (ValueError, OSError):
            data = json.loads(json.dumps(DEFAULT))
    for k, v in DEFAULT.items():
        data.setdefault(k, json.loads(json.dumps(v)))
    return data


def save(data, state_path=None):
    p = _path(state_path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with LOCK:
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    return p


def hooks(state_path=None):
    return list(load(state_path).get("hooks") or [])


def add_hook(hook, state_path=None):
    if not hook:
        return
    h = hook.strip().lower()
    if not h:
        return
    data = load(state_path)
    seen = {x.lower() for x in data["hooks"]}
    if h not in seen:
        data["hooks"].append(hook.strip())
        save(data, state_path)


def record(kind, *, hook=None, file=None, media_id=None, state_path=None,
           day=None):
    """Append a published item and bump the counters."""
    data = load(state_path)
    if hook:
        add_hook(hook, state_path)
        data = load(state_path)
    data["published"].append({
        "kind": kind, "hook": hook, "file": file,
        "media_id": media_id, "at": time_now(),
    })
    data["counters"][kind] = data["counters"].get(kind, 0) + 1
    if day:
        data["dates"].setdefault(day, {})
        data["dates"][day][kind] = data["dates"][day].get(kind, 0) + 1
    save(data, state_path)
    return data


def today(day, state_path=None):
    return load(state_path)["dates"].get(day, {})


def time_now():
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
