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


def _plate_text(canvas, text, *, top, colour=WHITE, size=None, accent=None,
                maxw_frac=0.88, plate=150, align="center"):
    """Draw `text` centred on rounded translucent plates."""
    w, h = canvas.size
    d = ImageDraw.Draw(canvas)
    maxw = int(w * maxw_frac)
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))

    size = size or int(h * 0.062)
    while size >= 24:
        fnt = _font(size)
        lines = _wrap(probe, text, fnt, maxw - 48)
        lh = int(size * 1.16)
        if len(lines) * lh <= h * 0.42:
            break
        size -= 4

    fnt = _font(size)
    lines = _wrap(probe, text, fnt, maxw - 48)
    lh = int(size * 1.16)
    gap = 14
    block = len(lines) * lh + (len(lines) - 1) * gap
    y = top

    for i, ln in enumerate(lines):
        tw = probe.textlength(ln, font=fnt)
        if align == "center":
            x = (w - tw) // 2
        else:
            x = int(w * 0.06)
        d.rounded_rectangle(
            [x - 22, y - 10, x + tw + 22, y + lh - 12],
            radius=18, fill=(0, 0, 0, plate))
        d.text((x, y), ln, font=fnt, fill=colour)
        if accent and i == 0:
            d.text((x, y), ln, font=fnt, fill=accent)
        y += lh + gap
    return block


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
    top = int(H * 0.10)
    if text:
        _plate_text(canvas, text, top=top, colour=WHITE, plate=155)

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


def render_cover(image_path, out_path, overlay, *, hook=None, seed=0):
    """1080x1920 cover - used as the reel poster / first frame."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    base = Image.open(image_path).convert("RGB")
    canvas = _cover(base, 1080, 1920)
    canvas = _veil(canvas, frac=0.46, strength=150)
    text = (overlay or "").strip()
    if text:
        _plate_text(canvas, text, top=int(1920 * 0.11), colour=WHITE,
                    size=int(1920 * 0.050), plate=155)
    if hook and hook.strip() and hook.strip().lower() != text.lower():
        fnt = _font(52)
        d = ImageDraw.Draw(canvas)
        probe = ImageDraw.Draw(Image.new("L", (8, 8)))
        sub = hook.strip().upper()
        tw = probe.textlength(sub, font=fnt)
        d.rounded_rectangle(
            [(1080 - tw) // 2 - 24, 120, (1080 + tw) // 2 + 24, 196],
            radius=16, fill=(0, 0, 0, 145))
        d.text(((1080 - tw) // 2, 131), sub, font=fnt, fill=GOLD)
    canvas.save(out_path, "JPEG", quality=93, optimize=True)
    return out_path, text
