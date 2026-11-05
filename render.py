"""Money Decoded reel renderer: 1080x1920 @30fps, motion graphics + sound design.

Pillow draws every frame from cached sprites (fast enough for a free GitHub runner),
FFmpeg encodes. Every animation beat also emits a sound event, so SFX always land
exactly on the motion.
"""
import glob
import math
import os
import random
import re
import subprocess

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from pipeline import sfx

W, H, FPS = 1080, 1920, 30
HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "..", "fonts")
MUSIC_DIR = os.path.join(HERE, "..", "assets", "music")

NAVY = (8, 16, 34)
NAVY2 = (14, 33, 66)
CARD = (17, 35, 70)
CARD_EDGE = (44, 72, 122)
WHITE = (246, 248, 252)
MUTED = (150, 168, 200)
GOLD = (255, 200, 60)
TEAL = (40, 214, 160)
BLUE = (70, 150, 255)
RED = (255, 86, 100)
INK = (6, 10, 22)
BAR_COLORS = [TEAL, GOLD, BLUE, RED]

SAFE_X = 90
CENTER_Y = 860          # visual centre of the content area
CAPTION_Y = 1450
GAP = 6                 # space between caption words (sprites already carry padding)
TR_IN, TR_OUT = 0.24, 0.16   # transition lengths (s)

FONT_FILES = {"Black": "InterDisplay-Black.otf", "XBold": "InterDisplay-ExtraBold.otf",
              "Semi": "InterDisplay-SemiBold.otf", "Bold": "Poppins-Bold.ttf",
              "Medium": "Poppins-Medium.ttf", "Regular": "Poppins-Regular.ttf"}
_fonts = {}


def F(weight, size):
    key = (weight, int(size))
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(os.path.join(FONTS, FONT_FILES[weight]), int(size))
    return _fonts[key]


# ---------------- easing ----------------
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_in(x):
    x = clamp(x)
    return x ** 3


def ease_io(x):
    x = clamp(x)
    return 3 * x * x - 2 * x * x * x


def back_out(x, s=1.9):
    x = clamp(x)
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def spring(t, freq=2.4, damp=7.0):
    """0 -> 1 with overshoot; t in seconds since start."""
    if t <= 0:
        return 0.0
    return 1 - math.exp(-damp * t) * math.cos(2 * math.pi * freq * t)


def slam(t, start_scale=1.6, dur=0.22):
    """scale that slams down from big to 1 with a small bounce."""
    if t <= 0:
        return start_scale
    return 1 + (start_scale - 1) * math.exp(-t * 16) * math.cos(t * 26) if t < 0.6 else 1.0


# ---------------- sprites ----------------
def text_w(t, f):
    b = f.getbbox(t)
    return b[2] - b[0]


def fit(text, weight, size, max_w, min_size=36):
    size = int(size)
    while size > min_size and text_w(text, F(weight, size)) > max_w:
        size -= 3
    return size


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


_sprites = {}


def text_sprite(text, weight, size, color, stroke=0, stroke_color=INK, box=None, pad_x=26, pad_y=12, radius=22):
    key = ("t", text, weight, int(size), color, stroke, stroke_color, box, pad_x, pad_y)
    if key in _sprites:
        return _sprites[key]
    f = F(weight, size)
    asc, desc = f.getmetrics()
    b = f.getbbox(text, stroke_width=stroke)
    w = (b[2] - b[0]) + 2 * pad_x
    h = asc + desc + 2 * pad_y - int(desc * 0.6)
    img = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if box:
        d.rounded_rectangle((0, 0, w - 1, h - 1), radius, fill=box + (255,))
    d.text((pad_x - b[0], pad_y - int(desc * 0.15)), text, font=f, fill=color + (255,),
           stroke_width=stroke, stroke_fill=stroke_color + (255,))
    _sprites[key] = img
    return img


def card_sprite(w, h, fill=CARD, edge=CARD_EDGE, width=3, radius=36, alpha=240):
    key = ("c", w, h, fill, edge, width, radius, alpha)
    if key not in _sprites:
        img = Image.new("RGBA", (int(w), int(h)), (0, 0, 0, 0))
        ImageDraw.Draw(img).rounded_rectangle((0, 0, w - 1, h - 1), radius, fill=fill + (alpha,),
                                              outline=edge + (255,), width=width)
        _sprites[key] = img
    return _sprites[key]


def glow_sprite(src, color, radius=28, strength=1.0):
    key = ("g", id(src), color, radius, strength)
    if key not in _sprites:
        pad = radius * 2
        base = Image.new("RGBA", (src.width + 2 * pad, src.height + 2 * pad), color + (0,))
        a = Image.new("L", base.size, 0)
        a.paste(src.getchannel("A"), (pad, pad))
        a = a.filter(ImageFilter.GaussianBlur(radius)).point(lambda v: min(255, int(v * 1.6 * strength)))
        base.putalpha(a)
        _sprites[key] = base
    return _sprites[key]


def circle_sprite(r, fill=None, edge=None, width=0):
    key = ("o", r, fill, edge, width)
    if key not in _sprites:
        s = int(2 * r + 4)
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse((2, 2, s - 3, s - 3), fill=fill + (255,) if fill else None,
                                    outline=edge + (255,) if edge else None, width=width)
        _sprites[key] = img
    return _sprites[key]


_alpha_luts = {}


def with_alpha(img, a):
    if a >= 0.999:
        return img
    q = int(a * 40)
    if q not in _alpha_luts:
        k = q / 40
        _alpha_luts[q] = [int(v * k) for v in range(256)]
    out = img.copy()
    out.putalpha(img.getchannel("A").point(_alpha_luts[q]))
    return out


# ---------------- frame context + camera ----------------
class Ctx:
    def __init__(self, frame):
        self.frame = frame
        self.zoom, self.ox, self.oy, self.alpha = 1.0, 0.0, 0.0, 1.0
        self.ghost = (0.0, 0.0)   # motion-blur direction during whip transitions

    def cam(self, x, y, s):
        z = self.zoom
        return (W / 2 + (x - W / 2) * z + self.ox, CENTER_Y + (y - CENTER_Y) * z + self.oy, s * z)

    def put(self, sprite, x, y, scale=1.0, alpha=1.0, cam=True, anchor="c"):
        if sprite is None or alpha <= 0.01 or scale <= 0.02:
            return
        if cam:
            x, y, scale = self.cam(x, y, scale)
            alpha *= self.alpha
            if alpha <= 0.01:
                return
        img = sprite
        if abs(scale - 1) > 0.01:
            img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.BILINEAR)
        img = with_alpha(img, alpha)
        if anchor == "c":
            x0, y0 = x - img.width / 2, y - img.height / 2
        else:  # left-centre
            x0, y0 = x, y - img.height / 2
        copies = [(0, 0, img)]
        gx, gy = self.ghost
        if cam and (abs(gx) > 2 or abs(gy) > 2):
            copies = [(gx * k, gy * k, with_alpha(img, a)) for k, a in ((1.0, 0.18), (0.6, 0.3), (0.3, 0.5))] + copies
        for dx, dy, im in copies:
            self._blit(im, int(x0 + dx), int(y0 + dy))

    def _blit(self, img, x, y):
        l, t = max(0, x), max(0, y)
        r, b = min(W, x + img.width), min(H, y + img.height)
        if r <= l or b <= t:
            return
        if (l, t, r, b) != (x, y, x + img.width, y + img.height):
            img = img.crop((l - x, t - y, r - x, b - y))
        self.frame.alpha_composite(img, (l, t))

    def rect(self, box, radius, fill, alpha=1.0):
        """Rounded rect in scene space (goes through the camera)."""
        x0, y0, _ = self.cam(box[0], box[1], 1)
        x1, y1, _ = self.cam(box[2], box[3], 1)
        a = int(255 * alpha * self.alpha)
        if a <= 2 or x1 - x0 < 2:
            return
        layer = Image.new("RGBA", (int(x1 - x0) + 2, int(y1 - y0) + 2), (0, 0, 0, 0))
        ImageDraw.Draw(layer).rounded_rectangle((0, 0, layer.width - 2, layer.height - 2),
                                                int(radius * self.zoom), fill=fill + (a,))
        self._blit(layer, int(x0), int(y0))


# ---------------- background ----------------
def make_background():
    bg = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(bg)
    for y in range(H):  # vertical gradient
        k = y / H
        c = tuple(int(NAVY[i] * (1 - k) + (4, 9, 20)[i] * k) for i in range(3))
        d.line([(0, y), (W, y)], fill=c)
    for x in range(0, W, 90):
        d.line([(x, 0), (x, H)], fill=(17, 30, 56), width=1)
    for y in range(0, H, 90):
        d.line([(0, y), (W, y)], fill=(17, 30, 56), width=1)
    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).ellipse((-260, -160, W + 260, H + 160), fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(220))
    return Image.composite(bg, Image.new("RGB", (W, H), (2, 5, 12)), vig).convert("RGBA")


def blob(color, r=420, a=95):
    img = Image.new("RGBA", (2 * r, 2 * r), color + (0,))
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).ellipse((r * 0.35, r * 0.35, r * 1.65, r * 1.65), fill=a)
    img.putalpha(m.filter(ImageFilter.GaussianBlur(r * 0.3)))
    return img


class Background:
    def __init__(self, seed):
        r = random.Random(seed)
        self.base = make_background()
        self.blobs = [(blob((30, 80, 170)), 0.3, 0.25, 0.11), (blob((12, 110, 100), 380, 80), 0.7, 0.72, 0.08)]
        self.parts = []
        glyphs = ["$", "%", "+", "•"]
        for _ in range(16):
            g = r.choice(glyphs)
            spr = text_sprite(g, "Black", r.randint(28, 60), r.choice([GOLD, TEAL, BLUE]), pad_x=4, pad_y=4)
            self.parts.append((with_alpha(spr, r.uniform(0.10, 0.22)), r.uniform(0, W), r.uniform(0, H),
                               r.uniform(18, 55), r.uniform(0, 6.28)))

    def frame(self, t):
        fr = self.base.copy()
        c = Ctx(fr)
        for img, fx, fy, sp in self.blobs:
            x = W * fx + 140 * math.sin(t * sp * 6.28)
            y = H * fy + 120 * math.cos(t * sp * 5.0)
            c.put(img, x, y, cam=False)
        for img, x, y, speed, ph in self.parts:
            yy = (y - speed * t) % (H + 100) - 50
            c.put(img, x + 16 * math.sin(t * 1.3 + ph), yy, cam=False)
        return fr


# ---------------- number count-up ----------------
NUM_RE = re.compile(r"\d[\d,]*(\.\d+)?")


def count_up(value, p):
    m = NUM_RE.search(value)
    if not m or p >= 1:
        return value
    raw = m.group(0)
    target = float(raw.replace(",", ""))
    cur = target * ease_out(p)
    dec = len(m.group(1)) - 1 if m.group(1) else 0
    s = f"{cur:,.{dec}f}" if "," in raw else f"{cur:.{dec}f}"
    return value[:m.start()] + s + value[m.end():]


# ======================= SCENES =======================
# Each scene kind has plan(v, L) -> dict of timings + list of sound events,
# and paint(c, v, t, L, P) that draws using the same timings.

def shake(c, t, start, amp=22, dur=0.32):
    k = t - start
    if 0 <= k < dur:
        a = amp * (1 - k / dur) ** 2
        c.ox += a * math.sin(k * 95)
        c.oy += a * math.cos(k * 71)


# ---- hook ----
def plan_hook(v, L):
    lines = [x for x in (v.get("line1"), v.get("line2")) if x]
    times = [0.06 + 0.16 * i for i in range(len(lines))]
    acc = (times[-1] + 0.2) if times else 0.08
    ev = [(t, "pop_lo") for t in times] + [(acc - 0.02, "boom")]
    return {"lines": lines, "times": times, "acc": acc}, ev


def paint_hook(c, v, t, L, P):
    lines, accent = P["lines"], (v.get("accent") or "").upper()
    n = len(lines) + (1 if accent else 0)
    y = CENTER_Y - (n - 1) * 92
    breathe = 1 + 0.012 * math.sin(t * 2.4)
    for line, t0 in zip(lines, P["times"]):
        s = fit(line.upper(), "Black", 132, W - 2 * SAFE_X)
        spr = text_sprite(line.upper(), "Black", s, WHITE)
        k = t - t0
        c.put(spr, W / 2, y, slam(k, 1.5) * breathe, clamp(k / 0.08))
        y += 184
    if accent:
        k = t - P["acc"]
        s = fit(accent, "Black", 128, W - 2 * SAFE_X - 60)
        spr = text_sprite(accent, "Black", s, INK, box=GOLD, pad_x=34, pad_y=14, radius=26)
        if k > 0:
            c.put(glow_sprite(spr, GOLD, 30), W / 2, y, slam(k, 1.7) * breathe, 0.55 * clamp(k / 0.1))
        c.put(spr, W / 2, y, slam(k, 1.7) * breathe, clamp(k / 0.06))
    shake(c, t, P["acc"], 26)


# ---- big number ----
def plan_big(v, L):
    val = v.get("value", "")
    has_num = bool(NUM_RE.search(val))
    cu = min(0.85, max(0.45, L * 0.3)) if has_num else 0.0
    start, land = 0.18, 0.18 + cu
    ev = [(0.04, "swish")]
    if has_num:
        tt = start
        while tt < land - 0.04:
            ev.append((tt, "tick"))
            tt += 0.07
    ev += [(land - 0.02, "boom"), (land + 0.02, "cash"), (land + 0.25, "pop")]
    return {"start": start, "land": land, "cu": cu}, ev


def paint_big(c, v, t, L, P):
    label = (v.get("label") or "").upper()
    k = t - 0.04
    if label:
        s = fit(label, "XBold", 54, 900)
        c.put(text_sprite(label, "XBold", s, MUTED), W / 2, CENTER_Y - 210 - 40 * (1 - ease_out(k / 0.3)),
              1, clamp(k / 0.2))
    val = v.get("value", "")
    shown = count_up(val, (t - P["start"]) / P["cu"]) if P["cu"] else val
    size = fit(val, "Black", 250, W - 2 * SAFE_X)
    spr = text_sprite(shown, "Black", size, GOLD)
    kl = t - P["land"]
    sc = 1.0 if kl < 0 else slam(kl, 1.28)
    sc *= 1 + 0.015 * math.sin(t * 2.2)
    if t > P["start"] - 0.05:
        if kl > 0:
            c.put(glow_sprite(text_sprite(val, "Black", size, GOLD), GOLD, 36), W / 2, CENTER_Y, sc,
                  0.35 + 0.4 * math.exp(-kl * 4))
        c.put(spr, W / 2, CENTER_Y, sc, clamp((t - P["start"] + 0.05) / 0.1))
    if 0 < kl < 0.6:  # shockwave ring
        p = ease_out(kl / 0.6)
        c.put(circle_sprite(int(140 + 420 * p), edge=GOLD, width=10), W / 2, CENTER_Y, 1, (1 - p) * 0.8)
    shake(c, t, P["land"], 20)
    sub = v.get("sub", "")
    if sub:
        ks = t - (P["land"] + 0.25)
        for i, line in enumerate(wrap(sub, F("Semi", 58), 880)[:2]):
            c.put(text_sprite(line, "Semi", 58, WHITE), W / 2,
                  CENTER_Y + 200 + i * 74 + 30 * (1 - ease_out(ks / 0.3)), 1, clamp(ks / 0.2))


# ---- list ----
def plan_list(v, L):
    items = (v.get("items") or [])[:4]
    span = max(0.5, L * 0.6)
    times = [0.32 + span * i / max(1, len(items)) for i in range(len(items))]
    ev = [(0.05, "pop_lo")] + [(t, "swish") for t in times] + [(t + 0.1, "pop_hi") for t in times]
    return {"items": items, "times": times}, ev


def paint_list(c, v, t, L, P):
    title = (v.get("title") or "").upper()
    items = P["items"]
    n = len(items)
    top = CENTER_Y - (n * 170) / 2 + 40
    if title:
        s = fit(title, "Black", 84, 900)
        k = t - 0.05
        c.put(text_sprite(title, "Black", s, GOLD), W / 2, top - 110, slam(k, 1.4), clamp(k / 0.08))
    cw = W - 2 * SAFE_X
    for i, (item, t0) in enumerate(zip(items, P["times"])):
        k = t - t0
        if k < 0:
            continue
        active = (i == n - 1) or t < (P["times"][i + 1] if i + 1 < n else 1e9)
        y = top + i * 170 + 70
        x = W / 2 + 520 * (1 - spring(k, 1.8, 8))
        card = card_sprite(cw, 140, edge=GOLD if active else CARD_EDGE, width=5 if active else 3)
        c.put(card, x, y, 1, clamp(k / 0.1) * (1 if active else 0.75))
        kb = k - 0.1
        badge = circle_sprite(36, fill=GOLD if active else (60, 80, 120))
        bx = x - cw / 2 + 74
        c.put(badge, bx, y, back_out(kb / 0.3), clamp(kb / 0.05))
        c.put(text_sprite(str(i + 1), "Black", 42, INK, pad_x=4, pad_y=4), bx, y, back_out(kb / 0.3), clamp(kb / 0.05))
        s = fit(item, "XBold", 56, cw - 180)
        spr = text_sprite(item, "XBold", s, WHITE if active else MUTED, pad_x=0)
        c.put(spr, x - cw / 2 + 140, y, 1, clamp(k / 0.12), anchor="l")


# ---- compare ----
def plan_compare(v, L):
    win = {"left": 0, "right": 1}.get(v.get("winner"))
    tw = max(0.75, L * 0.5)
    ev = [(0.04, "swish"), (0.16, "swish"), (0.34, "boom")]
    if win is not None:
        ev += [(tw, "ding"), (tw + 0.02, "pop_hi")]
    return {"win": win, "tw": tw}, ev


def paint_compare(c, v, t, L, P):
    cards = [(v.get("left_title", ""), v.get("left", "")), (v.get("right_title", ""), v.get("right", ""))]
    gap = 60
    cw, ch = (W - 2 * SAFE_X - gap) // 2, 520
    kw = t - P["tw"]
    for i, (ttl, val) in enumerate(cards):
        k = t - (0.04 + 0.12 * i)
        if k < 0:
            continue
        side = -1 if i == 0 else 1
        cx = SAFE_X + cw / 2 + i * (cw + gap) + side * 560 * (1 - spring(k, 1.7, 8))
        is_win = P["win"] == i and kw > 0
        is_lose = P["win"] is not None and P["win"] != i and kw > 0
        sc = 1 + (0.07 * spring(kw, 1.8, 7) if is_win else (-0.05 * ease_out(kw / 0.3) if is_lose else 0))
        al = clamp(k / 0.1) * (1 - 0.5 * ease_out(kw / 0.3) if is_lose else 1)
        card = card_sprite(cw, ch, edge=GOLD if is_win else CARD_EDGE, width=7 if is_win else 3)
        if is_win:
            c.put(glow_sprite(card, GOLD, 30, 0.7), cx, CENTER_Y, sc, 0.6)
        c.put(card, cx, CENTER_Y, sc, al)
        for j, line in enumerate(wrap(ttl.upper(), F("XBold", 38), cw - 60)[:2]):
            c.put(text_sprite(line, "XBold", 38, MUTED), cx, CENTER_Y - ch / 2 + 80 + j * 50, sc, al)
        size = 88
        while size > 44:
            vl = wrap(val, F("Black", size), cw - 60)
            if len(vl) <= 2:
                break
            size -= 4
        vl = wrap(val, F("Black", size), cw - 60)[:3]
        for j, line in enumerate(vl):
            col = GOLD if is_win else (WHITE if not is_lose else MUTED)
            c.put(text_sprite(line, "Black", size, col), cx,
                  CENTER_Y + 40 + (j - (len(vl) - 1) / 2) * size * 1.12, sc, al)
        if is_win:
            pill = text_sprite("WINNER", "Black", 36, INK, box=GOLD, pad_x=30, pad_y=10, radius=24)
            c.put(pill, cx, CENTER_Y + ch / 2, back_out(kw / 0.35), clamp(kw / 0.06))
        if is_lose:  # red strike across the losing value
            p = ease_out((kw - 0.08) / 0.25)
            if p > 0:
                c.rect((cx - (cw / 2 - 40), CENTER_Y + 34, cx - (cw / 2 - 40) + (cw - 80) * p, CENTER_Y + 46), 6, RED, 0.9)
    k = t - 0.34
    if k > 0:
        badge = circle_sprite(54, fill=NAVY, edge=GOLD, width=5)
        c.put(badge, W / 2, CENTER_Y, slam(k, 2.2), clamp(k / 0.05))
        c.put(text_sprite("VS", "Black", 40, GOLD, pad_x=4, pad_y=4), W / 2, CENTER_Y, slam(k, 2.2), clamp(k / 0.05))
    shake(c, t, 0.34, 12, 0.22)


# ---- bars ----
def plan_bars(v, L):
    items = (v.get("items") or [])[:4]
    times = [0.12 + 0.32 * i for i in range(len(items))]
    ev = []
    for t0 in times:
        ev += [(t0, "pop")] + [(t0 + 0.08 * j, "tick") for j in range(1, 6)]
    if times:
        ev.append((times[-1] + 0.55, "ding"))
    return {"items": items, "times": times}, ev


def paint_bars(c, v, t, L, P):
    items = P["items"]
    n = len(items)
    top = CENTER_Y - (n * 210) / 2 + 105
    max_w = 470
    for i, (it, t0) in enumerate(zip(items, P["times"])):
        k = t - t0
        if k < 0:
            continue
        val = float(it.get("value", 0) or 0)
        g = spring(k, 1.4, 6)
        bw = 150 + max_w * (val / 100) * g
        y = top + i * 210
        col = BAR_COLORS[i % len(BAR_COLORS)]
        c.rect((SAFE_X, y - 78, SAFE_X + bw, y + 78), 26, col, clamp(k / 0.08))
        pct = text_sprite(f"{int(round(val * clamp(g, 0, 1.0)))}%", "Black", 62, INK, pad_x=4)
        c.put(pct, SAFE_X + 80, y, 1, clamp(k / 0.08))
        lx = min(SAFE_X + 150 + max_w * (val / 100) + 40, W - SAFE_X - 280)
        kl = k - 0.12
        label = (it.get("label") or "").upper()
        s = fit(label, "Black", 58, W - SAFE_X - lx)
        c.put(text_sprite(label, "Black", s, col, pad_x=0), lx + 30 * (1 - ease_out(kl / 0.3)), y - 26, 1,
              clamp(kl / 0.12), anchor="l")
        note = it.get("note", "")
        if note:
            s2 = fit(note, "Semi", 38, W - SAFE_X - lx)
            c.put(text_sprite(note, "Semi", s2, WHITE, pad_x=0), lx + 30 * (1 - ease_out(kl / 0.3)), y + 36, 1,
                  clamp((kl - 0.05) / 0.15), anchor="l")


# ---- text ----
def plan_text(v, L):
    words = (v.get("big") or "").upper().split()
    times = [0.18 + 0.09 * i for i in range(len(words))]
    ev = [(0.04, "swish")] + [(t, "pop" if i % 2 else "pop_hi") for i, t in enumerate(times[:7])]
    return {"times": times}, ev


def paint_text(c, v, t, L, P):
    small, big = v.get("small", ""), (v.get("big") or "").upper()
    k = t - 0.04
    if small:
        for i, line in enumerate(wrap(small, F("Semi", 58), 880)[:2]):
            c.put(text_sprite(line, "Semi", 58, WHITE), W / 2, CENTER_Y - 250 + i * 74 + 30 * (1 - ease_out(k / 0.3)),
                  1, clamp(k / 0.2))
    size = 112
    while size > 60 and len(wrap(big, F("Black", size), W - 2 * SAFE_X)) > 3:
        size -= 8
    lines = wrap(big, F("Black", size), W - 2 * SAFE_X)[:4]
    wi = 0
    for li, line in enumerate(lines):
        y = CENTER_Y + 30 + (li - (len(lines) - 1) / 2) * size * 1.12
        words = line.split()
        sprs = [text_sprite(w, "Black", size, GOLD, pad_x=0) for w in words]
        space = size * 0.28
        total = sum(s.width for s in sprs) + space * (len(sprs) - 1)
        x = W / 2 - total / 2
        for spr in sprs:
            t0 = P["times"][wi] if wi < len(P["times"]) else 0
            kk = t - t0
            c.put(spr, x + spr.width / 2, y, back_out(kk / 0.28), clamp(kk / 0.06))
            x += spr.width + space
            wi += 1


# ---- cta ----
def plan_cta(v, L):
    tap = max(0.75, L * 0.5)
    ev = [(0.05, "pop_lo"), (0.25, "pop"), (tap - 0.3, "swish"), (tap, "pop_hi"), (tap + 0.03, "ding")]
    return {"tap": tap}, ev


def paint_cta(c, v, t, L, P):
    k = t - 0.05
    logo_y = CENTER_Y - 210
    ring = circle_sprite(124, fill=NAVY2, edge=GOLD, width=9)
    pulse = 1 + 0.035 * math.sin(t * 5)
    c.put(glow_sprite(ring, GOLD, 26, 0.6), W / 2, logo_y, back_out(k / 0.4) * pulse, 0.5 * clamp(k / 0.1))
    c.put(ring, W / 2, logo_y, back_out(k / 0.4) * pulse, clamp(k / 0.08))
    c.put(text_sprite("{MD}", "Black", 78, WHITE, pad_x=4), W / 2, logo_y, back_out(k / 0.4) * pulse, clamp(k / 0.08))
    kt = t - P["tap"]
    followed = kt > 0
    label = (v.get("big") or "FOLLOW").upper()
    btn = text_sprite("FOLLOWING" if followed else label, "Black", 82,
                      INK, box=TEAL if followed else GOLD, pad_x=64, pad_y=22, radius=50)
    kb = t - 0.25
    press = 1 - 0.1 * math.exp(-kt * 9) * math.cos(kt * 20) if followed else 1
    c.put(glow_sprite(btn, TEAL if followed else GOLD, 30, 0.6), W / 2, CENTER_Y + 30, back_out(kb / 0.4) * press,
          0.45 * clamp(kb / 0.1))
    c.put(btn, W / 2, CENTER_Y + 30, back_out(kb / 0.4) * press, clamp(kb / 0.08))
    if 0 < kt < 0.5:  # tap ripple
        p = ease_out(kt / 0.5)
        c.put(circle_sprite(int(30 + 170 * p), edge=WHITE, width=6), W / 2 + 120, CENTER_Y + 50, 1, 1 - p)
    kp = t - (P["tap"] - 0.32)
    if -0.01 < kp < 0.9:  # finger / cursor dot
        p = ease_io(kp / 0.32)
        px, py = W / 2 + 120 + 260 * (1 - p), CENTER_Y + 50 + 300 * (1 - p)
        a = clamp(kp / 0.08) * (1 - clamp((kp - 0.6) / 0.3))
        dot = circle_sprite(30, fill=WHITE, edge=INK, width=3)
        c.put(dot, px, py, 1 - 0.2 * (0 < kt < 0.12), a * 0.95)
    small = v.get("small", "")
    ks = t - 0.4
    for i, line in enumerate(wrap(small, F("Semi", 56), 880)[:2]):
        c.put(text_sprite(line, "Semi", 56, WHITE), W / 2, CENTER_Y + 200 + i * 72 + 30 * (1 - ease_out(ks / 0.3)),
              1, clamp(ks / 0.2))


SCENES = {"hook": (plan_hook, paint_hook), "big_number": (plan_big, paint_big), "list": (plan_list, paint_list),
          "compare": (plan_compare, paint_compare), "bars": (plan_bars, paint_bars),
          "text": (plan_text, paint_text), "cta": (plan_cta, paint_cta)}

TRANSITIONS = ["whip_left", "zoom", "whip_up", "whip_left", "zoom", "whip_up", "whip_left"]


def apply_transition(c, kind, phase, p):
    """phase 'in' (p 0->1 entering) or 'out' (p 0->1 leaving)."""
    if kind == "whip_left":
        if phase == "in":
            c.ox += W * 1.05 * (1 - ease_out(p))
            c.ghost = (90 * (1 - p), 0)
        else:
            c.ox -= W * 1.05 * ease_in(p)
            c.ghost = (90 * p, 0)
    elif kind == "whip_up":
        if phase == "in":
            c.oy += H * 0.75 * (1 - ease_out(p))
            c.ghost = (0, 110 * (1 - p))
        else:
            c.oy -= H * 0.75 * ease_in(p)
            c.ghost = (0, 110 * p)
    else:  # zoom
        if phase == "in":
            c.zoom *= 1.45 - 0.45 * ease_out(p)
            c.alpha *= clamp(p * 1.6)
        else:
            c.zoom *= 1 + 0.6 * ease_in(p)
            c.alpha *= 1 - ease_in(p)


# ---------------- captions (word-synced, active word highlighted) ----------------
def caption_chunks(timeline):
    chunks = []
    for start, words in timeline:
        cur = []
        for w in words:
            cur.append(dict(w, start=w["start"] + start, end=w["end"] + start))
            if len(cur) == 3 or w["text"][-1:] in ".,!?:":
                chunks.append(cur)
                cur = []
        if cur:
            chunks.append(cur)
    return chunks


def draw_captions(c, chunks, now):
    active = None
    for ch in chunks:
        if ch[0]["start"] - 0.05 <= now <= ch[-1]["end"] + 0.1:
            active = ch
    if not active:
        return
    words = [re.sub(r"[^\w$%'’+-]", "", w["text"]).upper() for w in active]
    size = 66
    while size > 44:
        sprs = [text_sprite(w, "Black", size, WHITE, stroke=7) for w in words]
        total = sum(s.width for s in sprs) + GAP * (len(sprs) - 1)
        if total < W - 2 * SAFE_X - 40:
            break
        size -= 6
    x = W / 2 - total / 2
    k0 = now - active[0]["start"]
    rise = 18 * (1 - ease_out(k0 / 0.15))
    cur = max([i for i, w in enumerate(active) if w["start"] - 0.03 <= now] or [-1])
    for wi, (w, spr, info) in enumerate(zip(words, sprs, active)):
        on = wi == cur
        if on:
            hi = text_sprite(w, "Black", size, INK, box=GOLD, pad_x=22, pad_y=8, radius=16)
            kk = now - info["start"]
            c.put(hi, x + spr.width / 2, CAPTION_Y + rise, 1 + 0.12 * math.exp(-kk * 12), 1, cam=False)
        else:
            c.put(spr, x + spr.width / 2, CAPTION_Y + rise, 1, 1 if now >= info["start"] else 0.85, cam=False)
        x += spr.width + GAP


def draw_chrome(c, progress):
    x, y = SAFE_X, 210
    for txt, col in (("{ ", GOLD), ("MONEY ", WHITE), ("DECODED", TEAL), (" }", GOLD)):
        spr = text_sprite(txt.strip(), "Black", 34, col, pad_x=0, pad_y=4)
        c.put(spr, x, y, cam=False, anchor="l")
        x += spr.width + (10 if txt.endswith(" ") else 2)
    d = ImageDraw.Draw(c.frame)
    d.rounded_rectangle((SAFE_X, 262, W - SAFE_X, 270), 4, fill=(30, 48, 84, 255))
    d.rounded_rectangle((SAFE_X, 262, SAFE_X + max(8, (W - 2 * SAFE_X) * progress), 270), 4, fill=GOLD + (255,))
    c.put(text_sprite("Educational example · not financial advice", "Regular", 26, MUTED, pad_x=0), W / 2, 1560, 1,
          0.55, cam=False)


# ---------------- audio ----------------
def build_audio(voice, starts, total, events, workdir, seed):
    parts = []
    for i, v in enumerate(voice):
        p = os.path.join(workdir, f"pad_{i:02d}.wav")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", v["audio"], "-af",
                        f"apad,atrim=0:{v['duration']:.3f}", "-ar", "44100", "-ac", "2", p], check=True)
        parts.append(p)
    lst = os.path.join(workdir, "concat.txt")
    with open(lst, "w") as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p)}'\n")
    voice_wav = os.path.join(workdir, "voice.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-af",
                    f"apad,atrim=0:{total:.3f},highpass=f=70,acompressor=threshold=-20dB:ratio=3:attack=5:release=80",
                    voice_wav], check=True)

    sfx_wav = os.path.join(workdir, "sfx.wav")
    sfx.build_sfx_track(events, total, sfx_wav)

    user_music = sorted(glob.glob(os.path.join(MUSIC_DIR, "*.mp3")) + glob.glob(os.path.join(MUSIC_DIR, "*.wav")))
    music_wav = os.path.join(workdir, "music.wav")
    if user_music:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", random.Random(seed).choice(user_music),
                        "-t", f"{total:.3f}", "-af", "loudnorm=I=-30", "-ar", "44100", "-ac", "2", music_wav], check=True)
    else:
        sfx.music_bed(total, music_wav, bpm=random.Random(seed).choice([90, 96, 100]), seed=seed)

    out = os.path.join(workdir, "mix.m4a")
    vol = float(os.getenv("MUSIC_VOLUME", "1.0"))
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", voice_wav, "-i", music_wav, "-i", sfx_wav, "-filter_complex",
        f"[0:a]asplit=2[v1][v2];[1:a]volume={vol}[m];"
        "[m][v2]sidechaincompress=threshold=0.03:ratio=5:attack=20:release=400[md];"
        "[v1][md][2:a]amix=inputs=3:normalize=0:weights='1 1 0.9',"
        f"afade=t=out:st={max(0, total - 0.6):.3f}:d=0.6,loudnorm=I=-14:TP=-1.5:LRA=11[a]",
        "-map", "[a]", "-ar", "44100", "-c:a", "aac", "-b:a", "192k", out], check=True)
    return out


# ---------------- main ----------------
def render(script, voice, out_path, workdir):
    scenes = script["scenes"]
    starts, t0 = [], 0.0
    for v in voice:
        starts.append(t0)
        t0 += v["duration"]
    total = t0 + 0.5
    seed = abs(hash(script.get("topic", ""))) % 100000

    plans, events = [], []
    for i, (sc, s0, v) in enumerate(zip(scenes, starts, voice)):
        kind = sc["visual"].get("kind", "text")
        plan, paint = SCENES.get(kind, SCENES["text"])
        P, ev = plan(sc["visual"], v["duration"])
        plans.append((paint, P))
        events += [(s0 + et, name) for et, name in ev]
        if i > 0:
            events.append((s0 - 0.16, "whoosh"))
    if len(scenes) >= 3:
        events.append((starts[-2] - 0.75, "riser"))  # build-up into the payoff
    events.append((0.0, "boom"))

    chunks = caption_chunks([(s, v["words"]) for s, v in zip(starts, voice)])
    bg = Background(seed)
    audio = build_audio(voice, starts, total, events, workdir, seed)

    enc = subprocess.Popen([
        "ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
        "-r", str(FPS), "-i", "-", "-i", audio, "-c:v", "libx264", "-preset",
        os.getenv("X264_PRESET", "veryfast"), "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-shortest", "-movflags", "+faststart", out_path], stdin=subprocess.PIPE)

    n_frames = int(total * FPS)
    last_idx = -1
    for fi in range(n_frames):
        now = fi / FPS
        idx = max(i for i, s in enumerate(starts) if s <= now)
        if idx != last_idx:  # free per-scene sprites (keeps memory flat)
            _sprites.clear()
            last_idx = idx
        L = voice[idx]["duration"]
        lt = now - starts[idx]
        frame = bg.frame(now)
        c = Ctx(frame)
        c.zoom = 1 + 0.04 * ease_io(lt / max(L, 0.1))       # slow push-in
        c.oy += 6 * math.sin(now * 1.7)                      # handheld drift
        c.ox += 4 * math.sin(now * 1.1)
        if idx > 0 and lt < TR_IN:
            apply_transition(c, TRANSITIONS[idx % len(TRANSITIONS)], "in", lt / TR_IN)
        if idx < len(scenes) - 1 and L - lt < TR_OUT:
            apply_transition(c, TRANSITIONS[(idx + 1) % len(TRANSITIONS)], "out", 1 - (L - lt) / TR_OUT)
        paint, P = plans[idx]
        paint(c, scenes[idx]["visual"], lt, L, P)
        draw_chrome(c, now / total)
        draw_captions(c, chunks, now)
        if now < 0.12 or (scenes[idx]["visual"].get("kind") == "hook" and 0 <= lt - P.get("acc", -9) < 0.1):
            k = (0.12 - now) / 0.12 if now < 0.12 else 1 - (lt - P["acc"]) / 0.1
            frame = Image.blend(frame, Image.new("RGBA", (W, H), (255, 255, 255, 255)), 0.35 * clamp(k))
        enc.stdin.write(frame.convert("RGB").tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("ffmpeg encode failed")
    return out_path, total
