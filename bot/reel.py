# -*- coding: utf-8 -*-
"""Build Instagram REELS: 1080x1920, 9:16, ~20s.

A reel is a stock clip from Pexels (or a still image with a slow Ken Burns
push), a dark veil, the hook burned in on frame 1, and burned-in captions
from the generated script.

Everything is rendered by ffmpeg so the runner only needs ffmpeg + Pillow.
"""
import os
import shlex
import subprocess
import textwrap

from config import FFMPEG, probe_has_audio, require_ffmpeg

W, H = 1080, 1920
GOLD = "#e8be54"

# ffmpeg drawtext needs the font as a file path; config.font() gives us one.
from config import font as _font_path


def _fontfile():
    p = _font_path(True)
    if not p:
        raise SystemExit("no usable font found for drawtext")
    return p


def _esc(s):
    """Escape a string for ffmpeg drawtext."""
    s = s.replace("\\", "\\\\").replace("'", "\\'")
    s = s.replace(":", "\\:").replace("%", "\\%").replace(",", "\\,")
    return s


def _run(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-1800:]
        raise RuntimeError("ffmpeg failed:\n" + tail)
    return proc


# ------------------------------------------------------------------ veil ----
def _veil_png(path, opacity=0.45):
    """Top-to-bottom dark gradient used as an overlay so text stays legible."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y in range(H):
        # strong at the very top, gone by 60%, faint again at the bottom
        if y < H * 0.55:
            a = int(255 * opacity * (1 - y / (H * 0.55)) ** 1.4)
        elif y > H * 0.72:
            a = int(255 * 0.42 * ((y - H * 0.72) / (H * 0.28)) ** 1.2)
        else:
            a = 0
        d.line([(0, y), (W, y)], fill=(0, 0, 0, a))
    img.save(path)
    return path


def _caption_card(path, text, size=64, plate=True):
    """A transparent PNG holding wrapped caption text with a soft plate."""
    from PIL import Image, ImageDraw, ImageFont
    fnt_path = _font_path(True)
    fnt = ImageFont.truetype(fnt_path, size)
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    maxw = int(W * 0.84)
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if probe.textlength(trial, font=fnt) <= maxw:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    lines = lines[:4]
    if not lines:
        lines = [""]

    lh = int(size * 1.22)
    gap = 12
    block_h = len(lines) * lh + (len(lines) - 1) * gap
    pad = 34
    img = Image.new("RGBA", (W, block_h + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    widest = max(probe.textlength(l, font=fnt) for l in lines)
    if plate:
        d.rounded_rectangle(
            [int((W - widest) / 2) - pad, 8,
             int((W + widest) / 2) + pad, block_h + pad * 2 - 8],
            radius=26, fill=(0, 0, 0, 150))
    y = pad - 4
    for l in lines:
        tw = probe.textlength(l, font=fnt)
        d.text(((W - tw) / 2, y), l, font=fnt, fill=(255, 255, 255, 255))
        y += lh + gap
    img.save(path)
    return path, block_h + pad * 2


def _hook_card(path, text, size=78):
    from PIL import Image, ImageDraw, ImageFont
    fnt_path = _font_path(True)
    fnt = ImageFont.truetype(fnt_path, size)
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    maxw = int(W * 0.86)
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if probe.textlength(trial, font=fnt) <= maxw:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    lines = lines[:3]
    lh = int(size * 1.18)
    gap = 10
    block_h = len(lines) * lh + (len(lines) - 1) * gap
    pad = 30
    img = Image.new("RGBA", (W, block_h + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    widest = max(probe.textlength(l, font=fnt) for l in lines)
    d.rounded_rectangle(
        [int((W - widest) / 2) - pad, 6,
         int((W + widest) / 2) + pad, block_h + pad * 2 - 6],
        radius=24, fill=(0, 0, 0, 160))
    y = pad - 6
    for l in lines:
        tw = probe.textlength(l, font=fnt)
        # gold outline + white fill reads better than a glow
        d.text(((W - tw) / 2, y), l, font=fnt, fill=GOLD, stroke_width=2,
               stroke_fill=(0, 0, 0, 220))
        d.text(((W - tw) / 2, y), l, font=fnt, fill=(255, 255, 255, 255))
        y += lh + gap
    img.save(path)
    return path, block_h + pad * 2


# ------------------------------------------------------------------ build ---
def build(source, out_path, *, hook, lines, workdir, duration=20,
          still=False, seed=0):
    """Render a reel. `source` is an mp4 (stock) or an image path."""
    require_ffmpeg()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    os.makedirs(workdir, exist_ok=True)

    veil = _veil_png(os.path.join(workdir, "veil.png"), opacity=0.5)
    hook_png, hook_h = _hook_card(os.path.join(workdir, "hook.png"), hook or " ")

    duration = max(8, min(60, int(duration)))
    fps = 30
    seg = duration / max(1, len(lines)) if lines else duration

    # Input order is fixed and known up front, so the filter graph can name
    # every stream by index without guessing:
    #   0 = video source   1 = veil   2 = hook   3.. = captions   last = audio
    has_audio = (not still) and probe_has_audio(source)
    inputs, filters, maps = [], [], []

    if still:
        # slow push-in on a still image keeps it from feeling static
        inputs += ["-loop", "1", "-t", str(duration), "-i", source]
        filters.append(
            f"[0:v]scale={W * 1.12}:{H * 1.12}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},zoompan=z='min(zoom+0.0009,1.18)':d={duration * fps}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={fps},"
            f"trim=0:{duration},setpts=PTS-STARTPTS,setsar=1[vbase]")
    else:
        inputs += ["-i", source]
        filters.append(
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},fps={fps},setsar=1,"
            f"trim=0:{duration},setpts=PTS-STARTPTS[vbase]")
    vlabel = "[vbase]"

    # veil - inputs are appended in a known order: [source, veil, hook, ...]
    inputs += ["-i", veil]
    filters.append(f"{vlabel}[1:v]overlay=0:0[v2]")
    vlabel = "[v2]"

    # hook, visible for the first ~3.2s
    inputs += ["-i", hook_png]
    hook_end = min(3.2, duration * 0.35)
    filters.append(
        f"{vlabel}[2:v]overlay=x=(W-w)/2:y=H*0.11:enable='lt(t,{hook_end})'[v3]")
    vlabel = "[v3]"

    # captions, one card per script line
    for i, line in enumerate(lines or []):
        if not str(line).strip():
            continue
        card, ch = _caption_card(os.path.join(workdir, f"cap{i}.png"), str(line))
        start = i * seg
        end = min(duration, (i + 1) * seg + 0.35)
        if start >= duration:
            break
        inputs += ["-i", card]
        # each input costs two list entries ("-i", path), so count the flags
        idx = inputs.count("-i") - 1
        filters.append(
            f"{vlabel}[{idx}:v]overlay=x=(W-w)/2:y=H*0.70:"
            f"enable='between(t,{start:.2f},{end:.2f})'[v{i + 4}]")
        vlabel = f"[v{i + 4}]"

    filters.append(f"{vlabel}format=yuv420p[vout]")

    # Audio: keep the source bed (quiet) when there is one, otherwise emit a
    # silent stereo track so players and the upload API see a real stream.
    if has_audio:
        filters.append(
            f"[0:a]atrim=0:{duration},asetpts=PTS-STARTPTS,"
            f"aformat=sample_rates=44100:channel_layouts=stereo,"
            f"volume=0.22[aout]")
    else:
        filters.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{duration}[aout]")

    cmd = [FFMPEG, "-y"] + inputs
    cmd += ["-filter_complex", ";".join(filters),
            "-map", "[vout]", "-map", "[aout]",
            "-t", str(duration), "-r", str(fps),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            out_path]
    _run(cmd)
    return out_path
