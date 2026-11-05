"""Renders a Money Decoded reel (1080x1920, 30fps) from a script + voice timings.

Pure Pillow + FFmpeg, so it runs free on any machine or GitHub Actions runner.
Layout keeps all text inside the Reels safe zone (clear of the top bar, the
right-hand buttons and the bottom caption area).
"""
import glob
import math
import os
import random
import re
import subprocess

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "..", "fonts")
MUSIC_DIR = os.path.join(HERE, "..", "assets", "music")

# Brand palette (matches the existing Money Decoded reels)
NAVY = (8, 16, 34)
NAVY2 = (14, 33, 66)
CARD = (19, 38, 74)
CARD_EDGE = (40, 66, 112)
WHITE = (245, 247, 252)
MUTED = (160, 176, 205)
GOLD = (247, 197, 72)
TEAL = (46, 211, 160)
BLUE = (64, 150, 255)
BAR_COLORS = [TEAL, GOLD, BLUE, (236, 110, 140)]

SAFE_X = 90                 # left/right margin
CONTENT_TOP, CONTENT_BOT = 330, 1330
CAPTION_Y = 1440
Y_SHIFT = 140              # moves scene content down toward the visual centre


def font(weight, size):
    return ImageFont.truetype(os.path.join(FONTS, f"Poppins-{weight}.ttf"), int(size))


_font_cache = {}


def F(weight, size):
    key = (weight, int(size))
    if key not in _font_cache:
        _font_cache[key] = font(weight, size)
    return _font_cache[key]


# ---------- easing ----------
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def back_out(x):
    x = clamp(x)
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


# ---------- text helpers ----------
def text_w(t, f):
    return f.getbbox(t)[2] - f.getbbox(t)[0] if t else 0


def fit_font(text, weight, size, max_w, min_size=40):
    while size > min_size and text_w(text, F(weight, size)) > max_w:
        size -= 4
    return F(weight, size)


def wrap(text, f, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if text_w(trial, f) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def draw_center(d, text, f, cy, fill, alpha=255, x_center=W // 2):
    d.text((x_center, cy), text, font=f, anchor="mm", fill=fill + (int(alpha),))


def rrect(d, box, r, fill, outline=None, width=0, alpha=255):
    fill = fill + (int(alpha),) if fill else None
    outline = outline + (int(alpha),) if outline else None
    d.rounded_rectangle(box, r, fill=fill, outline=outline, width=width)


# ---------- background ----------
def make_background():
    bg = Image.new("RGB", (W, H), NAVY)
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((-300, -200, W + 300, 1100), fill=(24, 58, 110))
    g.ellipse((400, 1200, 1500, 2300), fill=(10, 60, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(220))
    bg = Image.blend(bg, glow, 0.55)
    # faint grid for the "decoded" feel
    d = ImageDraw.Draw(bg)
    for x in range(0, W, 90):
        d.line([(x, 0), (x, H)], fill=(18, 32, 60), width=1)
    for y in range(0, H, 90):
        d.line([(0, y), (W, y)], fill=(18, 32, 60), width=1)
    # vignette
    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).ellipse((-250, -150, W + 250, H + 150), fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(200))
    dark = Image.new("RGB", (W, H), (3, 6, 14))
    return Image.composite(bg, dark, vig).convert("RGBA")


def draw_brand(d, progress):
    f = F("Bold", 34)
    x, y = SAFE_X, 200
    parts = [("{ ", GOLD), ("MONEY ", WHITE), ("DECODED", TEAL), (" }", GOLD)]
    for t, c in parts:
        d.text((x, y), t, font=f, fill=c + (255,))
        x += text_w(t, f) + (8 if t.endswith(" ") else 0)
    # progress bar (keeps people watching to the end)
    rrect(d, (SAFE_X, 262, W - SAFE_X, 270), 4, (30, 48, 84))
    rrect(d, (SAFE_X, 262, SAFE_X + max(8, (W - 2 * SAFE_X) * progress), 270), 4, GOLD)


# ---------- number count-up ----------
NUM_RE = re.compile(r"[\d,]+(\.\d+)?")


def count_up(value, p):
    m = NUM_RE.search(value)
    if not m or p >= 1:
        return value
    raw = m.group(0)
    try:
        target = float(raw.replace(",", ""))
    except ValueError:
        return value
    cur = target * ease_out(p)
    decimals = len(m.group(1)) - 1 if m.group(1) else 0
    s = f"{cur:,.{decimals}f}" if "," in raw else f"{cur:.{decimals}f}"
    return value[:m.start()] + s + value[m.end():]


# ---------- scene painters ----------
# Each painter draws onto d for local time t (seconds into scene), scene length L.
def enter(t, delay, dur=0.35):
    """returns (alpha 0-255, y offset px)"""
    p = ease_out((t - delay) / dur)
    return 255 * p, 70 * (1 - p)


def paint_hook(d, v, t, L):
    lines = [(v.get("line1", ""), WHITE), (v.get("line2", ""), WHITE), (v.get("accent", ""), GOLD)]
    lines = [(s.upper(), c) for s, c in lines if s]
    y = 700 - (len(lines) - 1) * 80
    for i, (s, c) in enumerate(lines):
        a, off = enter(t, 0.08 * i, 0.3)
        f = fit_font(s, "Bold", 132, W - 2 * SAFE_X - 40)
        if c == GOLD:  # punchline pops
            sc = back_out((t - 0.08 * i) / 0.4)
            f = fit_font(s, "Bold", max(40, 132 * (0.7 + 0.3 * sc)), W - 2 * SAFE_X - 40)
        draw_center(d, s, f, y + off, c, a)
        y += 165


def paint_big_number(d, v, t, L):
    a, off = enter(t, 0)
    draw_center(d, v.get("label", "").upper(), fit_font(v.get("label", "").upper(), "Bold", 52, 900),
                560 + off, MUTED, a)
    val = count_up(v.get("value", ""), (t - 0.1) / 0.9)
    final = v.get("value", "")
    f = fit_font(final, "Bold", 230, W - 2 * SAFE_X)
    a2, off2 = enter(t, 0.1)
    float_y = 6 * math.sin(t * 2.2)
    draw_center(d, val, f, 760 + off2 + float_y, GOLD, a2)
    sub = v.get("sub", "")
    if sub:
        a3, off3 = enter(t, 0.45)
        for i, line in enumerate(wrap(sub, F("Medium", 54), 880)[:2]):
            draw_center(d, line, F("Medium", 54), 950 + i * 70 + off3, WHITE, a3)


def paint_list(d, v, t, L):
    title = v.get("title", "").upper()
    a, off = enter(t, 0)
    draw_center(d, title, fit_font(title, "Bold", 78, 900), 470 + off, GOLD, a)
    items = v.get("items", [])[:4]
    span = max(0.6, L * 0.65)
    for i, item in enumerate(items):
        delay = 0.2 + span * i / max(1, len(items))
        a, off = enter(t, delay)
        if a <= 0:
            continue
        top = 590 + i * 170
        x = SAFE_X + off * 0.0
        rrect(d, (x, top + off, W - SAFE_X, top + 140 + off), 34, CARD, CARD_EDGE, 3, a * 0.95)
        cx, cy = x + 72, top + 70 + off
        d.ellipse((cx - 34, cy - 34, cx + 34, cy + 34), fill=GOLD + (int(a),))
        draw_center(d, str(i + 1), F("Bold", 40), cy, NAVY, a, x_center=cx)
        f = fit_font(item, "Bold", 54, W - 2 * SAFE_X - 170)
        d.text((x + 130, cy), item, font=f, anchor="lm", fill=WHITE + (int(a),))


def paint_compare(d, v, t, L):
    cards = [(v.get("left_title", ""), v.get("left", "")), (v.get("right_title", ""), v.get("right", ""))]
    win = 0 if v.get("winner") == "left" else 1 if v.get("winner") == "right" else None
    gap, cw = 60, (W - 2 * SAFE_X - 60) // 2
    top, bot = 540, 1080
    for i, (ttl, val) in enumerate(cards):
        a, off = enter(t, 0.15 * i)
        x0 = SAFE_X + i * (cw + gap)
        cxm = x0 + cw // 2
        show_win = win == i and t > L * 0.45
        edge = GOLD if show_win else CARD_EDGE
        rrect(d, (x0, top + off, x0 + cw, bot + off), 40, CARD, edge, 6 if show_win else 3, a)
        tl = wrap(ttl.upper(), F("Bold", 38), cw - 60)[:2]
        for j, line in enumerate(tl):
            draw_center(d, line, F("Bold", 38), top + 80 + j * 50 + off, MUTED, a, x_center=cxm)
        size = 84
        while size > 44:
            vl = wrap(val, F("Bold", size), cw - 60)
            if len(vl) <= 2 and all(text_w(x, F("Bold", size)) <= cw - 60 for x in vl):
                break
            size -= 4
        fv = F("Bold", size)
        vl = wrap(val, fv, cw - 60)[:3]
        for j, line in enumerate(vl):
            draw_center(d, line, fv, 830 + (j - (len(vl) - 1) / 2) * size * 1.15 + off,
                        GOLD if show_win else WHITE, a, x_center=cxm)
        if show_win:
            pa = 255 * ease_out((t - L * 0.45) / 0.25)
            rrect(d, (cxm - 120, bot - 30 + off, cxm + 120, bot + 30 + off), 30, GOLD, alpha=pa)
            draw_center(d, "WINNER", F("Bold", 32), bot + off, NAVY, pa, x_center=cxm)
    a, _ = enter(t, 0.3)
    d.ellipse((W / 2 - 48, 782, W / 2 + 48, 878), fill=NAVY + (int(a),), outline=GOLD + (int(a),), width=4)
    draw_center(d, "VS", F("Bold", 36), 830, GOLD, a)


def paint_bars(d, v, t, L):
    items = v.get("items", [])[:4]
    top = 520
    max_w = 430
    for i, it in enumerate(items):
        delay = 0.15 + 0.25 * i
        a, off = enter(t, delay)
        if a <= 0:
            continue
        val = float(it.get("value", 0) or 0)
        grow = ease_out((t - delay) / 0.6)
        bw = 130 + max_w * (val / 100) * grow
        y = top + i * 200 + off
        col = BAR_COLORS[i % len(BAR_COLORS)]
        rrect(d, (SAFE_X, y, SAFE_X + bw, y + 160), 24, col, alpha=a)
        draw_center(d, f"{int(round(val * grow))}%", F("Bold", 60), y + 80, NAVY, a,
                    x_center=SAFE_X + 85 if bw < 260 else SAFE_X + bw / 2)
        lx = SAFE_X + 130 + max_w * (val / 100) + 40
        lx = min(lx, W - SAFE_X - 260)
        f = fit_font(it.get("label", "").upper(), "Bold", 56, W - SAFE_X - lx)
        d.text((lx, y + 28), it.get("label", "").upper(), font=f, fill=col + (int(a),))
        note = it.get("note", "")
        if note:
            fn = fit_font(note, "Medium", 36, W - SAFE_X - lx)
            d.text((lx, y + 100), note, font=fn, fill=WHITE + (int(a),))


def paint_text(d, v, t, L):
    small, big = v.get("small", ""), v.get("big", "")
    a, off = enter(t, 0)
    yb = 820
    if small:
        for i, line in enumerate(wrap(small, F("Medium", 56), 880)[:2]):
            draw_center(d, line, F("Medium", 56), 560 + i * 72 + off, WHITE, a)
    fb = F("Bold", 104)
    lines = wrap(big.upper(), fb, W - 2 * SAFE_X)
    if len(lines) > 3:
        fb = F("Bold", 80)
        lines = wrap(big.upper(), fb, W - 2 * SAFE_X)[:4]
    for i, line in enumerate(lines):
        a2, off2 = enter(t, 0.15 + 0.08 * i)
        draw_center(d, line, fit_font(line, "Bold", fb.size, W - 2 * SAFE_X),
                    yb + (i - (len(lines) - 1) / 2) * fb.size * 1.15 + off2, GOLD, a2)


def paint_cta(d, v, t, L):
    a, off = enter(t, 0)
    cx, cy = W // 2, 600 + off
    pulse = 1 + 0.04 * math.sin(t * 6)
    r = 120 * pulse
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=NAVY2 + (int(a),), outline=GOLD + (int(a),), width=8)
    draw_center(d, "{MD}", F("Bold", 76), cy, WHITE, a)
    big = v.get("big", "FOLLOW").upper()
    a2, off2 = enter(t, 0.12)
    s = back_out((t - 0.12) / 0.45)
    draw_center(d, big, fit_font(big, "Bold", max(40, 150 * (0.75 + 0.25 * s)), 900), 860 + off2, GOLD, a2)
    small = v.get("small", "")
    a3, off3 = enter(t, 0.3)
    for i, line in enumerate(wrap(small, F("Medium", 54), 880)[:2]):
        draw_center(d, line, F("Medium", 54), 1010 + i * 70 + off3, WHITE, a3)


PAINTERS = {"hook": paint_hook, "big_number": paint_big_number, "list": paint_list,
            "compare": paint_compare, "bars": paint_bars, "text": paint_text, "cta": paint_cta}


# ---------- captions ----------
def caption_chunks(timeline):
    """Group words into 1-3 word chunks for big word-synced captions."""
    chunks = []
    for start, words in timeline:
        cur = []
        for w in words:
            cur.append(w)
            if len(cur) == 3 or w["text"][-1:] in ".,!?":
                chunks.append([dict(x, start=x["start"] + start, end=x["end"] + start) for x in cur])
                cur = []
        if cur:
            chunks.append([dict(x, start=x["start"] + start, end=x["end"] + start) for x in cur])
    return chunks


def draw_caption(d, chunks, now):
    active = None
    for ch in chunks:
        if ch[0]["start"] - 0.05 <= now <= ch[-1]["end"] + 0.12:
            active = ch
    if not active:
        return
    f = F("Bold", 60)
    words = [w["text"].strip(".,!?\"") for w in active]
    space = 18
    widths = [text_w(w, f) for w in words]
    total = sum(widths) + space * (len(words) - 1)
    if total > W - 2 * SAFE_X - 60:
        f = F("Bold", 48)
        widths = [text_w(w, f) for w in words]
        total = sum(widths) + space * (len(words) - 1)
    x = (W - total) / 2
    rrect(d, (x - 30, CAPTION_Y - 52, x + total + 30, CAPTION_Y + 52), 26, (5, 10, 24), alpha=200)
    for w, ww, info in zip(words, widths, active):
        on = info["start"] - 0.03 <= now
        col = GOLD if (info["start"] - 0.03 <= now <= info["end"] + 0.05) else (WHITE if on else MUTED)
        d.text((x, CAPTION_Y), w, font=f, anchor="lm", fill=col + (255,))
        x += ww + space


# ---------- main render ----------
def render(script, voice, out_path, workdir):
    scenes = script["scenes"]
    starts, t0 = [], 0.0
    for v in voice:
        starts.append(t0)
        t0 += v["duration"]
    total = t0 + 0.4
    n_frames = int(total * FPS)
    chunks = caption_chunks([(s, v["words"]) for s, v in zip(starts, voice)])
    bg = make_background()

    # 1) audio: voice track (+ optional quiet music from assets/music)
    concat_list = os.path.join(workdir, "concat.txt")
    with open(concat_list, "w") as f:
        for v in voice:
            f.write(f"file '{os.path.abspath(v['audio'])}'\n")
    voice_wav = os.path.join(workdir, "voice.wav")
    # pad each clip to its scene duration so audio stays in sync with the visuals
    parts = []
    for i, v in enumerate(voice):
        p = os.path.join(workdir, f"pad_{i:02d}.wav")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", v["audio"], "-af",
                        f"apad,atrim=0:{v['duration']:.3f}", "-ar", "44100", "-ac", "2", p], check=True)
        parts.append(p)
    with open(concat_list, "w") as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p)}'\n")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", concat_list,
                    "-af", f"apad,atrim=0:{total:.3f}", voice_wav], check=True)

    music = sorted(glob.glob(os.path.join(MUSIC_DIR, "*.mp3")) + glob.glob(os.path.join(MUSIC_DIR, "*.wav")))
    final_audio = os.path.join(workdir, "mix.m4a")
    if music:
        track = random.choice(music)
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-i", voice_wav, "-stream_loop", "-1", "-i", track,
            "-filter_complex",
            f"[1:a]volume=0.10,atrim=0:{total:.3f},afade=t=out:st={max(0, total - 1):.3f}:d=1[m];"
            "[0:a][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]",
            "-map", "[a]", "-c:a", "aac", "-b:a", "192k", final_audio], check=True)
    else:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", voice_wav, "-af",
                        "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", final_audio],
                       check=True)

    # 2) video frames piped straight into ffmpeg
    enc = subprocess.Popen([
        "ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
        "-r", str(FPS), "-i", "-", "-i", final_audio, "-c:v", "libx264", "-preset",
        os.getenv("X264_PRESET", "veryfast"), "-crf", "19", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-shortest", "-movflags", "+faststart", out_path], stdin=subprocess.PIPE)

    for fi in range(n_frames):
        now = fi / FPS
        idx = max(i for i, s in enumerate(starts) if s <= now) if now >= starts[0] else 0
        s0 = starts[idx]
        L = voice[idx]["duration"] if idx < len(voice) else 1
        lt = now - s0
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        vis = scenes[min(idx, len(scenes) - 1)]["visual"]
        PAINTERS.get(vis.get("kind"), paint_text)(d, vis, lt, L)
        # exit: quick fade in the last 0.12 s of each scene (not the last one)
        if idx < len(scenes) - 1 and L - lt < 0.12:
            k = clamp((L - lt) / 0.12)
            layer.putalpha(layer.getchannel("A").point(lambda a: int(a * k)))
        # entry punch-in zoom on the first frames of a scene
        punch = 1 + 0.035 * (1 - ease_out(lt / 0.25))
        if punch > 1.001:
            nw, nh = int(W * punch), int(H * punch)
            layer = layer.resize((nw, nh), Image.BILINEAR).crop(
                ((nw - W) // 2, (nh - H) // 2, (nw - W) // 2 + W, (nh - H) // 2 + H))
        frame = bg.copy()
        frame.alpha_composite(layer, dest=(0, Y_SHIFT))
        top = ImageDraw.Draw(frame)
        draw_brand(top, now / total)
        draw_caption(top, chunks, now)
        f_small = F("Regular", 26)
        draw_center(top, "Educational example · not financial advice", f_small, 1550, MUTED, 150)
        enc.stdin.write(frame.convert("RGB").tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("ffmpeg encode failed")
    return out_path, total
