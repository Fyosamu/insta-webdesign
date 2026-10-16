# -*- coding: utf-8 -*-
"""Render Instagram FEED images (1080x1350, 4:5).

Style follows the pipeline the money conversation settled on: photo fully
visible (cover-cropped, never letterboxed), a soft dark veil at the top, and
the hook written over it in bold white/gold on a rounded translucent plate.
No glow, no neon, no fake light - the user explicitly asked for that.
"""
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config import font

W, H = 1080, 1350
GOLD = (232, 190, 84)
WHITE = (255, 255, 255)


def _font(size, bold=True):
    p = font(bold)
    if not p:
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(p, size)
    except Exception:
        return ImageFont.load_default()


def _wrap(draw, text, fnt, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=fnt) <= maxw:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def _cover(img, w, h):
    """Fill w x h keeping the aspect ratio; crop overflow, never letterbox."""
    src = img.convert("RGB")
    sw, sh = src.size
    s = max(w / sw, h / sh)
    nw, nh = max(1, int(sw * s)), max(1, int(sh * s))
    src = src.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return src.crop((left, top, left + w, top + h))


def _veil(img, frac=0.52, strength=145):
    """Soft dark wash from the top so text stays readable without a hard bar."""
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.rectangle([0, 0, w, int(h * frac)], fill=strength)
    mask = mask.filter(ImageFilter.GaussianBlur(int(h * 0.075)))
    out = img.convert("RGBA")
    out.alpha_composite(Image.merge("RGBA",
                                    [Image.new("L", (w, h), 0)] * 3 + [mask]))
    return out.convert("RGB")


def _bottom_fade(img, frac=0.34, strength=120):
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.rectangle([0, int(h * (1 - frac)), w, h], fill=strength)
    mask = mask.filter(ImageFilter.GaussianBlur(int(h * 0.06)))
    out = img.convert("RGBA")
    out.alpha_composite(Image.merge("RGBA",
                                    [Image.new("L", (w, h), 0)] * 3 + [mask]))
    return out.convert("RGB")


def _plate_text(canvas, text, *, band=None, top=None, colour=WHITE, size=None,
                accent=None, maxw_frac=0.88, plate=150, align="center"):
    """Draw `text` centred horizontally AND vertically inside `band`.

    `band` is a (top, bottom) region - the whole block is placed in its exact
    middle instead of flowing down from a fixed offset, so one line and four
    lines both land dead centre of the dark area. A single plate wraps the
    block rather than one plate per line, which is what the style guide asks
    for and what stops the text looking like a stack of stickers.
    """
    w, h = canvas.size
    d = ImageDraw.Draw(canvas)
    maxw = int(w * maxw_frac)
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))

    if band is None:
        y0 = int(top if top is not None else h * 0.10)
        band = (y0, y0 + int(h * 0.42))
    b0, b1 = band
    band_h = b1 - b0

    def metrics(sz):
        """wrap + real ink boxes, so centring uses drawn pixels not estimates"""
        fnt = _font(sz)
        lines = _wrap(probe, text, fnt, maxw - 56)
        gap = max(8, int(sz * 0.18))
        boxes = [probe.textbbox((0, 0), ln, font=fnt) for ln in lines]
        heights = [b[3] - b[1] for b in boxes]
        total = sum(heights) + gap * (len(lines) - 1)
        return fnt, lines, boxes, heights, gap, total

    # shrink until the block fits comfortably inside the band
    size = size or int(h * 0.062)
    while size >= 24:
        fnt, lines, boxes, heights, gap, total = metrics(size)
        if total <= band_h * 0.88:
            break
        size -= 4
    fnt, lines, boxes, heights, gap, total = metrics(size)

    # exact vertical centre of the band
    y = b0 + (band_h - total) / 2

    # one plate around the entire block
    pad_x, pad_y = 30, 24
    draws = []
    for ln, box in zip(lines, boxes):
        iw = box[2] - box[0]
        x = ((w - iw) / 2 - box[0]) if align == "center" else int(w * 0.06) - box[0]
        draws.append((ln, box, x))
    x0 = min(x + box[0] for _, box, x in draws)
    x1 = max(x + box[2] for _, box, x in draws)
    d.rounded_rectangle([x0 - pad_x, y - pad_y, x1 + pad_x, y + total + pad_y],
                        radius=24, fill=(0, 0, 0, plate))

    for i, (ln, box, x) in enumerate(draws):
        d.text((x, y - box[1]), ln, font=fnt, fill=colour)
        if accent and i == 0:
            d.text((x, y - box[1]), ln, font=fnt, fill=accent)
        y += heights[i] + gap
    return total


def render(image_path, out_path, overlay, *, mode="post", hook=None,
           badge=None, seed=0):
    """Build a 1080x1350 feed image. Returns (path, overlay_text)."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    rng = random.Random(seed or (sum(ord(c) for c in (overlay or ""))))

    base = Image.open(image_path).convert("RGB")
    canvas = _cover(base, W, H)
    canvas = _veil(canvas)
    canvas = _bottom_fade(canvas)

    text = (overlay or hook or "").strip()
    if text:
        # _veil() darkens 0..52%H, so its midpoint is 26%H. These bounds are
        # symmetric about that (0.10+0.42)/2 = 0.26, and 0.10H clears the hook
        # chip that sits at 0.045H..0.075H.
        _plate_text(canvas, text, band=(int(H * 0.10), int(H * 0.42)),
                    colour=WHITE, plate=155)

    if hook and hook.strip() and hook.strip().lower() != text.lower():
        fnt = _font(int(H * 0.030))
        d = ImageDraw.Draw(canvas)
        sub = hook.strip().upper()
        probe = ImageDraw.Draw(Image.new("L", (8, 8)))
        tw = probe.textlength(sub, font=fnt)
        d.rounded_rectangle(
            [(W - tw) // 2 - 20, int(H * 0.045) - 8,
             (W + tw) // 2 + 20, int(H * 0.045) + int(H * 0.030) + 6],
            radius=14, fill=(0, 0, 0, 140))
        d.text(((W - tw) // 2, int(H * 0.045)), sub, font=fnt, fill=GOLD)

    if badge:
        fnt = _font(int(H * 0.022))
        d = ImageDraw.Draw(canvas)
        probe = ImageDraw.Draw(Image.new("L", (8, 8)))
        tw = probe.textlength(badge, font=fnt)
        d.rounded_rectangle(
            [W - tw - 46, H - 92, W - 24, H - 44],
            radius=16, fill=(0, 0, 0, 130))
        d.text((W - tw - 35, H - 84), badge, font=fnt, fill=GOLD)

    canvas.save(out_path, "JPEG", quality=93, optimize=True)
    return out_path, text


def render_cover(image_path, out_path, overlay, *, hook=None, seed=0,
                 size=(1080, 1920)):
    """Cover / thumbnail at an arbitrary size.

    1080x1920 by default - the reel poster. The long and short thumbnails
    ask for 1280x720 and 720x1280 instead, so every vertical offset below
    is the 1920-pixel value expressed as a fraction of the actual height.
    """
    cw, ch = size
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    base = Image.open(image_path).convert("RGB")
    canvas = _cover(base, cw, ch)
    canvas = _veil(canvas, frac=0.46, strength=150)
    text = (overlay or "").strip()
    if text:
        # veil covers 0..46% of the height -> midpoint 23%; these bounds are
        # symmetric about it and the lower edge clears the hook chip below.
        _plate_text(canvas, text, band=(int(ch * 0.12), int(ch * 0.34)),
                    colour=WHITE, size=int(ch * 0.050), plate=155)
    if hook and hook.strip() and hook.strip().lower() != text.lower():
        fnt = _font(max(18, round(ch * 52 / 1920)))
        d = ImageDraw.Draw(canvas)
        probe = ImageDraw.Draw(Image.new("L", (8, 8)))
        sub = hook.strip().upper()
        tw = probe.textlength(sub, font=fnt)
        d.rounded_rectangle(
            [(cw - tw) // 2 - 24, round(ch * 120 / 1920),
             (cw + tw) // 2 + 24, round(ch * 196 / 1920)],
            radius=16, fill=(0, 0, 0, 145))
        d.text(((cw - tw) // 2, round(ch * 131 / 1920)), sub, font=fnt,
               fill=GOLD)
    canvas.save(out_path, "JPEG", quality=93, optimize=True)
    return out_path, text
