# -*- coding: utf-8 -*-
"""Guard the two subtitle bugs that already shipped once each.

  python test_talk.py            # offline, no network, a second
  python test_talk.py --live     # also synthesizes real speech

The failures these catch:

1. overlap - a plate's end used to carry a 0.25s floor that ran past the
   next plate's start. Every plate sits on the same bottom-centre anchor,
   so the two lines of text drew straight through each other. It only showed
   up by eye in the finished video, six pairs deep.

2. stubs - splitting at a fixed word boundary left a remainder (a 12-word
   sentence became 9 + 3), and that 3-word stub got a plate of its own for
   less than half a second.

Both are pure timing, so they are tested without rendering anything.
"""
import os
import sys
import io

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

import talk

FAILURES = []


def check(name, ok, detail=""):
    print(f"  [{'ok' if ok else 'FAIL'}] {name}"
          + (f"  - {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


# ------------------------------------------------------------- fixtures --
SCRIPT = (
    "Here is the truth. People hear about your business, then they search "
    "your name. If nothing comes up they move on to someone else, which "
    "means the sale never happened at all. "
    "Your website is the first impression you never get to make in person. "
    "It also keeps working after you close the door at night. "
    "So ask yourself this. What would a stranger find?"
)


def fake_words(text, wpm=196, pause=0.10):
    """Word boundaries shaped like edge-tts's: (start, duration, word).

    Deliberately generous pauses, because that is exactly the shape that
    used to break - a long pause makes the 0.25s floor overrun into the
    phrase that follows it.
    """
    out, t = [], 0.0
    for w in text.split():
        dur = max(0.12, min(0.7, len(w) * 0.055))
        out.append((t, dur, w.strip(",.!?")))
        t += dur + pause
    return out


def pipeline_timings(text, words, total):
    """Exactly what build() does, minus the ffmpeg."""
    return talk.tighten(talk.subtitle_items(text, words, total), total)


def assert_disjoint(name, items, total, fps=talk.FPS):
    bad = []
    for i in range(len(items) - 1):
        gap = items[i + 1][0] - items[i][1]
        # inclusive between(): matching ends still light both up for a frame
        if gap < 1.0 / fps - 1e-9:
            bad.append((i, round(gap, 3)))
    check(name, not bad, f"overlaps at {bad}")

    inside = [t for s, e, t in items if s < 0 or e > total + 1e-6]
    check(f"{name}: inside 0..{total:.1f}s", not inside, str(inside[:2]))


# ---------------------------------------------------------------- tests --
def test_overlap_offline():
    print("\n1. no two plates on screen at once (offline)")
    words = fake_words(SCRIPT)
    total = words[-1][0] + words[-1][1] + 0.4
    raw = talk.subtitle_items(SCRIPT, words, total)
    check("phrases produced", len(raw) >= 5, f"{len(raw)} plates")

    # the raw timings are expected to overlap - that is the bug being
    # guarded against - so first prove the problem exists, then the fix
    naive = [(s, min(e + 0.15, total), t) for s, e, t in raw]
    naive_bad = sum(1 for i in range(len(naive) - 1)
                    if naive[i + 1][0] < naive[i][1])
    print(f"         (unclamped would overlap {naive_bad} times)")

    items = pipeline_timings(SCRIPT, words, total)
    assert_disjoint("no overlap", items, total)
    check("plates survived", len(items) >= 4, f"{len(items)} plates")


def test_no_stubs():
    print("\n2. sentences split into equal pieces, not 9+3")
    for n, limit in ((12, 9), (14, 9), (10, 9), (9, 9), (25, 9), (3, 9)):
        pieces = talk._chunks(list(range(n)), limit)
        sizes = [len(p) for p in pieces]
        biggest, smallest = max(sizes), min(sizes)
        # a stub is a piece less than a third the size of its siblings
        ok = smallest >= max(3, biggest // 3) or len(pieces) == 1
        check(f"{n} words / limit {limit} -> {sizes}", ok,
              f"stub of {smallest} vs {biggest}")

    # the case from the report: 12 words used to become 9 + 3
    check("12 words no longer 9+3", talk._chunks(list(range(12)), 9) !=
          [list(range(9)), list(range(9, 12))],
          "still splits 9+3")


def test_plate_geometry():
    print("\n3. plate is drawn inside the frame")
    import tempfile
    d = tempfile.mkdtemp(prefix="plate_")
    for phrase in ("A website belongs to you.",
                   "It is your own digital house on the internet, and people "
                   "can reach it at any hour of the day from anywhere.",
                   "money."):
        p = os.path.join(d, "p.png")
        w, h = talk.render_plate(p, phrase)
        check(f"{len(phrase)} chars -> {w}x{h}",
              0 < w <= talk.MAX_WIDTH and h > talk.FONT_SIZE,
              f"w={w} max={talk.MAX_WIDTH} h={h}")
        check(f"file written for {phrase[:16]!r}",
              os.path.getsize(p) > 100)


def test_live():
    print("\n6. real edge-tts boundaries (network)")
    mp3, words = talk.speak(SCRIPT, os.path.join(os.getcwd(), "_tts_test"))
    total = talk.duration_of(mp3)
    check("audio produced", total > 1.0, f"{total}s")
    check("word boundaries returned", len(words) >= 20, f"{len(words)} words")

    items = pipeline_timings(SCRIPT, words, total)
    assert_disjoint("no overlap (live)", items, total)
    shortest = min(e - s for s, e, t in items)
    check(f"no flash plate (shortest {shortest:.2f}s)", shortest > 0.35)
    print(f"         {len(items)} plates over {total:.1f}s")


def test_fit_offline():
    print("\n5. an over-long narration is cut at a sentence, not mid-word")
    # what the old code did: clamp the video length but not the audio
    spoken, limit = 99.7, talk.MAX_SECONDS
    check("the bug it guards needs >limit audio",
          spoken > limit,
          "fixture is not long enough to be a regression test")
    check("FIT leaves room for the pad",
          talk.FIT_SECONDS < talk.MAX_SECONDS
          and abs((talk.MAX_SECONDS - talk.FIT_SECONDS) - 0.6) < 1e-9,
          f"FIT={talk.FIT_SECONDS} MAX={talk.MAX_SECONDS}")
    # a single sentence has no safe cut point, so it must refuse rather
    # than silently chop the tail off
    try:
        talk._fit("Just one very long sentence without any stop in it",
                  "x", [(0, 0.1, "x")], 80.0, ".", None, None)
        check("one-sentence overrun raises", False, "returned instead")
    except talk.TalkError as e:
        check("one-sentence overrun raises", True)
        print("         ->", e)


def test_fit_live():
    print("\n7. 300-word narration shortened to fit (network)")
    sentence = ("A website is the only place on the internet that you own "
                "completely, and nobody can take it away from you overnight.")
    script = " ".join([sentence] * 14)
    import tempfile
    d = tempfile.mkdtemp(prefix="fit_")
    try:
        mp3, words = talk.speak(script, d)
        spoken = talk.duration_of(mp3)
        check("fixture is actually over the limit",
              spoken > talk.MAX_SECONDS, f"{spoken:.1f}s")
        _, _, _, fitted = talk._fit(script, mp3, words, spoken, d, None, None)
        check(f"fits ({spoken:.0f}s -> {fitted:.1f}s)",
              fitted <= talk.FIT_SECONDS)
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def _rows(phrase):
    """Rows a plate would draw - same numbers render_plate uses."""
    font = talk._load_font(talk.FONT_SIZE)
    text_max = max(1, talk.MAX_WIDTH - 2 * int(talk.FONT_SIZE * 0.4))
    return len(talk._wrap_lines(phrase, font, text_max))


def test_two_rows_max():
    print("\n4. no plate draws more than two rows")
    # _MAX_WORDS = 9 assumed word count stood in for width. This phrase
    # disproves it: eight words, three rows, burned into the second sample
    # before anything measured it. Prove the fixture really is broken when
    # left unsplit, then that it is not broken now.
    LONG = ("Search engines, ads and messages all point somewhere, and "
            "that somewhere has to belong to you.")

    naive = [" ".join(p) for p in talk._chunks(LONG.split(), talk._MAX_WORDS)]
    worst = max(_rows(p) for p in naive)
    check(f"unsplit, this phrase does draw {worst} rows",
          worst > talk._MAX_ROWS,
          "fixture no longer reproduces the bug")

    for label, text in (("fixture", SCRIPT), ("the three-row phrase", LONG)):
        phrases = talk._phrases(text)
        overs = [p for p in phrases if _rows(p) > talk._MAX_ROWS]
        check(f"{label}: {len(phrases)} plates, none past "
              f"{talk._MAX_ROWS} rows", not overs, str(overs[:1]))

    # the fix must not have earned its rows back as stubs - that is the
    # other way this went wrong once already
    sizes = [len(p.split()) for p in talk._phrases(LONG)]
    biggest, smallest = max(sizes), min(sizes)
    check(f"cut stays even ({sizes})",
          smallest >= max(3, biggest // 3) or len(sizes) == 1,
          f"stub of {smallest} vs {biggest}")


def test_speak_retry():
    """The voice has no second source, so a dropped stream must be retried.

    Images fall through Pinterest, Pexels and Pollinations; edge-tts is the
    only way a reel gets a voice at all. `import edge_tts` happens inside
    `speak`, so a stand-in module dropped into sys.modules is enough to
    exercise every branch without the network or a single request.
    """
    print("\nvoice transport: edge-tts retry")
    import shutil
    import tempfile
    import types

    saved = sys.modules.get("edge_tts")
    tmp = tempfile.mkdtemp(prefix="talk_speak_")
    state = {"calls": 0, "fail": 2, "empty": False}

    class FakeCommunicate:
        def __init__(self, text, voice, rate=None, boundary=None):
            self.text = text
            self.boundary = boundary

        async def stream(self):
            state["calls"] += 1
            if state["calls"] <= state["fail"]:
                raise ConnectionError("simulated drop")
            yield {"type": "audio", "data": b"\x00" * 4000}
            if not state["empty"]:
                yield {"type": "WordBoundary", "offset": 0,
                       "duration": 5_000_000, "text": "hello"}

    fake = types.ModuleType("edge_tts")
    fake.Communicate = FakeCommunicate
    sys.modules["edge_tts"] = fake
    old_delay = talk.RETRY_DELAY
    talk.RETRY_DELAY = 0
    try:
        state.update(calls=0, fail=2, empty=False)
        mp3, words = talk.speak("hello world", tmp, attempts=3)
        check("a stream that drops twice still yields audio",
              os.path.isfile(mp3) and os.path.getsize(mp3) >= 1000,
              f"{os.path.getsize(mp3) if os.path.exists(mp3) else 0} bytes")
        check("and the word timings with it", len(words) == 1, str(words))
        check("took exactly three attempts", state["calls"] == 3,
              f"{state['calls']}")

        state.update(calls=0, fail=99, empty=False)
        try:
            talk.speak("hello world", tmp, attempts=3)
            check("three failures raise", False, "no exception")
        except talk.TalkError as e:
            check("three failures raise", True)
            check("the message names how many attempts were made",
                  "3 attempts" in str(e), str(e))
        check("stopped at the attempts allowed", state["calls"] == 3,
              f"{state['calls']}")

        # Audio that arrives without boundaries is the shape of the reply,
        # not a hiccup - retrying would get the same thing back.
        state.update(calls=0, fail=0, empty=True)
        try:
            talk.speak("hello world", tmp, attempts=3)
            check("audio without word timings says so",
                  False, "no exception")
        except talk.TalkError as e:
            check("audio without word timings says so",
                  "word timings" in str(e), str(e))
        check("a protocol problem is not retried", state["calls"] == 1,
              f"{state['calls']} attempt(s)")

        state.update(calls=0, fail=0, empty=False)
        talk.speak("hello world", tmp, attempts=3)
        check("a healthy first attempt is left alone", state["calls"] == 1,
              f"{state['calls']}")
    finally:
        talk.RETRY_DELAY = old_delay
        if saved is None:
            sys.modules.pop("edge_tts", None)
        else:
            sys.modules["edge_tts"] = saved
        shutil.rmtree(tmp, ignore_errors=True)


def test_build_from_still():
    """A failed clip download must not cost the reel its voice.

    ffmpeg hands back exactly one frame for an image - measured above, 0.04s
    - so a still could not be used as footage, and the voice reel was only
    ever attempted `if clips`. When every clip download failed the account
    silently got the 20-second silent card instead of the approved format.
    Build one end to end from a generated still and a stand-in voice, then
    probe the streams: the picture has to last as long as the voice.
    """
    print("\nvoice reel built from a still (the clip-download fallback)")
    import shutil
    import subprocess
    import tempfile
    import types

    from config import FFMPEG, FFPROBE

    tmp = tempfile.mkdtemp(prefix="talk_still_")
    saved = sys.modules.get("edge_tts")
    old_delay = talk.RETRY_DELAY
    talk.RETRY_DELAY = 0
    try:
        still = os.path.join(tmp, "still.jpg")
        subprocess.run([FFMPEG, "-y", "-f", "lavfi",
                        "-i", "color=c=0x2b3a4a:s=1080x1920",
                        "-frames:v", "1", still],
                       capture_output=True, timeout=180)
        check("made a still to build from", os.path.isfile(still))

        # a real 3s tone to stand in for the synthesized voice, because
        # duration_of() and _clean_voice() both have to read it
        real = os.path.join(tmp, "tone.mp3")
        subprocess.run([FFMPEG, "-y", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=3",
                        "-c:a", "libmp3lame", "-q:a", "4", real],
                       capture_output=True, timeout=180)
        check("made a voice to fit it to", os.path.getsize(real) > 1000,
              f"{os.path.getsize(real) if os.path.exists(real) else 0} bytes")
        AUDIO = open(real, "rb").read()

        class FakeCommunicate:
            def __init__(self, text, voice, rate=None, boundary=None):
                self.text = text

            async def stream(self):
                yield {"type": "audio", "data": AUDIO}
                for i, w in enumerate(self.text.split()):
                    yield {"type": "WordBoundary",
                           "offset": int((0.15 + i * 0.30) * 1e7),
                           "duration": int(0.28 * 1e7), "text": w}

        fake = types.ModuleType("edge_tts")
        fake.Communicate = FakeCommunicate
        sys.modules["edge_tts"] = fake

        script = "Here is a short test of the voice reel."
        out = os.path.join(tmp, "reel.mp4")
        try:
            talk.build(script, [still], out, workdir=os.path.join(tmp, "w"),
                       hook="A test hook")
            check("built a reel from a single still", os.path.isfile(out),
                  "no output")
        except Exception as e:
            check("built a reel from a single still", False, str(e))
            return

        def streams(path):
            got = {}
            cur = None
            r = subprocess.run(
                [FFPROBE, "-v", "error",
                 "-show_entries", "stream=codec_type,duration",
                 "-of", "default=nw=1", path],
                capture_output=True, text=True, timeout=180)
            for line in r.stdout.splitlines():
                k, _, v = line.partition("=")
                if k == "codec_type":
                    cur = v
                    got.setdefault(v, {})
                elif cur:
                    got[cur][k] = float(v)
            return got

        got = streams(out)
        vdur = got.get("video", {}).get("duration") or 0.0
        adur = got.get("audio", {}).get("duration") or 0.0
        check("the picture lasts as long as the narration",
              vdur >= 3.5, f"video {vdur:.2f}s")
        check("it carries audio too", adur > 2.5, f"audio {adur:.2f}s")
        check("picture does not stop before the voice",
              abs(vdur - adur) <= 1.0,
              f"video {vdur:.2f}s vs voice {adur:.2f}s")
        check("not the 0.1s stub the old chain produced", vdur > 1.0,
              f"{vdur:.2f}s")
    finally:
        talk.RETRY_DELAY = old_delay
        if saved is None:
            sys.modules.pop("edge_tts", None)
        else:
            sys.modules["edge_tts"] = saved
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("talk.py subtitle tests  (voice=%s)" % talk.VOICE)
    test_overlap_offline()
    test_no_stubs()
    test_plate_geometry()
    test_two_rows_max()
    test_fit_offline()
    test_speak_retry()
    test_build_from_still()
    if "--live" in sys.argv:
        test_live()
        test_fit_live()

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
