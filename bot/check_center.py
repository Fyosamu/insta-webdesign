# -*- coding: utf-8 -*-
"""Prove the overlay text is centred, and render a real preview.

Two renders are produced:

1. `measure.jpg` - the same layout on a flat dark canvas. Without a photo
   behind it, every white pixel belongs to the text, so the reported centre
   is exact rather than a guess contaminated by clouds or highlights.
2. `preview.jpg` - the actual post, on a real photo, for eyeballing.

    python check_center.py
    python check_center.py path\\to.jpg "SOME HOOK"
"""
import glob
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

TEXT = " ".join(sys.argv[2:]).strip() if len(sys.argv) > 2 else (
    "Your website is open 24 hours. Your shop is not.")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_source() -> str:
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        return sys.argv[1]
    hits = sorted(glob.glob(os.path.join(ROOT, "out", "posts", "*", "*_src.jpg")))
    if not hits:
        raise SystemExit("no source image found")
    return hits[-1]


def flat(size, colour=(46, 46, 54)) -> str:
    """A featureless dark source: the only white pixels will be the text."""
    path = os.path.join(ROOT, "out", "_flat.jpg")
    Image.new("RGB", size, colour).save(path, "JPEG", quality=95)
    return path


def measure(path: str) -> bool:
    """Locate the white glyph pixels and compare with the veil midpoint."""
    im = Image.open(path).convert("RGB")
    w, h = im.size
    px = im.load()

    veil_bottom = int(h * 0.52)      # _veil() darkens the top 52%
    veil_mid = veil_bottom / 2

    xs, ys = [], []
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if r > 235 and g > 235 and b > 235:
                xs.append(x)
                ys.append(y)

    if not xs:
        print("NO WHITE TEXT FOUND")
        return False

    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    dx, dy = (x0 + x1) / 2 - w / 2, (y0 + y1) / 2 - veil_mid

    print(f"  canvas       {w}x{h}")
    print(f"  dark band    0..{veil_bottom}   mid={veil_mid:.1f}")
    print(f"  text ink     x=[{x0},{x1}]  y=[{y0},{y1}]")
    print(f"  centre       dx={dx:+.1f}px   dy={dy:+.1f}px")
    print(f"  margins      top={y0}  bottom={veil_bottom - y1}  "
          f"delta={(y0) - (veil_bottom - y1):+d}px")
    print(f"  side margins left={x0}  right={w - x1}  "
          f"delta={x0 - (w - x1):+d}px")

    tol = w * 0.03
    ok_x, ok_y = abs(dx) <= tol, abs(dy) <= tol
    print(f"  horizontal   {'PASS' if ok_x else 'FAIL'} (tol {tol:.0f}px)")
    print(f"  vertical     {'PASS' if ok_y else 'FAIL'} (tol {tol:.0f}px)")
    return ok_x and ok_y


def main() -> int:
    src = find_source()

    probe = flat((render.W, render.H))
    m_path = os.path.join(ROOT, "out", "measure.jpg")
    render.render(probe, m_path, TEXT, mode="post", hook="WEBSITE DESIGN",
                  badge="insta-webdesign", seed=7)
    print("layout check (flat canvas, no photo to confuse the measurement)")
    ok = measure(m_path)

    p_path = os.path.join(ROOT, "out", "preview.jpg")
    render.render(src, p_path, TEXT, mode="post", hook="WEBSITE DESIGN",
                  badge="insta-webdesign", seed=7)
    print(f"\npreview rendered from {os.path.relpath(src)}")

    c_path = os.path.join(ROOT, "out", "preview_cover.jpg")
    render.render_cover(src, c_path, TEXT, hook="WEBSITE DESIGN", seed=7)
    print(f"cover preview rendered from {os.path.relpath(src)}")

    for junk in (probe,):
        try:
            os.remove(junk)
        except OSError:
            pass

    print(f"\nmeasure -> {m_path}\npreview -> {p_path}\ncover    -> {c_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
