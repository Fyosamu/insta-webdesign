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
 "script": "ONE spoken paragraph of 140-160 words, plain English A1-A2, no emoji, no hashtags, no stage directions, opens with the hook line and ends with one question to the viewer - this is read aloud by a voice-over",
 "caption": "2-4 sentences, ends with one clear question",
 "hashtags": ["8-12, each starts with #"],
 "overlay": "max 5 words for the first frame"}"""


class CopyError(RuntimeError):
    pass


# Circuit breaker: once Gemini has refused several times in a row with a
# hard quota error, stop calling it for the rest of this process. Each
# failed call still counts against the 20-request free tier, so retrying
# blindly only makes the exhaustion worse. The fallback templates take over.
_QUOTA_STRIKES = 4
_quota_strikes = [0]
# which model to try first next time - persists across calls so a run that
# found a working model keeps using it
_model_cursor = [0]
# GEMINI_OFF=1 skips the model entirely and uses the written templates.
# Useful for a quick local run, or when you want a day of purely
# hand-checked copy without spending free-tier requests.
_gemini_down = [bool(os.environ.get("GEMINI_OFF"))]

if _gemini_down[0]:
    print("GEMINI_OFF is set - copy will come from the written templates",
          flush=True)


def _note_quota():
    _quota_strikes[0] += 1
    if _quota_strikes[0] >= _QUOTA_STRIKES:
        if not _gemini_down[0]:
            print(f"  gemini quota exhausted "
                  f"({_quota_strikes[0]} straight 429s) - switching to "
                  f"written fallback for the rest of this run", flush=True)
        _gemini_down[0] = True


def _note_success():
    _quota_strikes[0] = 0


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


def ask(schema, used, extra="", model=None, tries=7, expect_hook=True):
    """Ask Gemini for one JSON object, refusing to repeat a used hook.

    expect_hook=False is for wrappers (a whole day's batch) whose top level
    has no "hook" key - the caller validates the contents itself.
    """
    if not GEMINI_KEY:
        raise CopyError("GEMINI_KEY is not set")
    if _gemini_down[0]:
        raise CopyError("gemini circuit open (free-tier quota exhausted)")
    # Free-tier quota is per model, not per key: gemini-3.8-flash can be
    # empty while the lite models still answer. Rotate through them before
    # ever sitting in a backoff wait.
    if model:
        models = [model]
    else:
        models = [m for m in dict.fromkeys(
            [MODEL, "gemini-flash-lite-latest", "gemini-3.1-flash-lite"])]
    sys_prompt = BASE_RULES.format(niche=NICHE)
    if used:
        sys_prompt += "\nAlready used (never reuse, not even close):\n- " + "\n- ".join(sorted(used)[-400:])
    if extra:
        sys_prompt += "\n" + extra

    prompt = ("Return one JSON object matching exactly this shape:\n" + schema)

    last = ""
    mi = _model_cursor[0] % len(models)
    for attempt in range(tries):
        model = models[mi % len(models)]
        body = json.dumps({
            "system_instruction": {"parts": [{"text": sys_prompt}]},
            "contents": [{"parts": [{"text": prompt}]}],
            # 3 reels at ~160 words plus 3 captions and their hashtags comes
            # close to 2048: a truncated response is invalid JSON and would
            # silently drop the whole day back to the written templates
            "generationConfig": {"temperature": 1.0, "maxOutputTokens": 4096},
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
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} on {model}: {e}"
            if e.code in (404, 400):
                # this model name does not exist for this key - drop it
                if len(models) > 1:
                    models.pop(mi % len(models))
                    print(f"    {model} unavailable, trying next model",
                          flush=True)
                    continue
            # 429/503 are quota, not a bad prompt: try another model first,
            # and only then wait it out.
            if e.code in (429, 500, 502, 503, 504):
                tried_all = len(models) == 1
                if e.code == 429 and tried_all:
                    _note_quota()
                    if _gemini_down[0]:
                        break
                if not tried_all:
                    mi += 1
                    _model_cursor[0] = mi
                    print(f"    {model} -> {e.code}, switching to "
                          f"{models[mi % len(models)]}", flush=True)
                    continue
                wait = min(75, 15 * (2 ** attempt))
                print(f"    gemini {e.code}, backing off {wait}s "
                      f"(try {attempt + 1}/{tries})", flush=True)
                time.sleep(wait)
            else:
                time.sleep(2 + attempt * 2)
            continue
        except (urllib.error.URLError, KeyError, IndexError, ValueError,
                CopyError) as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(2 + attempt * 2)
            continue

        _note_success()
        _model_cursor[0] = mi
        if not expect_hook:
            # a wrapper object: the caller validates its contents, so just
            # make sure the model actually returned something to work with
            if not isinstance(obj, dict) or not obj:
                last = "empty object"
                time.sleep(3)
                continue
            return obj
        hook = str(obj.get("hook") or obj.get("overlay") or "").strip()
        if not hook:
            last = "empty hook"
            time.sleep(3)
            continue
        if hook.lower() in {u.lower() for u in used}:
            last = "duplicate hook"
            time.sleep(3)
            continue
        if not obj.get("hashtags"):
            obj["hashtags"] = _default_hashtags(hook)
        _paced()
        return _tidy(obj)

    raise CopyError(f"copy generation failed after {tries} tries: {last}")


_last_call = [0.0]


def _paced(min_gap=6.0):
    """Keep a floor between Gemini calls so a 6-item day never trips 429.

    Free-tier limits are per-minute; spacing the calls out costs a couple of
    minutes a day and removes the whole class of failure.
    """
    global _last_call
    delta = time.time() - _last_call[0]
    if delta < min_gap:
        time.sleep(min_gap - delta)
    _last_call[0] = time.time()


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
    if isinstance(obj.get("narration"), str):
        obj["narration"] = " ".join(obj["narration"].split())
    if isinstance(obj.get("script"), str):
        obj["script"] = " ".join(obj["script"].split())
    return obj


def post_copy(used):
    try:
        return ask(POST_SCHEMA, used,
                   extra="Format: an Instagram FEED POST (single image).")
    except CopyError as e:
        print("  gemini unavailable, using written fallback:", e, flush=True)
        return _fallback(used, kind="post")


def reel_copy(used):
    try:
        return ask(REEL_SCHEMA, used,
                   extra="Format: a 40-50s REEL with a voice-over. "
                        "The script field is the paragraph the voice reads.")
    except CopyError as e:
        print("  gemini unavailable, using written fallback:", e, flush=True)
        return _fallback(used, kind="reel")


def batch_copy(used, n_posts, n_reels):
    """All of a day's copy in ONE Gemini call.

    The free tier is 20 requests per day, so asking item-by-item spends 6 of
    them before anything else has happened. One batched call costs 1 and
    leaves the rest for retries - and for the rest of the key's other uses.
    Anything the model gets wrong or omits is filled in from the written
    templates, so a partial answer still produces a full day of content.
    """
    out = {"posts": [], "reels": [], "source": "gemini"}
    if n_posts <= 0 and n_reels <= 0:
        return out

    schema = (
        '{"posts": [' + str(n_posts) + ' objects, each shaped like: '
        + POST_SCHEMA + '], '
        '"reels": [' + str(n_reels) + ' objects, each shaped like: '
        + REEL_SCHEMA + ']}'
    )
    extra = (f"Write {n_posts} feed post(s) and {n_reels} reel(s). "
             f"Every hook must be different from every other hook you write "
             f"here as well as from the already-used list. Return exactly "
             f"{n_posts} entries in posts and {n_reels} in reels.")
    try:
        raw = ask(schema, used, extra=extra, tries=3, expect_hook=False)
    except CopyError as e:
        print("  batch copy failed, using written fallback:", e, flush=True)
        out["source"] = "fallback"
        for kind, n in (("post", n_posts), ("reel", n_reels)):
            for _ in range(n):
                item = _fallback(used + [x["hook"] for x in out["posts"]]
                                 + [x["hook"] for x in out["reels"]],
                                 kind=kind)
                out["posts" if kind == "post" else "reels"].append(item)
        return out

    # ask() returns the top-level object it extracted, which for a batch is
    # the wrapper - pull the arrays out of it.
    posts = raw.get("posts") or []
    reels = raw.get("reels") or []
    if not isinstance(posts, list):
        posts = []
    if not isinstance(reels, list):
        reels = []

    def take(arr, n, kind):
        got = []
        seen = {u.lower() for u in used}
        for item in arr[:n]:
            if not isinstance(item, dict):
                continue
            obj = _tidy(item)
            h = obj["hook"].lower()
            if not h or h in seen:
                continue
            seen.add(h)
            if kind == "reel" and not obj.get("script"):
                continue
            obj["source"] = "gemini"
            got.append(obj)
        # fill any shortfall (or a rejected duplicate) from the templates
        while len(got) < n:
            obj = _fallback([o["hook"] for o in got] +
                            [u for u in used if u], kind=kind)
            if obj["hook"].lower() not in seen:
                seen.add(obj["hook"].lower())
                obj["source"] = "fallback"
                got.append(obj)
        return got

    out["posts"] = take(posts, n_posts, "post")
    out["reels"] = take(reels, n_reels, "reel")
    return out


# --- fallback -----------------------------------------------------------
# Gemini's free tier is 20 requests. Six items a day plus a couple of
# retries can eat that, and the account must not go quiet because of it.
# These are hand-written in the same voice and are checked against
# state/seen.json exactly like the AI copy, so they never repeat either.

_TEMPLATES = [
    ("Stop selling only in your direct messages",
     ["Selling in chat means you reply to every buyer yourself.",
      "A simple website lets people browse and order without you lifting a finger.",
      "How many sales did you lose last week to slow replies?"],
     ["Most sales start with a chat message",
      "You cannot answer every message at once",
      "A website replies for you all day",
      "Buyers check your page while you sleep",
      "One link beats a hundred replies"]),
    ("Your shop should be open all night",
     ["A closed shop earns nothing.",
      "A website keeps selling at 2am, on Sunday, and while you are on holiday.",
      "When did you last make a sale while you were asleep?"],
     ["Your shop closes at six",
      "But your customers do not",
      "They keep looking after hours",
      "A website never closes",
      "Wake up to an order"]),
    ("Social media is not your real shop",
     ["One change to an algorithm and your reach disappears.",
      "A website is a place you own completely.",
      "When did your last post reach everyone who follows you?"],
     ["You do not own your followers",
      "The platform decides who sees you",
      "An algorithm can bury you overnight",
      "A website answers to nobody",
      "It is yours for good"]),
    ("People search Google before they buy from you",
     ["Someone hears about you and types your name into Google.",
      "If nothing comes up, they move on.",
      "What does Google show when people search for you?"],
     ["They heard your name",
      "So they searched for you",
      "No website, no result",
      "They chose someone else",
      "Google is the first impression"]),
    ("Make it easy for customers to pay",
     ["Every extra step costs you buyers.",
      "A website lets people see the price and pay in a few taps.",
      "How many steps does it take to buy from you right now?"],
     ["A long checkout loses people",
      "They will not fill in ten forms",
      "See the price, tap pay, done",
      "Easy buying means more sales",
      "Count your checkout steps"]),
    ("Put all your products in one clear place",
     ["Scattered posts make people hunt for prices.",
      "One page shows everything in order.",
      "Can a new customer find your full range in under a minute?"],
     ["Your products are scattered",
      "Across posts, stories and messages",
      "People give up looking",
      "One page shows everything",
      "Find it in under a minute"]),
    ("Your website works even when you stop",
     ["Ads stop the moment you stop paying.",
      "A good page keeps bringing people in for years.",
      "Which one still works when your budget runs out?"],
     ["Ads stop when the money stops",
      "Your website keeps going",
      "Old pages still bring visitors",
      "It works while you rest",
      "The cheapest employee you hire"]),
    ("A website makes a small business look big",
     ["Customers judge you in seconds, often before they message you.",
      "A clean page says you are serious.",
      "What does yours say in the first three seconds?"],
     ["Small shops get judged fast",
      "Before anyone messages you",
      "A clean page says serious",
      "A messy one says the opposite",
      "You have three seconds"]),
    ("Owning a website beats renting an audience",
     ["Followers live on a platform you do not control.",
      "Your own site is yours, and so is everyone who visits it.",
      "Where do your customers actually belong to you?"],
     ["You are renting your audience",
      "The platform can take it back",
      "Your own page is different",
      "Visitors belong to you",
      "Build on ground you own"]),
    ("Customers compare you before they message you",
     ["People look at two or three options first and pick quietly.",
      "If you are not easy to compare, you are not chosen.",
      "Who wins that silent comparison?"],
     ["They compare before they ask",
      "Three options, one winner",
      "The choice is made quietly",
      "Nobody announces their decision",
      "Be the easy one to pick"]),
    ("Your website is the best place to sell",
     ["Marketplaces charge you for every sale and show your rivals next to you.",
      "On your own page you keep the margin.",
      "How much are fees costing you each month?"],
     ["Fees on every single sale",
      "And your rivals on the same page",
      "Your own page is different",
      "Keep the margin you earned",
      "Add up this month's fees"]),
    ("Stop explaining the same things every day",
     ["The same five questions fill your inbox every week.",
      "Put the answers on one page and let it do the talking.",
      "What do you answer most often?"],
     ["The same questions weekly",
      "Answered by you every time",
      "Put the answers on a page",
      "Let it talk while you work",
      "What do you reply most?"]),
    ("A website brings local customers too",
     ["People search for things near them every day.",
      "Without a page you are invisible in that moment.",
      "Have you searched for your own service from your phone?"],
     ["People search near them daily",
      "Right when they are ready",
      "No page means invisible",
      "Be there at that moment",
      "Search your own service now"]),
    ("Your first impression happens on your website",
     ["Someone hears your name and looks you up.",
      "What they find decides everything before you speak to them.",
      "What will they find about you?"],
     ["They hear your name",
      "Then they look you up",
      "Before you ever speak",
      "That page decides it",
      "What will they find?"]),
    ("Word of mouth needs somewhere to land",
     ["A friend recommends you and the first thing that happens is a search.",
      "If there is no page, the recommendation fades.",
      "Where does your next referral go?"],
     ["Someone recommends you",
      "They search you right after",
      "No page and it fades",
      "A referral needs a landing place",
      "Where does yours go?"]),
    ("You lose money without a real website",
     ["Every day without a page is a day buyers cannot find you.",
      "They cannot check your prices, and they cannot pay you.",
      "What did yesterday cost you?"],
     ["Another day without a page",
      "Buyers cannot find you",
      "They cannot check prices",
      "They cannot pay you",
      "What did yesterday cost?"]),
    ("Your competitors already have one",
     ["While you think about it, they are being found and chosen.",
      "A page takes an afternoon, not a month.",
      "How long will you keep letting them go first?"],
     ["They are being found now",
      "And chosen while you wait",
      "It takes an afternoon",
      "Not a whole month",
      "How long will you wait?"]),
    ("One link beats ten different profiles",
     ["Ten platforms, ten bios, ten places to update.",
      "One link does the whole job.",
      "Which one do you send someone who wants to buy?"],
     ["Ten profiles to keep updated",
      "Ten bios, ten links",
      "One page does it all",
      "One link in your bio",
      "What do you actually send?"]),
    ("A Facebook page is not a website",
     ["You do not own it, you cannot design it freely, and reach keeps dropping.",
      "Treat a page as a doorway, not a home.",
      "What are you building on?"],
     ["A page is not a home",
      "You do not own it",
      "Reach keeps dropping",
      "Treat it as a doorway",
      "What are you building on?"]),
    ("Your website is open even when you are not",
     ["You are busy serving the person in front of you.",
      "The page keeps selling to everyone else.",
      "Who is serving your other customers right now?"],
     ["You are busy in the shop",
      "The page keeps selling",
      "To everyone who is not here",
      "It never takes a break",
      "Who is serving them now?"]),
    ("Show the price, lose fewer buyers",
     ["Hidden prices make people ask, and many never ask at all.",
      "Listing them openly filters for serious buyers.",
      "How many left without ever contacting you?"],
     ["Hidden prices cost buyers",
      "They will not always ask",
      "Many just leave quietly",
      "Show it openly instead",
      "How many never contacted you?"]),
    ("Turn visitors into buyers with a simple page",
     ["A clear headline, real photos, one button to buy. That is most of it.",
      "Anything more is friction.",
      "How many buttons does your visitor see before they can pay?"],
     ["A clear headline",
      "Real photos of your work",
      "One button to buy",
      "That is most of it",
      "How many buttons do they see?"]),
    ("Slow websites lose small businesses",
     ["People leave a page that takes too long, and they leave without telling you.",
      "Speed is a sales feature.",
      "How many seconds does yours take to load?"],
     ["Slow pages lose people",
      "They leave without saying",
      "You never see the bounce",
      "Speed is a sales feature",
      "How many seconds do you take?"]),
    ("Your customers already expect a website",
     ["People assume a real business has a page, the same way they assume it has a phone.",
      "Missing one now looks like a warning sign.",
      "What does your absence say about you?"],
     ["They expect a page",
      "Like they expect a phone number",
      "Not having one looks odd",
      "It reads as a warning sign",
      "What does your absence say?"]),
]


_HASHTAGS = ["#webdesign", "#websitetips", "#smallbusiness",
             "#onlinebusiness", "#digitalmarketing", "#websiteformbusiness",
             "#sellonline", "#ecommercetips", "#contentmarketing",
             "#entrepreneurtips", "#smallbiz", "#buildabrand"]


_FALLBACK_CURSOR = [0]


def _fallback(used, kind="post"):
    taken = {u.lower() for u in used}
    free = [t for t in _TEMPLATES if t[0].lower() not in taken]
    if not free:
        # everything has been used: vary the wording rather than repeat it
        free = [(f"{t[0]} - part {i + 2}", t[1], t[2])
                for i, t in enumerate(_TEMPLATES)]

    # rotate so a fresh run does not always open with the same template
    idx = (len(used) + _FALLBACK_CURSOR[0]) % len(free)
    _FALLBACK_CURSOR[0] += 1
    hook, sentences, lines = free[idx]

    caption = " ".join(sentences)
    obj = {
        "hook": hook,
        "overlay": " ".join(hook.split()[:4]),
        "caption": caption,
        "hashtags": list(_HASHTAGS),
        "source": "fallback",
    }
    if kind == "reel":
        obj["script"] = list(lines)
        # the voice reel reads a paragraph, not card lines: the caption
        # sentences plus the lines are long enough to sit under a real
        # voice-over instead of the eight seconds a card reel runs
        obj["narration"] = " ".join(sentences + lines)
    return _tidy(obj)
