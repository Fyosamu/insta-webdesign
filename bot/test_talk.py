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
    print("\n4. real edge-tts boundaries (network)")
    mp3, words = talk.speak(SCRIPT, os.path.join(os.getcwd(), "_tts_test"))
    total = talk.duration_of(mp3)
    check("audio produced", total > 1.0, f"{total}s")
    check("word boundaries returned", len(words) >= 20, f"{len(words)} words")

    items = pipeline_timings(SCRIPT, words, total)
    assert_disjoint("no overlap (live)", items, total)
    shortest = min(e - s for s, e, t in items)
    check(f"no flash plate (shortest {shortest:.2f}s)", shortest > 0.35)
    print(f"         {len(items)} plates over {total:.1f}s")


def main():
    print("talk.py subtitle tests  (voice=%s)" % talk.VOICE)
    test_overlap_offline()
    test_no_stubs()
    test_plate_geometry()
    if "--live" in sys.argv:
        test_live()

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
