# -*- coding: utf-8 -*-
"""Written copy: hooks, captions, hashtags, on-screen text - via Gemini.

Everything the account publishes is generated here, and every hook/caption is
checked against state/seen.json so nothing is ever repeated.
"""
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request

from config import GEMINI_KEY, NICHE

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
_SSL = ssl.create_default_context()

BASE_RULES = """You write scroll-stopping Instagram copy for a beginner audience.
NICHE: {niche}
Rules: plain English (A1-A2), no jargon, no "you won't believe", no "this one
trick", no claim that anything is automated or AI-made. Max 2 emoji in a
caption, never in a hook. Every output must be materially different from the
hooks you are given as "already used".
Return RAW JSON only: no markdown fences, no commentary."""

POST_SCHEMA = """{"hook": "max 8 words, the big text on the image",
 "caption": "2-4 sentences, ends with one clear question to drive comments",
 "hashtags": ["8-12, no spaces, each starts with #"],
 "overlay": "max 5 words, the text actually drawn on the image"}"""

REEL_SCHEMA = """{"hook": "max 8 words",
 "script": ["4-7 short spoken lines, 8-14 words each, conversational"],
 "caption": "2-4 sentences, ends with one clear question",
 "hashtags": ["8-12, each starts with #"],
 "overlay": "max 5 words for the first frame"}"""


class CopyError(RuntimeError):
    pass


def _extract_json(txt):
    txt = txt.strip()
    txt = re.sub(r"^```[a-zA-Z]*\s*", "", txt)
    txt = re.sub(r"\s*```$", "", txt)
    s = txt.find("{")
    if s < 0:
        raise CopyError("no '{' in model response: " + txt[:200])
    depth, in_str, esc = 0, False, False
    for i in range(s, len(txt)):
        ch = txt[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(txt[s:i + 1])
    raise CopyError("unbalanced JSON in model response")


def ask(schema, used, extra="", model=None, tries=5):
    """Ask Gemini for one JSON object, refusing to repeat a used hook."""
    if not GEMINI_KEY:
        raise CopyError("GEMINI_KEY is not set")
    model = model or MODEL
    sys_prompt = BASE_RULES.format(niche=NICHE)
    if used:
        sys_prompt += "\nAlready used (never reuse, not even close):\n- " + "\n- ".join(sorted(used)[-400:])
    if extra:
        sys_prompt += "\n" + extra

    prompt = ("Return one JSON object matching exactly this shape:\n" + schema)

    last = ""
    for attempt in range(tries):
        body = json.dumps({
            "system_instruction": {"parts": [{"text": sys_prompt}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 1.0, "maxOutputTokens": 2048},
        }).encode()
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               + model + ":generateContent")
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY})
        try:
            with urllib.request.urlopen(req, context=_SSL, timeout=90) as r:
                data = json.load(r)
            txt = data["candidates"][0]["content"]["parts"][0]["text"]
            obj = _extract_json(txt)
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError,
                IndexError, ValueError, CopyError) as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(2 + attempt * 2)
            continue

        hook = str(obj.get("hook") or obj.get("overlay") or "").strip()
        if not hook:
            last = "empty hook"
            continue
        if hook.lower() in {u.lower() for u in used}:
            last = "duplicate hook"
            continue
        if not obj.get("hashtags"):
            obj["hashtags"] = _default_hashtags(hook)
        return _tidy(obj)

    raise CopyError(f"copy generation failed after {tries} tries: {last}")


def _default_hashtags(hook):
    base = ["#webdesign", "#websitetips", "#smallbusiness",
            "#onlinebusiness", "#digitalmarketing"]
    return base


def _tidy(obj):
    obj["hook"] = str(obj.get("hook", "")).strip()[:90]
    obj["overlay"] = str(obj.get("overlay") or obj["hook"]).strip()[:60]
    obj["caption"] = str(obj.get("caption", "")).strip()[:2100]
    tags = obj.get("hashtags") or []
    clean = []
    for t in tags:
        t = str(t).strip().replace(" ", "")
        if not t:
            continue
        if not t.startswith("#"):
            t = "#" + t
        if t.lower() not in {c.lower() for c in clean}:
            clean.append(t)
    obj["hashtags"] = clean[:12]
    if isinstance(obj.get("script"), list):
        obj["script"] = [str(s).strip() for s in obj["script"] if str(s).strip()]
    return obj


def post_copy(used):
    return ask(POST_SCHEMA, used,
               extra="Format: an Instagram FEED POST (single image).")


def reel_copy(used):
    return ask(REEL_SCHEMA, used,
               extra="Format: a 15-30s REEL with a voiceover-style script.")
