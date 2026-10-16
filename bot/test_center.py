# -*- coding: utf-8 -*-
"""Run the centring check across several copy lengths.

Short one-liners and long four-liners wrap differently, so a fix that only
centres one of them is not fixed. Each case renders on the flat canvas and
is measured against the veil midpoint.

    python test_center.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("DRY_RUN", "1")
os.environ.setdefault("APPROVED", "0")
os.environ.setdefault(
    "OUT_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "out"))

from PIL import Image  # noqa: E402

import render  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CASES = [
    "Sell products here",
    "Your website is open 24 hours, your shop is not",
    "A website is the only salesperson that never sleeps, never asks for a "
    "raise and never takes a single day off",
    "Every business needs a website because social media can ban you in one "
    "click and you own nothing there, not the page, not the audience, not "
    "the years you spent building it",
]


def ink(path):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    px = im.load()
    veil_bottom = int(h * 0.52)
    xs, ys = [], []
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if r > 235 and g > 235 and b > 235:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    return dict(w=w, h=h, veil=veil_bottom,
                dx=(x0 + x1) / 2 - w / 2,
                dy=(y0 + y1) / 2 - veil_bottom / 2,
                top=y0, bottom=veil_bottom - y1,
                left=x0, right=w - x1, rows=len(ys))


def measure_label(text):
    """A rough line count, so a failure says how many lines were involved."""
    return len(text) // 40 + 1


def main() -> int:
    flat = os.path.join(ROOT, "out", "_flat.jpg")
    out = os.path.join(ROOT, "out", "measure.jpg")
    Image.new("RGB", (render.W, render.H), (46, 46, 54)).save(
        flat, "JPEG", quality=95)

    tol = render.W * 0.03
    failed = 0
    print(f"{'lines':>5}  {'dx':>7} {'dy':>7}  {'top':>5} {'bot':>5} "
          f"{'left':>5} {'right':>5}  result")
    print("-" * 72)
    for text in CASES:
        render.render(flat, out, text, mode="post", hook="WEBSITE DESIGN",
                      badge="insta-webdesign", seed=7)
        m = ink(out)
        if not m:
            print(f"{measure_label(text):>5}  no text found")
            failed += 1
            continue
        ok = abs(m["dx"]) <= tol and abs(m["dy"]) <= tol
        if not ok:
            failed += 1
        print(f"{measure_label(text):>5}  {m['dx']:+7.1f} {m['dy']:+7.1f}  "
              f"{m['top']:5d} {m['bottom']:5d} {m['left']:5d} {m['right']:5d}  "
              f"{'PASS' if ok else 'FAIL'}")

    try:
        os.remove(flat)
    except OSError:
        pass

    print("-" * 72)
    print(f"{len(CASES) - failed}/{len(CASES)} centred (tol {tol:.0f}px)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
