# -*- coding: utf-8 -*-
"""The daily pipeline: make N feed posts + N reels, then publish them.

  python -m pipeline                 # dry run, writes out/ and reports
  DRY_RUN=0 APPROVED=1 python -m pipeline

Order of work per item:
  1. copy      - Gemini writes hook/caption/hashtags (never repeating one)
  2. media     - Pexels photo or stock clip (Pinterest/Pollinations fallback)
  3. render    - PIL for posts, ffmpeg for reels
  4. publish   - Graph API, behind the safety gate
  5. state     - record it so the next run picks a fresh hook
"""
import datetime as dt
import json
import os
import random
import re
import shutil
import sys
import traceback

from config import (DAILY_POSTS, DAILY_REELS, OUT, REEL_SECONDS)
import images
import instagram
import render
import reel as reelmod
import state
import textgen

# Topics stay inside the niche the account was set up for. Each one is a
# different angle on "why a business needs a website / where to sell".
TOPICS = [
    "why every business needs a website",
    "website is the best place to sell products online",
    "customers judge a business by its website first",
    "sell products online without a marketplace fee",
    "a website works for you 24 hours a day",
    "small business without a website loses customers",
    "own your customer data instead of renting an audience",
    "a website makes a small business look trustworthy",
    "online store vs social media shop",
    "first impression happens on your website",
    "how a website brings local customers in",
    "stop paying commission on every sale",
    "your website is open even when your shop is closed",
    "one link in bio beats ten platform profiles",
    "why a Facebook page is not a website",
    "how to look bigger than your competition online",
    "the cost of not having a website",
    "a website is the cheapest employee you will ever hire",
    "turn visitors into buyers with a simple website",
    "why word of mouth needs a website to land on",
]

POST_QUERIES = [
    "modern laptop showing a website on screen",
    "small business owner using a laptop in a shop",
    "online shopping website on a smartphone screen",
    "clean desk workspace with computer showing a web page",
    "person browsing an online store on a laptop",
    "ecommerce website product page on a monitor",
    "startup team looking at a website design on screen",
    "hands typing on a laptop with a website open",
]

REEL_QUERIES = [
    "person typing on a laptop keyboard close up",
    "scrolling an online shop on a smartphone",
    "online store website browsing on a phone",
    "working on a laptop in a modern office",
    "unboxing an online order at home",
    "packing a product order for shipping",
    "shopping online on a laptop at night",
    "small business packing boxes for delivery",
]

AI_QUERIES = [
    "a clean modern website hero section on a laptop screen, "
    "bright minimal office, soft daylight, photorealistic",
    "an online store product page displayed on a monitor, "
    "modern desk, shallow depth of field, photorealistic",
]


def _day():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def _dirs(kind):
    base = os.path.join(OUT, kind, _day())
    os.makedirs(base, exist_ok=True)
    pub = os.path.join(OUT, "public", _day())
    os.makedirs(pub, exist_ok=True)
    return base, pub


def _caption(copy):
    body = [copy.get("caption", "").strip()]
    tags = " ".join(copy.get("hashtags") or [])
    if tags:
        body.append(tags)
    return "\n\n".join(x for x in body if x)


def make_post(i, used, *, seed, publish=True, copy=None):
    base, pub = _dirs("posts")
    tag = f"post{i:02d}"
    print(f"\n=== POST {tag} ===", flush=True)

    if copy is None:
        copy = textgen.post_copy(used)
    print("  hook :", copy["hook"], flush=True)

    topic = random.Random(seed + i).choice(TOPICS)
    query = random.Random(seed * 7 + i).choice(POST_QUERIES)
    seedv = seed + i * 13

    src_name = None
    img_path = os.path.join(base, f"{tag}_src.jpg")
    for attempt, q in enumerate([query, topic + " concept photo"]):
        try:
            src_name = images.fetch_to(q, img_path, prefer_ai=(attempt > 0),
                                       seed=seedv)
            break
        except images.ImageError as e:
            print("  image miss:", e, flush=True)
    if src_name is None:
        try:
            raw = images.pollinations(AI_QUERIES[i % len(AI_QUERIES)],
                                      1080, 1350, seedv)
            if raw:
                with open(img_path, "wb") as fh:
                    fh.write(raw)
                src_name = "pollinations"
        except Exception:
            pass
    if src_name is None or not os.path.exists(img_path):
        print("  !! no image available, skipping", flush=True)
        return None
    print("  image :", src_name, flush=True)

    out_path = os.path.join(pub, f"{tag}.jpg")
    render.render(img_path, out_path, copy.get("overlay") or copy["hook"],
                  hook=copy["hook"],
                  badge=f"WEBDESIGN BASICS / {i:02d}", seed=seedv)
    print("  saved :", out_path, flush=True)

    rel = os.path.relpath(out_path, OUT).replace(os.sep, "/")
    res = {"dry_run": True, "blocked_by": "render-only run"}
    if publish:
        res = instagram.publish_image(rel, _caption(copy))
        print("  publish:", json.dumps(res, ensure_ascii=False)[:300], flush=True)
        if not res.get("dry_run"):
            state.record("post", hook=copy["hook"], file=out_path,
                         media_id=res.get("media_id"), day=_day())
    return {"copy": copy, "file": out_path, "rel": rel,
            "caption": _caption(copy), "res": res}


def _narration(copy):
    """The paragraph the voice reads.

    Gemini now returns it as one string in `script`; the written templates
    still carry card lines as a list, so both shapes are accepted and joined.
    """
    for key in ("narration", "script"):
        v = copy.get(key)
        if isinstance(v, str) and v.strip():
            return " ".join(v.split())
        if isinstance(v, list) and v:
            joined = " ".join(str(x).strip() for x in v if str(x).strip())
            if joined:
                return joined
    return str(copy.get("hook") or "").strip()


def _short_lines(copy):
    """Overlay lines for the silent card reel (the fallback path)."""
    v = copy.get("script")
    if isinstance(v, list):
        out = [str(s).strip() for s in v if str(s).strip()]
        if out:
            return out[:6]
    # a spoken paragraph: cut it into sentences to stand in for card lines
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", _narration(copy))
             if p.strip()]
    return parts[:6] or [copy["hook"]]


def make_reel(i, used, *, seed, publish=True, copy=None):
    base, pub = _dirs("reels")
    tag = f"reel{i:02d}"
    print(f"\n=== REEL {tag} ===", flush=True)

    if copy is None:
        copy = textgen.reel_copy(used)
    print("  hook :", copy["hook"], flush=True)

    topic = random.Random(seed + 100 + i).choice(TOPICS)
    query = random.Random(seed * 11 + i).choice(REEL_QUERIES)
    seedv = seed + 500 + i * 17
    narration = _narration(copy)
    lines = _short_lines(copy)
    overlay = copy.get("overlay") or copy["hook"]
    print("  script:", f"{len(narration.split())} words", flush=True)

    vid_path = os.path.join(base, f"{tag}_src.mp4")
    still_path = os.path.join(base, f"{tag}_src.jpg")
    clip_dir = os.path.join(base, f"{tag}_clips")
    still, src_name, clips = False, None, []

    # Several clips, not one. The narration runs about 45s while a single
    # stock clip is usually 20-30s, and trimming it short stops the picture
    # while the voice carries on - the container duration counts the audio,
    # so nothing looks wrong until the streams are probed separately.
    # pexels_video returns several distinct results for one query.
    try:
        urls = images.pexels_video(query)
    except Exception:
        urls = []
    for n, u in enumerate(urls[:3]):
        dest = os.path.join(clip_dir, f"clip{n}.mp4")
        try:
            raw = images._get(u, {}, timeout=300)
            if raw and len(raw) > 100_000:
                os.makedirs(clip_dir, exist_ok=True)
                with open(dest, "wb") as fh:
                    fh.write(raw)
                clips.append(dest)
        except Exception as e:
            print(f"  clip {n} download miss:", e, flush=True)
    if clips:
        src_name = "pexels-video"
        vid_path = clips[0]

    if src_name is None:
        try:
            src_name = images.fetch_to(topic + " concept", still_path,
                                       portrait=True, prefer_ai=True,
                                       seed=seedv)
            still = True
        except images.ImageError as e:
            print("  !! no media, skipping:", e, flush=True)
            return None
    print("  media :", src_name, "still" if still else "video",
          f"({len(clips)} clips)" if clips else "", flush=True)

    source = still_path if still else vid_path
    out_path = os.path.join(pub, f"{tag}.mp4")
    work = os.path.join(base, f"{tag}_work")
    built = False
    try:
        # 1. the voice reel - stock footage, edge-tts narration, subtitles
        #    timed to the words. This is the format that was reviewed and
        #    approved; it runs as long as the narration needs, under 60s.
        if clips:
            try:
                import talk
                talk.build(narration, clips, out_path, workdir=work,
                           hook=overlay)
                built = True
                print(f"  voice : {talk.VOICE} @ {talk.RATE}", flush=True)
            except Exception as e:
                # TTS or the network can be down; a silent card reel still
                # gives the account something to post
                print("  voice reel failed, using the card reel:", e,
                      flush=True)

        # 2. fallback - the original silent card reel
        if not built:
            try:
                reelmod.build(source, out_path, hook=overlay,
                              lines=lines[:6], workdir=work,
                              duration=REEL_SECONDS, still=still, seed=seedv)
                built = True
            except Exception as e:
                print("  reel render failed, retrying as still image:", e,
                      flush=True)
                if still:
                    built = False
                else:
                    try:
                        src_name = images.fetch_to(topic + " concept",
                                                   still_path,
                                                   portrait=True, seed=seedv)
                        still, source = True, still_path
                        reelmod.build(source, out_path, hook=overlay,
                                      lines=lines[:6], workdir=work,
                                      duration=REEL_SECONDS, still=True,
                                      seed=seedv)
                        built = True
                    except Exception as e2:
                        print("  !! reel failed twice, skipping:", e2,
                              flush=True)
                        built = False
    finally:
        # both the plates talk drew and the downloaded clips are scratch
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(clip_dir, ignore_errors=True)

    if not built:
        return None
    print("  saved :", out_path, flush=True)

    cover_path = os.path.join(pub, f"{tag}_cover.jpg")
    try:
        if still:
            render.render_cover(source, cover_path,
                                copy.get("overlay") or copy["hook"],
                                hook=copy["hook"], seed=seedv)
        else:
            from PIL import Image
            poster = os.path.join(base, f"{tag}_poster.jpg")
            import subprocess
            from config import FFMPEG
            subprocess.run([FFMPEG, "-y", "-i", out_path, "-frames:v", "1",
                            poster], capture_output=True, timeout=120)
            render.render_cover(poster, cover_path,
                                copy.get("overlay") or copy["hook"],
                                hook=copy["hook"], seed=seedv)
    except Exception as e:
        print("  cover skipped:", e, flush=True)
        cover_path = None

    rel = lambda p: os.path.relpath(p, OUT).replace(os.sep, "/") if p else None
    rel_video = rel(out_path)
    res = {"dry_run": True, "blocked_by": "render-only run"}
    if publish:
        res = instagram.publish_reel(rel_video, _caption(copy),
                                     cover_rel=rel(cover_path))
        print("  publish:", json.dumps(res, ensure_ascii=False)[:300], flush=True)
        if not res.get("dry_run"):
            state.record("reel", hook=copy["hook"], file=out_path,
                         media_id=res.get("media_id"), day=_day())
    return {"copy": copy, "file": out_path, "rel": rel_video,
            "cover": rel(cover_path), "caption": _caption(copy), "res": res}


def run(posts=None, reels=None, seed=None, publish=True):
    posts = DAILY_POSTS if posts is None else posts
    reels = DAILY_REELS if reels is None else reels
    seed = seed if seed is not None else int(_day().replace("-", ""))

    random.seed(seed)
    day = _day()
    already = state.today(day)
    done_p = already.get("post", 0)
    done_r = already.get("reel", 0)
    print(f"day={day} already published: posts={done_p} reels={done_r}",
          flush=True)

    results = {"day": day, "publish": publish, "posts": [], "reels": [],
               "skipped": [], "errors": []}

    if publish:
        gate = instagram.gate()
        print("publish gate:", gate or "OPEN (will publish)", flush=True)
    else:
        print("publish: skipped (render-only)", flush=True)

    used = state.hooks()

    # One Gemini call for the whole day, not one per item - see batch_copy.
    print("generating copy for the batch...", flush=True)
    copies = textgen.batch_copy(used, posts, reels)
    # recorded so the report shows whether the day came from Gemini or from
    # the written templates - that is the first thing to check if copy reads
    # oddly after a quota change
    results["source"] = copies.get("source")
    print(f"  copy source: {copies.get('source')} "
          f"({len(copies['posts'])} posts, {len(copies['reels'])} reels)",
          flush=True)

    for n, i in enumerate(range(done_p + 1, max(done_p, 0) + posts + 1)):
        try:
            r = make_post(i, used, seed=seed, publish=publish,
                          copy=copies["posts"][n] if n < len(copies["posts"])
                          else None)
        except Exception as e:
            print(f"  !! post {i} error: {e}", flush=True)
            traceback.print_exc()
            results["errors"].append(f"post{i}: {e}")
            continue
        if r:
            used.append(r["copy"]["hook"].lower())
            results["posts"].append({"n": i, "hook": r["copy"]["hook"],
                                     "file": r["file"], "rel": r["rel"],
                                     "caption": r["caption"],
                                     "dry_run": r["res"].get("dry_run"),
                                     "media_id": r["res"].get("media_id")})
        else:
            results["skipped"].append(f"post{i}")

    for n, i in enumerate(range(done_r + 1, max(done_r, 0) + reels + 1)):
        try:
            r = make_reel(i, used, seed=seed, publish=publish,
                          copy=copies["reels"][n] if n < len(copies["reels"])
                          else None)
        except Exception as e:
            print(f"  !! reel {i} error: {e}", flush=True)
            traceback.print_exc()
            results["errors"].append(f"reel{i}: {e}")
            continue
        if r:
            used.append(r["copy"]["hook"].lower())
            results["reels"].append({"n": i, "hook": r["copy"]["hook"],
                                     "file": r["file"], "rel": r["rel"],
                                     "cover": r.get("cover"),
                                     "script": r["copy"].get("script") or [],
                                     "caption": r["caption"],
                                     "dry_run": r["res"].get("dry_run"),
                                     "media_id": r["res"].get("media_id")})
        else:
            results["skipped"].append(f"reel{i}")

    report = os.path.join(OUT, f"report-{day}.json")
    os.makedirs(OUT, exist_ok=True)
    with open(report, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    print("\nreport:", report, flush=True)
    print(json.dumps(results, ensure_ascii=False, indent=2)[:3000], flush=True)
    return results


def publish_report(path):
    """Second half of the split: publish an already-rendered report.

    Used by the workflow after GitHub Pages is up, because Meta's fetcher
    has to be able to GET the file *before* the container is created.
    """
    with open(path, encoding="utf-8") as fh:
        results = json.load(fh)

    gate = instagram.gate()
    print("publish gate:", gate or "OPEN (will publish)", flush=True)

    for item in results.get("posts", []):
        if not item.get("rel"):
            continue
        res = instagram.publish_image(item["rel"], item["caption"])
        print("  post", item["n"], json.dumps(res, ensure_ascii=False)[:300],
              flush=True)
        if not res.get("dry_run"):
            state.record("post", hook=item.get("hook"), file=item.get("file"),
                         media_id=res.get("media_id"), day=results.get("day"))
            item["media_id"] = res.get("media_id")
            item["dry_run"] = False

    for item in results.get("reels", []):
        if not item.get("rel"):
            continue
        res = instagram.publish_reel(item["rel"], item["caption"],
                                     cover_rel=item.get("cover"))
        print("  reel", item["n"], json.dumps(res, ensure_ascii=False)[:300],
              flush=True)
        if not res.get("dry_run"):
            state.record("reel", hook=item.get("hook"), file=item.get("file"),
                         media_id=res.get("media_id"), day=results.get("day"))
            item["media_id"] = res.get("media_id")
            item["dry_run"] = False

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    return results


if __name__ == "__main__":
    n_posts = n_reels = None
    publish = not os.environ.get("RENDER_ONLY")
    for a in sys.argv[1:]:
        if a.startswith("--posts="):
            n_posts = int(a.split("=", 1)[1])
        elif a.startswith("--reels="):
            n_reels = int(a.split("=", 1)[1])
        elif a == "--publish-only":
            import glob
            files = sorted(glob.glob(os.path.join(OUT, "report-*.json")))
            if not files:
                print("no report to publish", flush=True)
                sys.exit(1)
            publish_report(files[-1])
            sys.exit(0)
        elif a == "--render-only":
            publish = False
    run(posts=n_posts, reels=n_reels, publish=publish)
