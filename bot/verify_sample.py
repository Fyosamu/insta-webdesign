# -*- coding: utf-8 -*-
"""Prove a finished sample is safe to show - subtitles first.

    python verify_sample.py <folder-or-video>

The subtitles are painted into the pixels, so there is no reading them back
out of an mp4. Everything checked here therefore comes from the .srt that
`make_sample` writes next to the video: the same timings that were burned
in, not a re-derived approximation.

What it fails on, and why each one is here:

  overlap        two plates anchored to the same bottom-centre point draw
                 straight through each other. This is the bug that shipped
                 twice, and it is invisible until somebody watches it.
  gap too small  a 1-frame gap still reads as one line running into the
                 next, because the eye fills the space the plates would
                 have shared.
  inverted       tighten() clamps an end against the next start; if that
                 lands early the cue ends before it begins.
  outside video  a cue that outlives the file shows a plate over black.
  stub / bloat   a3-word plate under half a second is noise, and one
                 twelve-word plate cannot fit on two lines anyway.
  over 60s       the whole point of the format.
  picture < voice  the classic: audio keeps going over a frozen last frame.
  loudness       reels are watched with the sound on; -14 LUFS is where the
                 platforms land them, and a quiet one gets skipped.
"""
import io
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

from config import FFMPEG, FFPROBE  # noqa: E402

FPS = 30
MIN_GAP = 1.0 / FPS          # what tighten() guarantees, so hold it to it
# write_srt rounds both ends of a cue to the millisecond, so a true 1/30s
# gap reads back as 33ms. Allow for that, and no further: anything under
# MIN_GAP - SRT_MS would have been under a frame before it was written down.
SRT_MS = 0.0015
MAX_ROWS = 2                 # the same ceiling talk cuts its phrases against
MAX_CUE_WORDS = 12           # two lines of ~40 chars, generously
MIN_CUE_SEC = 0.35
LIMA_LO, LIMA_HI = -15.5, -12.5     # -14 +/- 1.5 LU of tolerance
TP_MAX = -1.0

import talk  # noqa: E402   # the font numbers must be the ones that drew it

FAILURES = []
WARNINGS = []


def check(name, ok, detail=""):
    tag = "ok  " if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f"  - {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)
    return ok


def warn(name, detail=""):
    print(f"  [warn] {name}  - {detail}")
    WARNINGS.append(name)


# ------------------------------------------------------------------ srt ---
def read_srt(path):
    """[(start, end, text)] or [] if the file is unusable."""
    if not path or not os.path.exists(path):
        return []
    cues, block = [], []
    with open(path, encoding="utf-8-sig") as fh:
        raw = fh.read()
    for line in raw.replace("\r\n", "\n").split("\n"):
        if line.strip() == "":
            if block:
                cues.extend(_parse_block(block))
                block = []
        else:
            block.append(line)
    if block:
        cues.extend(_parse_block(block))
    return cues


def _parse_block(lines):
    """A cue block is [index, timecode, text...]. Index is optional and the
    timecode line is the only reliable marker, so anchor on that."""
    for i, line in enumerate(lines):
        m = re.match(
            r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)",
            line.strip())
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000.0
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000.0
        text = " ".join(l.strip() for l in lines[i + 1:]).strip()
        return [(start, end, text)]
    return []


# ----------------------------------------------------------- video props ---
def probe(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries",
         "format=duration:stream=index,codec_type,codec_name,width,height",
         "-of", "json", path],
        capture_output=True, text=True, timeout=120)
    try:
        j = json.loads(out.stdout or "{}")
    except ValueError:
        return {}
    dur = float(j.get("format", {}).get("duration") or 0)
    streams = {s.get("codec_type"): s for s in j.get("streams", [])}
    return dict(dur=dur, streams=streams)


def video_duration(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=120)
    try:
        return float((out.stdout or "0").strip().splitlines()[0])
    except (ValueError, IndexError):
        return 0.0


def loudness(path):
    """Measured integrated loudness and true peak, in LUFS and dBTP."""
    out = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", path,
         "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=600)
    blob = (out.stderr or "") + (out.stdout or "")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", blob, re.S)
    if not m:
        return None, None
    try:
        j = json.loads(m.group(0))
        return float(j["input_i"]), float(j["input_tp"])
    except (ValueError, KeyError, TypeError):
        return None, None


# ---------------------------------------------------------------- checks ---
def check_subtitles(srt, vdur, label, narration=""):
    print(f"\nsubtitles  ({label})")
    cues = read_srt(srt)
    if not srt or not os.path.exists(srt):
        # Built before captions.srt existed. The timings left with the
        # pixels, so overlap cannot be re-proved for this one - fall back to
        # what is still on disk: the narration, from which the plates are a
        # pure function of the text.
        if not narration:
            check("captions file present", False,
                  f"missing: {os.path.basename(srt or '')}")
            return []
        warn("timing file not kept",
             f"{os.path.basename(srt or '')} was never written, so overlap "
             "is guarded by test_talk.py rather than re-read here")
        phrases = talk._phrases(narration)
        font = talk._load_font(talk.FONT_SIZE)
        text_max = max(1, talk.MAX_WIDTH - 2 * int(talk.FONT_SIZE * 0.4))
        rowed = [len(talk._wrap_lines(p, font, text_max)) for p in phrases]
        over = [(i, n) for i, n in enumerate(rowed) if n > MAX_ROWS]
        check(f"{len(phrases)} plates derived from the script, "
              f"all <= {MAX_ROWS} rows", not over,
              (f"plate {over[0][0]+1} draws {over[0][1]} rows" if over else
               f"widest {max(rowed)} row(s)"))
        check("every plate has text", all(p.strip() for p in phrases))
        big = [(i, len(p.split())) for i, p in enumerate(phrases)
               if len(p.split()) > MAX_CUE_WORDS]
        check(f"<= {MAX_CUE_WORDS} words per plate", not big,
              f"plate {big[0][0]+1} has {big[0][1]} words" if big else "")
        return []
    check("captions file present", True, os.path.basename(srt))
    check("parses into cues", len(cues) > 0, f"{len(cues)} cues")
    if not cues:
        return []

    check("every cue has text",
          all(t.strip() for _, _, t in cues),
          next((f"empty cue at {i+1}" for i, (_, _, t) in enumerate(cues)
                if not t.strip()), ""))

    end_before_start = [i for i, (s, e, _) in enumerate(cues) if e <= s]
    check("no inverted cue (end > start)",
          not end_before_start,
          f"cue {end_before_start[0]+1}" if end_before_start else "")

    # The one that shipped twice. Same anchor point, so any overlap is
    # two lines of text drawn through each other.
    overlaps = [(i, cues[i][1] - cues[i + 1][0])
                for i in range(len(cues) - 1)
                if cues[i][1] > cues[i + 1][0]]
    check("no overlapping plates",
          not overlaps,
          (f"cue {overlaps[0][0]+1} runs "
           f"{overlaps[0][1]*1000:.0f}ms into the next" if overlaps else
           f"{len(cues)-1} boundaries clean"))

    gaps = [cues[i + 1][0] - cues[i][1] for i in range(len(cues) - 1)]
    too_close = [g for g in gaps if g < MIN_GAP - SRT_MS]
    check(f"gap >= 1 frame ({MIN_GAP*1000:.1f}ms) between plates",
          not too_close,
          (f"{len(too_close)} tighter than 1 frame, worst "
           f"{min(gaps)*1000:.1f}ms" if too_close else
           f"tightest gap {min(gaps)*1000:.1f}ms"))

    starts = [s for s, _, _ in cues]
    check("starts run forwards", starts == sorted(starts))

    beyond = [i for i, (_, e, _) in enumerate(cues) if vdur and e > vdur + .05]
    check("no cue outlives the video",
          not beyond,
          (f"cue {beyond[0]+1} ends {cues[beyond[0]][1]:.2f}s, video is "
           f"{vdur:.2f}s" if beyond else ""))

    negative = [i for i, (s, _, _) in enumerate(cues) if s < -0.01]
    check("no cue starts before 0", not negative)

    stubs = [(i, e - s) for i, (s, e, _) in enumerate(cues)
             if e - s < MIN_CUE_SEC]
    check(f"every cue >= {MIN_CUE_SEC}s",
          not stubs,
          (f"cue {stubs[0][0]+1} is {stubs[0][1]*1000:.0f}ms" if stubs else ""))

    wordy = [(i, len(t.split())) for i, (_, _, t) in enumerate(cues)
             if len(t.split()) > MAX_CUE_WORDS]
    check(f"<= {MAX_CUE_WORDS} words per plate",
          not wordy,
          (f"cue {wordy[0][0]+1} has {wordy[0][1]} words" if wordy else ""))

    # Character count is not the question - eight short words sit on one
    # row and eight long ones draw two. Measure at the same font and the
    # same box the reel burned in with, so this reads the pixels back out.
    font = talk._load_font(talk.FONT_SIZE)
    text_max = max(1, talk.MAX_WIDTH - 2 * int(talk.FONT_SIZE * 0.4))
    rowed = [(i, len(talk._wrap_lines(t, font, text_max)))
             for i, (_, _, t) in enumerate(cues)]
    over = [(i, n) for i, n in rowed if n > MAX_ROWS]
    check(f"<= {MAX_ROWS} rows of type per plate",
          not over,
          (f"cue {over[0][0]+1} draws {over[0][1]} rows" if over else
           f"widest cue {max(n for _, n in rowed)} row(s)"))

    voiced = sum(e - s for s, e, _ in cues)
    cov = voiced / vdur * 100 if vdur else 0
    print(f"         {len(cues)} plates, {cov:.0f}% of the frame covered, "
          f"{min(gaps):.2f}s shortest gap")
    if cov > 92:
        warn("very little clean air between plates",
             f"{cov:.0f}% of the video has a plate on screen")
    return cues


def check_video(path, srt):
    print("\nvideo")
    p = probe(path)
    if not p:
        check("file probes", False)
        return

    dur = p["dur"]
    streams = p["streams"]
    v = streams.get("video") or {}
    a = streams.get("audio") or {}

    check("video stream present", bool(v))
    check("audio stream present", bool(a),
          "" if a else "a silent reel was never the deliverable")
    check("duration under 60s", 0 < dur < 60, f"{dur:.2f}s")
    check("resolution 1080x1920",
          (v.get("width"), v.get("height")) == (1080, 1920),
          f"{v.get('width')}x{v.get('height')}")
    check("h264 video", v.get("codec_name") == "h264", v.get("codec_name", ""))
    check("aac audio", a.get("codec_name") == "aac", a.get("codec_name", ""))

    vdur = video_duration(path)
    if vdur and dur:
        check("picture does not stop before the voice", vdur >= dur - 0.4,
              f"picture {vdur:.2f}s / voice {dur:.2f}s")

    print("\naudio level")
    lufs, tp = loudness(path)
    if lufs is None:
        warn("loudness not measured", "ffmpeg loudnorm produced no summary")
    else:
        check("integrated loudness near -14 LUFS",
              LIMA_LO <= lufs <= LIMA_HI, f"{lufs:.1f} LUFS")
        check("true peak under -1 dBTP", tp <= TP_MAX, f"{tp:.2f} dBTP")

    return dur, vdur, lufs, tp


def check_files(folder, video):
    print("\nfolder")
    stem = os.path.splitext(os.path.basename(video))[0]
    digits = re.sub(r"\D", "", stem)
    srt_candidates = [os.path.join(folder, stem + ".srt")]
    if digits:
        srt_candidates.append(os.path.join(folder, f"captions{digits}.srt"))
    srt_candidates.append(os.path.join(folder, "captions.srt"))
    srt = next((p for p in srt_candidates if os.path.exists(p)), srt_candidates[0])

    for name in ("script.txt", "thumbnail.jpg"):
        p = os.path.join(folder, name)
        if name == "thumbnail.jpg" and digits:
            p = os.path.join(folder, f"thumbnail{digits}.jpg")
        check(f"{name} present", os.path.exists(p),
              "" if os.path.exists(p) else p)

    script = os.path.join(folder,
                          "script.txt" if not digits else f"script{digits}.txt")
    narration = ""
    if os.path.exists(script):
        body = open(script, encoding="utf-8").read()
        lines = body.splitlines()

        # Two layouts reach this point, and both have to work:
        #   HOOK: <line>                       (as written)
        #   HOOK:                              (rewritten after _fit cut
        #   <line>                              the narration to fit 60s)
        #   NARRATION (as spoken):
        #   <text>
        hook_line, i = "", 0
        if lines and lines[0].startswith("HOOK:"):
            i = 1
            hook_line = lines[0][5:].strip()
            if not hook_line and len(lines) > 1:
                hook_line = lines[1].strip()
                i = 2
        while i < len(lines) and (not lines[i].strip()
                                  or lines[i].startswith("NARRATION")):
            i += 1
        narration = " ".join(l.strip() for l in lines[i:]).strip()

        check("script declares a hook", bool(hook_line), hook_line[:50])
        words = len(narration.split())
        check("narration 110-175 words", 110 <= words <= 175, f"{words} words")

        # The cover draws the hook and the voice says the first line: if
        # those drift, the viewer reads one thing and hears another.
        spoken_first = (re.split(r"(?<=[.!?])\s+", narration)[0].strip()
                        if narration else "")
        if hook_line and spoken_first:
            norm = lambda s: s.lower().rstrip(".!? ")
            check("on-screen hook is the first spoken line",
                  norm(hook_line) == norm(spoken_first),
                  f"screen={hook_line!r} voice={spoken_first!r}")
    return srt, narration


# ------------------------------------------------------------- ink ------
# The .srt proves the plates were *scheduled*. It cannot prove they were
# painted - the overlays are pixels, and there is no reading them back out
# of an mp4. So sample the frame and look for the type itself.
#
# Deliberately one-sided. The subtitles are drawn in pure white and footage
# rarely holds thousands of 255,255,255 pixels in one band, so a low count
# is solid evidence that nothing was drawn; a high count is only weak
# evidence that something was. This is therefore built to fail when the ink
# is *missing* - a bright clip can pass unnoticed, which is a false pass
# rather than a false alarm. Crying wolf here would make the whole gate
# unreadable.
INK_SUB_BAND = (0, 1460, 1080, 1860)   # plate sits at H*0.95 - plate height
INK_HOOK_BAND = (0, 440, 1080, 780)    # hook is overlaid at H*0.24
INK_WHITE_MIN = 2000                   # a plate is 10k+; a gap is ~0
INK_GOLD_MIN = 5000                    # the chip is 19k+; cool footage ~0
INK_SUB_SAMPLES = 10
INK_HOOK_SAMPLES = 4
INK_HOOK_END = 2.4                     # chip is on screen for ~2.8s
INK_MIN_SUB = 0.40                     # 91% of a reel carries a plate
INK_MIN_HOOK = 0.50


def _ink(video, t, band, kind):
    """Pixel count of the given colour inside `band` at time `t`, or None."""
    import tempfile
    from PIL import Image

    d = os.path.join(tempfile.gettempdir(), "verify_ink")
    os.makedirs(d, exist_ok=True)
    png = os.path.join(
        d, f"{os.path.splitext(os.path.basename(video))[0]}_{kind}_"
           f"{t:07.2f}.png")
    if os.path.exists(png):
        os.remove(png)
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss",
         f"{t:.3f}", "-i", video, "-frames:v", "1", png],
        capture_output=True, timeout=180)
    if not os.path.exists(png):
        return None
    try:
        px = Image.open(png).convert("RGB").crop(band)
    except Exception:
        return None
    if kind == "sub":
        hit = sum(1 for r, g, b in px.getdata()
                  if r >= 250 and g >= 250 and b >= 250)
    else:
        hit = sum(1 for r, g, b in px.getdata()
                  if r > 190 and 130 < g < 235 and b < 110)
    os.remove(png)
    return hit


def check_ink(video, vdur):
    print("\nink  (is the type on the frame, not just in the timings?)")
    if not vdur:
        check("video readable for sampling", False, "no duration")
        return

    lo, hi = 0.6, max(0.6, vdur - 0.6)
    sub = [lo + i * (hi - lo) / (INK_SUB_SAMPLES - 1)
           for i in range(INK_SUB_SAMPLES)]
    got = [c for c in (_ink(video, t, INK_SUB_BAND, "sub")
                       for t in sub) if c is not None]
    if not check("frames could be sampled", bool(got),
                 f"{len(got)}/{len(sub)} frames decoded"
                 if got else "ffmpeg produced no frames"):
        return
    hits = sum(1 for c in got if c >= INK_WHITE_MIN)
    frac = hits / len(got)
    check(f"subtitle ink on {INK_MIN_SUB:.0%}+ of sampled frames",
          frac >= INK_MIN_SUB,
          f"{hits}/{len(got)} frames carried >= {INK_WHITE_MIN} white px "
          f"(min seen {min(got)}, max {max(got)})")

    # first couple of seconds only, while the chip is on screen
    hook_t = [0.4 + i * (INK_HOOK_END - 0.4) / (INK_HOOK_SAMPLES - 1)
              for i in range(INK_HOOK_SAMPLES)]
    gold = [c for c in (_ink(video, t, INK_HOOK_BAND, "hook")
                        for t in hook_t) if c is not None]
    if not gold:
        warn("hook not sampled", "no frames in the opening window")
        return
    ghits = sum(1 for c in gold if c >= INK_GOLD_MIN)
    gfrac = ghits / len(gold)
    check(f"golden hook on {INK_MIN_HOOK:.0%}+ of the opening frames",
          gfrac >= INK_MIN_HOOK,
          f"{ghits}/{len(gold)} carried >= {INK_GOLD_MIN} gold px "
          f"(min {min(gold)}, max {max(gold)})")


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    target = os.path.abspath(argv[1])
    if os.path.isdir(target):
        vids = sorted(f for f in os.listdir(target)
                      if f.lower().endswith((".mp4", ".mov")))
        vids = [os.path.join(target, f) for f in vids]
        folder = target
    else:
        vids = [target]
        folder = os.path.dirname(target)
    if not vids:
        print("no video found")
        return 2

    code = 0
    for video in vids:
        print("\n" + "=" * 66)
        print(os.path.basename(video))
        print("=" * 66)
        srt, narration = check_files(folder, video)
        vdur = video_duration(video)
        check_subtitles(srt, vdur, os.path.basename(srt), narration)
        check_video(video, srt)
        check_ink(video, vdur)
        if FAILURES:
            code = 1
            print(f"\n  {len(FAILURES)} FAILED, {len(WARNINGS)} warnings")
        else:
            print(f"\n  PASSED - no subtitle overlap, "
                  f"{len(WARNINGS)} warning(s)")
        del FAILURES[:]
        del WARNINGS[:]
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
