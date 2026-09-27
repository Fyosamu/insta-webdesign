# -*- coding: utf-8 -*-
"""A talking reel: voice-over + subtitles drawn the way the other channels do it.

The subtitle geometry is a faithful port of MoneyPrinterTurbo's
`create_text_clip` / `_rounded_subtitle_background_clip`:

    max_width      = video_width * 0.9
    pad_x          = font_size * 0.4          (rounded background)
    interline      = font_size * 0.25
    vertical pad   = font_size * 0.35
    radius         = max(8, font_size * 0.4)
    box            = text width + 2*pad_x, never wider than max_width
    colours        = white text, black stroke, dark plate
    position       = bottom: y = height * 0.95 - plate height

The one deliberate change is plate alpha: MPT ships 140/255 (~55%), this
uses 178/255 (70%) so the words stay legible over bright stock footage
without going fully black.

Timing comes from edge-tts word boundaries, so the subtitle changes exactly
when the voice says the next word - no drift, no manual timing.
"""
import math
import os
import re
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

from config import FFMPEG, FFPROBE

# Voice picked after a 10-way audition (C:\Users\USER\Desktop\insta-voices).
# Sonia is en-GB, clear and well-articulated without being flat - it reads
# the second-language audience's words cleanly. REEL_VOICE overrides it.
VOICE = os.environ.get("REEL_VOICE", "en-GB-SoniaNeural")
# Measured on this script: +6% = 222 wpm, 0% = 205, -6% = 196. The audience
# is beginners reading a second language, so -6% buys comprehension without
# sounding slow. REEL_RATE overrides it per run.
RATE = os.environ.get("REEL_RATE", "-6%")

W, H = 1080, 1920
FPS = 30

# Instagram refuses a reel of a minute or more. The clamp below has to bite
# on the AUDIO, not only on the video length - see _fit().
MAX_SECONDS = 59.0
# headroom for the pad added after the voice, so a file that fits still
# fits once the pad is counted
FIT_SECONDS = MAX_SECONDS - 0.6

# --- subtitle look (MPT defaults, alpha raised as noted above) ------------
FONT_SIZE = int(os.environ.get("SUB_FONT_SIZE", "60"))
STROKE_W = 2
TEXT_RGB = (255, 255, 255)
STROKE_RGB = (0, 0, 0)
PLATE_RGB = (0, 0, 0)
PLATE_ALPHA = int(float(os.environ.get("SUB_BG_ALPHA", "0.70")) * 255)
MAX_WIDTH = int(W * 0.9)
PAD_X = int(FONT_SIZE * 0.4)
INTERLINE = int(FONT_SIZE * 0.25)
VERT_PAD = int(FONT_SIZE * 0.35)
RADIUS = max(8, int(FONT_SIZE * 0.4))

_CANDIDATE_FONTS = (
    # Windows
    [r"C:\Windows\Fonts\msyhbd.ttc",
     r"C:\Windows\Fonts\arialbd.ttf",
     r"C:\Windows\Fonts\segoeuib.ttf"]
    if os.name == "nt"
    # GitHub Actions runs Ubuntu: the workflow installs exactly these two
    # families, so the subtitles render the same there as they do locally.
    else ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
          "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
          "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"]
)


class TalkError(RuntimeError):
    pass


def _font_path():
    for p in _CANDIDATE_FONTS:
        if os.path.exists(p):
            return p
    raise TalkError("no subtitle font found (looked for msyhbd/arialbd/segoeuib)")


def _load_font(size=FONT_SIZE):
    return ImageFont.truetype(_font_path(), size)


def _run(cmd, timeout=900):
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                       encoding="utf-8", timeout=timeout)
    if p.returncode != 0:
        tail = (p.stderr or "")[-2000:]
        raise TalkError(f"ffmpeg failed:\n{tail}")
    return p


# --- voice ----------------------------------------------------------------
def speak(text, out_dir, voice=None, rate=None):
    """Synthesize `text` and return (mp3_path, [(start, dur, word), ...])."""
    import asyncio
    import edge_tts

    os.makedirs(out_dir, exist_ok=True)
    mp3 = os.path.join(out_dir, "voice.mp3")
    voice = voice or VOICE
    rate = rate or RATE

    async def go():
        # edge-tts defaults to SentenceBoundary now; the plate timing needs
        # per-word offsets or the subtitle changes late.
        comm = edge_tts.Communicate(text, voice, rate=rate,
                                    boundary="WordBoundary")
        words = []
        with open(mp3, "wb") as fh:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    fh.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    words.append((chunk["offset"] / 1e7,
                                  chunk["duration"] / 1e7,
                                  chunk["text"]))
        return words

    try:
        words = asyncio.run(go())
    except Exception as e:
        raise TalkError(f"edge-tts failed ({type(e).__name__}: {e})") from None
    if not os.path.exists(mp3) or os.path.getsize(mp3) < 1000:
        raise TalkError("edge-tts produced no audio")
    return mp3, words


def duration_of(path):
    if not FFPROBE:
        return 0.0
    p = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of",
         "csv=p=0", path],
        capture_output=True, text=True)
    try:
        return float((p.stdout or "0").strip().splitlines()[0])
    except (ValueError, IndexError):
        return 0.0


# --- timing ---------------------------------------------------------------
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_MAX_WORDS = 9          # a line this long already wraps to two rows


def _chunks(words, limit):
    """Split a sentence into pieces of *equal* length.

    `words[0:limit], words[limit:2*limit], ...` leaves a stub whenever the
    count is not a multiple of the limit - a 12-word sentence became 9 + 3,
    and that 3-word stub got a plate of its own for less than half a second.
    Splitting into `ceil(n / ceil(n/limit))`-sized pieces keeps them even.
    """
    n = len(words)
    if n <= limit:
        return [words]
    pieces = -(-n // limit)          # how many we need
    size = -(-n // pieces)           # words per piece, rounded up
    return [words[i:i + size] for i in range(0, n, size)]


def subtitle_items(text, words, total=None):
    """Group the word boundaries into phrases, the way 'sentence' mode does."""
    phrases = []
    for sent in _SENT_SPLIT.split(text.strip()):
        sent = sent.strip()
        if not sent:
            continue
        ws = sent.split()
        for piece in _chunks(ws, _MAX_WORDS):
            phrases.append(" ".join(piece))
    if not phrases:
        return []

    if not words:
        # no boundaries at all - spread the phrases evenly over the audio so
        # the reel still has subtitles instead of failing outright
        if not total:
            return []
        step = total / len(phrases)
        return [(i * step, min(total, (i + 1) * step + 0.2), p)
                for i, p in enumerate(phrases)]

    items, wi = [], 0
    for phrase in phrases:
        want = phrase.split()
        if wi >= len(words):
            break
        # the TTS text may differ in punctuation; match on the words themselves
        take = []
        for w in want:
            if wi >= len(words):
                break
            take.append(words[wi])
            wi += 1
        if not take:
            continue
        start = take[0][0]
        end = take[-1][0] + max(0.25, take[-1][1])
        items.append((start, end, phrase))
    if items:
        return items

    # last resort: one phrase per word boundary chunk
    step = 5
    for i in range(0, len(words), step):
        grp = words[i:i + step]
        items.append((grp[0][0], grp[-1][0] + grp[-1][1],
                      " ".join(g[2] for g in grp)))
    return items


# --- the plate ------------------------------------------------------------
def _wrap_lines(phrase, font, max_w):
    words, lines, cur = phrase.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if font.getbbox(trial)[2] <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def render_plate(out_png, phrase, font_size=FONT_SIZE):
    """One subtitle plate: white text with black outline on a rounded dark box."""
    font = _load_font(font_size)
    pad_x = int(font_size * 0.4)
    interline = int(font_size * 0.25)
    vert_pad = int(font_size * 0.35)
    radius = max(8, int(font_size * 0.4))
    text_max = max(1, MAX_WIDTH - 2 * pad_x)

    lines = _wrap_lines(phrase, font, text_max)

    # measure: bbox of every line, plus the outline bleed on each side
    widths = [font.getbbox(ln)[2] - font.getbbox(ln)[0] for ln in lines]
    heights = []
    for ln in lines:
        bb = font.getbbox(ln, stroke_width=STROKE_W)
        heights.append(bb[3] - bb[1])
    text_w = max(widths) if widths else 1
    text_h = sum(heights) + interline * max(0, len(lines) - 1)

    box_w = min(MAX_WIDTH, text_w + 2 * pad_x)
    stroke_pad = STROKE_W * 2
    box_h = text_h + 2 * vert_pad + stroke_pad

    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, max(0, box_w - 1), max(0, box_h - 1)],
                           radius=radius,
                           fill=(PLATE_RGB[0], PLATE_RGB[1], PLATE_RGB[2],
                                 PLATE_ALPHA))

    y = vert_pad + stroke_pad // 2
    for ln, hgt in zip(lines, heights):
        bb = font.getbbox(ln, stroke_width=STROKE_W)
        lw = bb[2] - bb[0]
        x = (box_w - lw) // 2 - bb[0]
        draw.text((x, y - bb[1]), ln, font=font, fill=TEXT_RGB,
                  stroke_width=STROKE_W, stroke_fill=STROKE_RGB)
        y += hgt + interline

    img.save(out_png)
    return img.size


def _plate_y(box_h):
    """Bottom placement, matching MPT's `height * 0.95 - plate height`."""
    return int(round(H * 0.95 - box_h))


def tighten(items, total, fps=FPS):
    """Make a list of subtitle timings safe to burn in.

    Never leave two plates enabled at the same instant: they are all
    anchored to the same bottom-centre point, so an overlap draws one line
    of text straight through the other. Each plate gets a little longer to
    close the gaps between phrases, but is cut off one frame before the
    next one starts - `between(t,s,e)` is inclusive at both ends, so
    matching them exactly would still light both up on the boundary frame.

    Extracted from build() so test_talk.py can assert the invariant
    directly instead of having to render a video to find out.
    """
    tight = []
    for i, (s, e, t) in enumerate(items):
        if s >= total:
            continue
        e = min(e + 0.15, total)
        if i + 1 < len(items):
            e = min(e, items[i + 1][0] - 1.0 / fps)
        if e > s:
            tight.append((s, e, t))
    return tight


# --- assembly -------------------------------------------------------------
def _prepare_source(sources, workdir, duration):
    """Chain the stock clips to a full-bleed 9:16 plate of `duration` seconds.

    One Pexels clip is typically 15-30s while the narration runs longer.
    Trimming a clip that is too short silently stops the picture there and
    the reel plays a frozen last few seconds while the voice keeps going -
    and because the container duration counts the audio, nothing looks
    wrong until you probe the streams. So the clips are replayed in order
    until the total clears the runtime; the cut lands under the dark veil
    with the plate over it, exactly like a normal stock edit.
    """
    if isinstance(sources, str):
        sources = [sources]
    sources = [s for s in sources if s and os.path.exists(s)]
    if not sources:
        raise TalkError("no footage to build from")

    # measure each clip once - the same file may be reused in the chain
    durs = {}
    for s in dict.fromkeys(sources):
        d = duration_of(s)
        durs[s] = d if d > 0 else 6.0

    chain, covered, i = [], 0.0, 0
    while covered < duration + 1.0 and i < len(sources) * 8:
        src = sources[i % len(sources)]
        chain.append(src)
        covered += durs[src]
        i += 1

    norm = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},fps={FPS},setsar=1,format=yuv420p,"
            f"setpts=PTS-STARTPTS")
    parts = [f"[{n}:v]{norm}[c{n}]" for n in range(len(chain))]
    joined = "".join(f"[c{n}]" for n in range(len(chain)))
    parts.append(f"{joined}concat=n={len(chain)}:v=1:a=0[cc]")
    parts.append(f"[cc]trim=0:{duration:.3f},setpts=PTS-STARTPTS,"
                 f"format=yuv420p[vout]")

    cmd = [FFMPEG, "-y"]
    for src in chain:
        cmd += ["-i", src]
    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]",
            "-t", f"{duration:.3f}", "-r", str(FPS),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-an", os.path.join(workdir, "bg.mp4")]
    _run(cmd, timeout=900)
    return os.path.join(workdir, "bg.mp4")


def _clean_voice(mp3, out_wav, duration):
    """Make the voice crisp: normalise the level, open the top end, trim."""
    _run([FFMPEG, "-y", "-i", mp3,
          "-af", ("loudnorm=I=-14:TP=-1.5:LRA=11,"
                  "treble=g=3.5:f=5000,"
                  "aresample=44100,"
                  f"atrim=0:{duration:.3f},apad=whole_dur={duration:.3f}"),
          "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", out_wav],
         timeout=300)
    return out_wav


def _fit(script, mp3, words, spoken, workdir, voice, rate):
    """Cut a narration back so the finished reel fits under a minute.

    Without this, a long script quietly produces a reel whose last seconds
    are chopped off mid-sentence: `total` is clamped to MAX_SECONDS while
    the audio is not, and the container duration counts the audio, so every
    other check reports a perfectly healthy file. Nothing looks wrong until
    somebody listens to the ending.

    The cut lands on a sentence boundary - a finished sentence is better
    than a shorter one with its tail missing - and the result is read
    again. edge-tts is free, so the re-read costs about a second.
    """
    if spoken <= FIT_SECONDS:
        return script, mp3, words, spoken

    sentences = [s for s in re.split(r"(?<=[.!?])\s+", script) if s.strip()]
    if len(sentences) < 2:
        raise TalkError(
            f"narration runs {spoken:.0f}s, over the {MAX_SECONDS:.0f}s "
            "limit, and has no sentence boundary to cut at")

    for _ in range(len(sentences)):
        # measured rate, so the estimate tracks this voice at this speed
        per_word = spoken / max(len(words), 1)
        kept = [sentences[0]]
        for s in sentences[1:]:
            candidate = " ".join(kept + [s])
            if len(candidate.split()) * per_word > FIT_SECONDS:
                break
            kept.append(s)
        trimmed = " ".join(kept)
        if trimmed == script:
            break
        print(f"   narration {spoken:.0f}s > {MAX_SECONDS:.0f}s: cutting to "
              f"{len(trimmed.split())} words at a sentence end", flush=True)
        script, mp3, words = trimmed, *speak(trimmed, workdir,
                                              voice=voice, rate=rate)
        spoken = duration_of(mp3)
        if spoken <= 0:
            raise TalkError("could not read the trimmed voice duration")
        if spoken <= FIT_SECONDS:
            return script, mp3, words, spoken

    raise TalkError(
        f"narration is {spoken:.0f}s, over the {MAX_SECONDS:.0f}s "
        "Instagram limit even after cutting back to full sentences")


def build(script, source, out_path, *, workdir, hook=None, voice=None,
          rate=None, duration=None, keep_notes=False):
    """Render a talking reel: stock footage + voice-over + synced subtitles.

    `script` is the sentence that gets spoken (plain English). Returns the
    output path, the subtitle items that were burned in, the total length,
    and the script as it was actually narrated - _fit() may have cut it
    back to fit under a minute, and a report of what shipped has to match
    what shipped.
    """
    os.makedirs(workdir, exist_ok=True)
    script = " ".join(str(script).split())
    if not script:
        raise TalkError("empty script")

    mp3, words = speak(script, workdir, voice=voice, rate=rate)
    spoken = duration_of(mp3)
    if spoken <= 0:
        raise TalkError("could not read the voice duration")

    # a reel that overruns gets cut off mid-word below, so fit it first
    script, mp3, words, spoken = _fit(script, mp3, words, spoken,
                                       workdir, voice, rate)

    total = duration or spoken
    # tiny pad so the last word is never clipped, but never over the limit
    total = min(max(total + 0.6, 4.0), MAX_SECONDS)

    items = subtitle_items(script, words, total)
    if not items:
        raise TalkError("no subtitle timings from the voice")
    items = tighten(items, total)
    if not items:
        raise TalkError("subtitle timings collapsed to nothing")

    bg = _prepare_source(source, workdir, total)

    inputs = ["-i", bg]
    filters = []
    labels = ["[0:v]"]

    # hook: first ~2.8s, up top so it never fights the subtitle plate
    hook_png = None
    if hook:
        hook_png = os.path.join(workdir, "hook.png")
        hw, hh = _render_hook(hook_png, hook)
        inputs += ["-i", hook_png]
        idx = inputs.count("-i") - 1
        end = min(2.8, total * 0.45)
        filters.append(
            f"{labels[-1]}[{idx}:v]overlay=x=(W-w)/2:y=H*0.24:"
            f"enable='lt(t,{end:.2f})'[vh]")
        labels.append("[vh]")

    boxes = []
    for n, (start, end, phrase) in enumerate(items):
        png = os.path.join(workdir, f"sub{n:03d}.png")
        size = render_plate(png, phrase)
        boxes.append(size)
        inputs += ["-i", png]
        idx = inputs.count("-i") - 1
        y = _plate_y(size[1])
        filters.append(
            f"{labels[-1]}[{idx}:v]overlay=x=(W-w)/2:y={y}:"
            f"enable='between(t,{start:.2f},{end:.2f})'[v{n}]")
        labels.append(f"[v{n}]")

    filters.append(f"{labels[-1]}format=yuv420p[vout]")

    wav = _clean_voice(mp3, os.path.join(workdir, "voice.wav"), total)
    inputs += ["-i", wav]
    aidx = inputs.count("-i") - 1

    cmd = [FFMPEG, "-y"] + inputs
    cmd += ["-filter_complex", ";".join(filters),
            "-map", "[vout]", "-map", f"{aidx}:a",
            "-t", f"{total:.3f}", "-r", str(FPS),
            "-c:v", "libx264", "-preset", "medium", "-crf", "19",
            "-c:a", "aac", "-b:a", "192k",
            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
            "-movflags", "+faststart", out_path]
    _run(cmd, timeout=900)
    return out_path, items, total, script


def _render_hook(out_png, text):
    """The opening line: big, bold, top of frame, gone after a couple of
    seconds so it never competes with the subtitle plate."""
    font = _load_font(76)
    lines = _wrap_lines(text, font, int(W * 0.84))
    widths = [font.getbbox(l, stroke_width=3)[2] -
              font.getbbox(l, stroke_width=3)[0] for l in lines]
    heights = [font.getbbox(l, stroke_width=3)[3] -
               font.getbbox(l, stroke_width=3)[1] for l in lines]
    tw = max(widths)
    th = sum(heights) + 18 * (len(lines) - 1)
    pad = 46
    img = Image.new("RGBA", (tw + 2 * pad, th + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=28,
                        fill=(0, 0, 0, 150))
    y = pad
    for l, h in zip(lines, heights):
        bb = font.getbbox(l, stroke_width=3)
        x = (img.width - (bb[2] - bb[0])) // 2 - bb[0]
        d.text((x, y - bb[1]), l, font=font, fill=(255, 224, 60),
               stroke_width=3, stroke_fill=(0, 0, 0))
        y += h + 18
    img.save(out_png)
    return img.size


def video_duration(path):
    """Duration of the *video* stream only.

    `duration_of` reads the container, which counts the audio as well - so a
    picture that stops ten seconds early still looks fine there. This is the
    number that has to cover the voice-over.
    """
    if not FFPROBE:
        return 0.0
    p = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True)
    for line in (p.stdout or "").strip().splitlines():
        line = line.strip().rstrip(",")
        try:
            return float(line)
        except ValueError:
            continue
    return 0.0


def probe(path):
    """(width, height, duration, has_audio) - a cheap sanity check."""
    if not FFPROBE:
        return None
    p = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries",
         "stream=width,height,codec_type:format=duration",
         "-of", "json", path], capture_output=True, text=True)
    import json
    try:
        data = json.loads(p.stdout or "{}")
    except ValueError:
        return None
    w = h = 0
    has_audio = False
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            w, h = s.get("width", 0), s.get("height", 0)
        elif s.get("codec_type") == "audio":
            has_audio = True
    try:
        dur = float(data.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        dur = 0.0
    return w, h, dur, has_audio

