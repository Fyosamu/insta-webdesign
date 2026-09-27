# -*- coding: utf-8 -*-
"""Build one talking reel sample and drop it in a folder for review.

  python make_sample.py            ->  <sample dir>/sample.mp4

Script comes from Gemini (one call, with a written fallback), voice from
edge-tts, footage from Pexels, subtitles in the MoneyPrinterTurbo style.
Hard-limited to under 60 seconds.
"""
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SAMPLE_DIR = os.environ.get(
    "SAMPLE_DIR", r"C:\Users\USER\Desktop\uoooooo")

# Optional manual override - by default the hook is derived from the script
# so the on-screen line and the voice always say the same thing.
HOOK = os.environ.get("SAMPLE_HOOK", "")

# Used when Gemini is out of quota - written to the same length and rhythm
# as what the model returns, so the sample looks the same either way.
FALLBACK_SCRIPT = (
    # The first sentence is doing double duty: it is the hook drawn on the
    # thumbnail AND the first line spoken, so it has to work as a punchy
    # seven-word line and still lead into what follows. "Here is the truth"
    # read well aloud and said nothing on a cover image.
    "Nobody can find you online. People hear about your business, then "
    "they search your name. If nothing comes up, they move on to someone "
    "else. Your website is the first impression you never get to make in "
    "person. It also keeps working after you close. Your shop locks the "
    "door at night, but your page stays open, showing prices and taking "
    "orders at three in the morning. "
    "And you do not need to write any code or spend a big budget. One "
    "page with your products, your prices and a single way to pay is "
    "enough to start. "
    "So ask yourself this. If someone searched for you right now, what "
    "would they find?"
)

QUERY = os.environ.get(
    "SAMPLE_QUERY", "person working on laptop website online store")


def narration_script():
    """Returns (hook, narration) - the hook is always the first line of
    what gets spoken, so the text on screen and the voice never disagree."""
    try:
        import textgen
        schema = ('{"hook": "max 7 words, the punchiest short line of the '
                  'reel", "script": "a single spoken paragraph, 140-160 '
                  'words, plain English A1-A2, no emoji, no hashtags, no '
                  'stage directions, opens with that same hook line and '
                  'ends with one direct question to the viewer"}')
        obj = textgen.ask(
            schema, [],
            extra=("Write the narration for a 45-50 second Instagram reel "
                   "about why a small business needs a website to sell "
                   "products. One clear argument, conversational, as if "
                   "speaking to the camera. The hook must be the first "
                   "sentence of the script."),
            tries=2, expect_hook=False)
        script = str(obj.get("script") or "").strip()
        hook = str(obj.get("hook") or "").strip()
        if 110 <= len(script.split()) <= 175:
            print(f"  script from gemini ({len(script.split())} words)",
                  flush=True)
            if not hook:
                hook = _hook_from(script)
            return hook, script
        print("  script off-length, using the written one", flush=True)
    except Exception as e:
        print("  gemini unavailable, using the written script:", e,
              flush=True)
    return _hook_from(FALLBACK_SCRIPT), FALLBACK_SCRIPT


def _hook_from(script, limit=8):
    """The first sentence of the narration, trimmed to a line that fits the
    top of the frame - guarantees the on-screen hook matches the voice."""
    first = re.split(r"(?<=[.!?])\s+", script.strip())[0].strip()
    words = first.split()
    if len(words) > limit:
        words = words[:limit]
        first = " ".join(words).rstrip(",;:") + "..."
    return first


def fetch_footage(dest_dir, wanted=3):
    """Grab a few *different* portrait clips.

    A single clip is almost never as long as the narration, so having three
    means `_prepare_source` can cut between them instead of looping one
    obvious shot back on itself.
    """
    import images
    os.makedirs(dest_dir, exist_ok=True)
    got = []
    queries = (QUERY, "typing on laptop keyboard close up",
               "online shopping website on a phone",
               "small business owner packing an order",
               "woman browsing a website on her phone")
    for q in queries:
        if len(got) >= wanted:
            break
        try:
            urls = images.pexels_video(q)
        except Exception:
            urls = []
        for u in urls[:3]:
            if len(got) >= wanted:
                break
            try:
                raw = images._get(u, {}, timeout=300)
            except Exception:
                continue
            if raw and len(raw) > 200_000:
                p = os.path.join(dest_dir, f"clip{len(got)}.mp4")
                with open(p, "wb") as fh:
                    fh.write(raw)
                print(f"  footage: {q} ({len(raw)//1024} KB)", flush=True)
                got.append(p)
                break
    return got


def cached_clips(cache_dir):
    if not os.path.isdir(cache_dir):
        return []
    out = []
    for name in sorted(os.listdir(cache_dir)):
        if not name.endswith(".mp4"):
            continue
        p = os.path.join(cache_dir, name)
        if os.path.getsize(p) > 200_000:
            out.append(p)
    return out


def make_cover(workdir, video, dest, hook, seed=0):
    """The thumbnail Instagram shows in the grid.

    Taken from talk's cropped background plate (`_work/bg.mp4`) rather than
    from the finished reel. The finished frame already has the hook overlay
    and a subtitle line burned into it, and `render_cover` draws its own
    text on top - stacking three pieces of writing in one frame. The clean
    plate gives it footage to work with, and render_cover's veil does the
    rest. It is the same function the daily pipeline uses for reel covers,
    so what is reviewed here is what would ship.
    """
    import subprocess
    import render
    from config import FFMPEG

    bg = os.path.join(workdir, "bg.mp4")
    src = bg if os.path.exists(bg) else video
    poster = os.path.join(dest, "_poster.jpg")
    out = os.path.join(dest, "thumbnail.jpg")
    try:
        # a few seconds in, so the plate is not the first frame of a clip;
        # output-side seek, because the background has sparse keyframes
        subprocess.run([FFMPEG, "-y", "-i", src, "-ss", "4",
                        "-frames:v", "1", poster],
                       capture_output=True, timeout=120)
        if not os.path.exists(poster) or os.path.getsize(poster) < 5000:
            subprocess.run([FFMPEG, "-y", "-i", src, "-frames:v", "1", poster],
                           capture_output=True, timeout=120)
        if not os.path.exists(poster) or os.path.getsize(poster) < 5000:
            return None
        render.render_cover(poster, out, hook, hook=hook, seed=seed)
        return out if os.path.exists(out) else None
    except Exception as e:
        print("   thumbnail skipped:", e, flush=True)
        return None
    finally:
        try:
            if os.path.exists(poster):
                os.remove(poster)
        except OSError:
            pass


def main():
    import talk

    # clear the previous output but keep the downloaded clips - they are the
    # slow part and they do not change between runs
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    cache_dir = os.path.join(SAMPLE_DIR, "footage")
    for name in ("sample.mp4", "ABOUT.txt", "script.txt"):
        p = os.path.join(SAMPLE_DIR, name)
        if os.path.exists(p):
            os.remove(p)
    shutil.rmtree(os.path.join(SAMPLE_DIR, "_work"), ignore_errors=True)
    work = os.path.join(SAMPLE_DIR, "_work")
    os.makedirs(work, exist_ok=True)

    print("1. writing the script", flush=True)
    hook, script = narration_script()
    if HOOK:
        hook = HOOK
    with open(os.path.join(SAMPLE_DIR, "script.txt"), "w",
              encoding="utf-8") as fh:
        fh.write(f"HOOK: {hook}\n\n{script}\n")
    print(f"   hook: {hook}", flush=True)
    print("   ", script[:110].replace("\n", " "), "...", flush=True)

    print("2. footage + voice-over (edge-tts)", flush=True)
    clips = cached_clips(cache_dir)
    if clips:
        print(f"  footage: {len(clips)} clips reused", flush=True)
    else:
        clips = fetch_footage(cache_dir)
    if not clips:
        print("   no footage available", flush=True)
        return 1

    print("3. rendering (voice + subtitles + footage)", flush=True)
    out = os.path.join(SAMPLE_DIR, "sample.mp4")
    t0 = time.time()
    path, items, total, spoken = talk.build(
        script, clips, out, workdir=work, hook=hook)
    print(f"   done in {time.time()-t0:.1f}s, {total:.1f}s of video, "
          f"{len(items)} subtitle plates", flush=True)
    if spoken != script:
        # _fit() cut sentences back to fit under a minute - the folder
        # must describe what is in the video, not what was asked for
        print(f"   trimmed {len(script.split())} -> {len(spoken.split())} "
              "words to fit 60s", flush=True)
        with open(os.path.join(SAMPLE_DIR, "script.txt"), "w",
                  encoding="utf-8", newline="\n") as fh:
            fh.write("HOOK:\n" + hook + "\n\nNARRATION (as spoken):\n"
                     + spoken + "\n")

    w, h, dur, has_audio = talk.probe(path)
    # the container number includes the audio, so a picture that stops early
    # still looks fine here - check the video stream on its own
    vdur = talk.video_duration(path)
    print(f"   {w}x{h}  picture {vdur:.2f}s / voice {dur:.2f}s  "
          f"audio={has_audio}", flush=True)

    if vdur and dur and vdur < dur - 0.4:
        print(f"   !! picture stops {dur-vdur:.1f}s before the voice",
              flush=True)
        return 1
    if dur >= 60:
        print("   !! over 60s", flush=True)
        return 1

    cover = make_cover(work, path, SAMPLE_DIR, hook)
    if cover:
        print("   thumbnail:", os.path.basename(cover), flush=True)
    else:
        print("   !! no thumbnail", flush=True)

    shutil.rmtree(work, ignore_errors=True)

    # a text file next to it, so the sample folder is self-explanatory
    with open(os.path.join(SAMPLE_DIR, "ABOUT.txt"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(
            "Instagram reel sample - website design niche\n"
            f"duration   : {dur:.1f}s  (limit: under 60s)\n"
            f"picture    : {vdur:.1f}s across {len(clips)} stock clips\n"
            f"format     : {w}x{h} h264 + aac\n"
            f"voice      : {talk.VOICE}  rate {talk.RATE}\n"
            f"subtitles  : MoneyPrinterTurbo style - white bold text, black\n"
            f"             outline, dark rounded plate at "
            f"{talk.PLATE_ALPHA/255:.0%} opacity, bottom of frame,\n"
            f"             {len(items)} plates timed to the spoken words\n"
            f"thumbnail  : {'thumbnail.jpg (1080x1920)' if cover else 'failed'}\n"
            "footage    : Pexels stock\n"
            "hook       : " + hook + "\n")
    print("   wrote ABOUT.txt", flush=True)
    print("\nSAMPLE:", path, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
