# -*- coding: utf-8 -*-
"""Centring check for the reel cover (1080x1920).

The feed post and the cover use different bands and different veil heights,
so they have to be verified separately.

    python test_center_cover.py
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
    "click and you own nothing there",
]


def main() -> int:
    flat = os.path.join(ROOT, "out", "_flat.jpg")
    out = os.path.join(ROOT, "out", "_cover.jpg")
    Image.new("RGB", (1080, 1920), (46, 46, 54)).save(flat, "JPEG", quality=95)

    tol = 1080 * 0.03
    failed = 0
    print(f"{'dx':>7} {'dy':>7}  {'top':>5} {'bot':>5} {'left':>5} "
          f"{'right':>5}  result")
    print("-" * 60)
    for text in CASES:
        render.render_cover(flat, out, text, hook="WEBSITE DESIGN", seed=7)
        im = Image.open(out).convert("RGB")
        w, h = im.size
        px = im.load()
        veil = int(h * 0.46)          # render_cover uses frac=0.46
        xs, ys = [], []
        for y in range(h):
            for x in range(w):
                r, g, b = px[x, y]
                if r > 235 and g > 235 and b > 235:
                    xs.append(x)
                    ys.append(y)
        if not xs:
            print("  no text found")
            failed += 1
            continue
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        dx, dy = (x0 + x1) / 2 - w / 2, (y0 + y1) / 2 - veil / 2
        ok = abs(dx) <= tol and abs(dy) <= tol
        failed += 0 if ok else 1
        print(f"{dx:+7.1f} {dy:+7.1f}  {y0:5d} {veil - y1:5d} {x0:5d} "
              f"{w - x1:5d}  {'PASS' if ok else 'FAIL'}")

    for junk in (flat, out):
        try:
            os.remove(junk)
        except OSError:
            pass

    print("-" * 60)
    print(f"{len(CASES) - failed}/{len(CASES)} cover centred (tol {tol:.0f}px)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
