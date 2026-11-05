"""Sound design generated in code (numpy only): SFX and a lo-fi music bed.

No downloads, no licences to worry about: every sound is synthesised here.
"""
import wave

import numpy as np

SR = 44100
rng = np.random.default_rng(7)


def _n(sec):
    return max(1, int(SR * sec))


def _norm(x, peak):
    m = np.max(np.abs(x)) or 1.0
    return x / m * peak


def _shaped_noise(dur, fc_curve, width=0.45, win=1024, hop=256):
    """Noise whose centre frequency follows fc_curve(p) for p in 0..1 (overlap-add STFT)."""
    n = _n(dur)
    out = np.zeros(n + win)
    w = np.hanning(win)
    freqs = np.fft.rfftfreq(win, 1 / SR) + 1.0
    for start in range(0, n, hop):
        p = start / n
        fc = fc_curve(p)
        shape = np.exp(-((np.log(freqs) - np.log(fc)) ** 2) / (2 * width ** 2))
        seg = np.fft.irfft(np.fft.rfft(rng.standard_normal(win) * w) * shape)
        out[start:start + win] += seg * w
    return out[:n]


def whoosh(dur=0.42):
    x = _shaped_noise(dur, lambda p: 350 + 4200 * np.sin(np.pi * min(1, p * 1.1)) ** 2)
    p = np.linspace(0, 1, len(x))
    env = np.sin(np.pi * p ** 0.8) ** 2
    return _norm(x * env, 0.55)


def swish(dur=0.22):
    x = _shaped_noise(dur, lambda p: 1500 + 5000 * p, width=0.6)
    env = np.sin(np.pi * np.linspace(0, 1, len(x))) ** 2
    return _norm(x * env, 0.30)


def pop(pitch=1.0):
    n = _n(0.09)
    t = np.arange(n) / SR
    f = (380 + 900 * (1 - np.exp(-t * 60))) * pitch
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-t * 38)
    x[:30] += np.linspace(0.6, 0, 30) * rng.standard_normal(30)  # click
    return _norm(x, 0.42)


def tick():
    n = _n(0.025)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * 2100 * t) * np.exp(-t * 260)
    return _norm(x, 0.16)


def ding():
    n = _n(1.1)
    t = np.arange(n) / SR
    base = 1318.5  # E6
    x = np.zeros(n)
    for mult, amp, dec in [(1, 1, 3.2), (2.0, 0.35, 5), (3.01, 0.18, 7), (4.17, 0.08, 9)]:
        x += amp * np.sin(2 * np.pi * base * mult * t) * np.exp(-t * dec)
    x *= np.minimum(1, t / 0.004)
    return _norm(x, 0.30)


def cash():
    """Two quick bright dings, a 'cha-ching' feel without a sample."""
    a, b = ding() * 0.8, ding()
    out = np.zeros(len(b) + _n(0.09))
    out[:len(a)] += a
    out[_n(0.09):] += b
    return _norm(out, 0.30)


def boom():
    n = _n(0.9)
    t = np.arange(n) / SR
    f = 42 + 70 * np.exp(-t * 14)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 4.2)
    hit = _shaped_noise(0.12, lambda p: 900 - 600 * p, width=0.8)
    hit *= np.exp(-np.arange(len(hit)) / SR * 35)
    x = body
    x[:len(hit)] += hit * 0.6
    return _norm(np.tanh(x * 1.8), 0.85)


def riser(dur=0.8):
    x = _shaped_noise(dur, lambda p: 300 + 6000 * p ** 1.6, width=0.5)
    env = np.linspace(0, 1, len(x)) ** 2.2
    env[-_n(0.03):] *= np.linspace(1, 0, _n(0.03))
    return _norm(x * env, 0.38)


SOUNDS = {"whoosh": whoosh, "swish": swish, "pop": pop, "pop_hi": lambda: pop(1.35),
          "pop_lo": lambda: pop(0.8), "tick": tick, "ding": ding, "cash": cash,
          "boom": boom, "riser": riser}


def build_sfx_track(events, total, path):
    """events: list of (time_seconds, name). A sound that starts before 0 is trimmed."""
    out = np.zeros(_n(total) + SR)
    cache = {}
    for t, name in sorted(events):
        if name not in SOUNDS:
            continue
        if name not in cache or name.startswith("pop") or name in ("whoosh", "swish"):
            cache[name] = SOUNDS[name]()  # fresh noise each time keeps it natural
        s = cache[name]
        i = int(t * SR)
        if i < 0:
            s, i = s[-i:], 0
        end = min(len(out), i + len(s))
        out[i:end] += s[:end - i]
    write_wav(out[:_n(total)], path)


# ---------------- music bed ----------------
def _midi(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def _lowpass(x, cutoff):
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    spec *= 1 / np.sqrt(1 + (f / cutoff) ** 4)
    return np.fft.irfft(spec, len(x))


def music_bed(total, path, bpm=96, seed=None):
    r = np.random.default_rng(seed)
    progressions = [
        [[57, 60, 64, 67], [53, 57, 60, 64], [48, 52, 55, 59], [55, 59, 62, 65]],  # Am7 Fmaj7 Cmaj7 G7
        [[50, 53, 57, 60], [55, 58, 62, 65], [48, 52, 55, 58], [53, 57, 60, 64]],  # Dm7 Gm7 C7 Fmaj7
        [[52, 55, 59, 62], [48, 52, 55, 59], [55, 59, 62, 66], [50, 54, 57, 60]],  # Em7 Cmaj7 Gmaj7 D7
    ]
    prog = progressions[r.integers(len(progressions))]
    n = _n(total)
    t = np.arange(n) / SR
    beat = 60 / bpm
    bar = 4 * beat
    pad = np.zeros(n)
    bass = np.zeros(n)
    for b in range(int(total / bar) + 1):
        chord = prog[b % len(prog)]
        s, e = int(b * bar * SR), min(n, int((b + 1) * bar * SR))
        if s >= n:
            break
        tt = t[s:e] - b * bar
        seg = np.zeros(e - s)
        for m in chord:
            for det in (-0.004, 0.004):
                f = _midi(m) * (1 + det)
                for k in range(1, 6):
                    seg += np.sin(2 * np.pi * f * k * tt + k) / k
        fade = np.minimum(1, tt / 0.08) * np.minimum(1, (bar - tt) / 0.08)
        pad[s:e] = seg * fade
        root = _midi(chord[0] - 24)
        bass[s:e] = np.sin(2 * np.pi * root * tt) * fade
    pad = _lowpass(pad, 1400)
    pad *= 0.85 + 0.15 * np.sin(2 * np.pi * t / beat)  # gentle pulse

    drums = np.zeros(n)
    kick_n = _n(0.35)
    kt = np.arange(kick_n) / SR
    kick = np.sin(2 * np.pi * np.cumsum(45 + 90 * np.exp(-kt * 30)) / SR) * np.exp(-kt * 9)
    hat_n = _n(0.05)
    hat = r.standard_normal(hat_n)
    hat = (hat - np.convolve(hat, np.ones(8) / 8, "same")) * np.exp(-np.arange(hat_n) / SR * 90)
    snr_n = _n(0.18)
    snare = _lowpass(r.standard_normal(snr_n), 3500) * np.exp(-np.arange(snr_n) / SR * 22)
    steps = int(total / (beat / 2)) + 1
    for i in range(steps):
        pos = int(i * beat / 2 * SR)
        if pos >= n:
            break
        def add(sample, gain):
            end = min(n, pos + len(sample))
            drums[pos:end] += sample[:end - pos] * gain
        if i % 8 in (0, 3):           # kick on 1 and the "and" of 2
            add(kick, 1.0)
        if i % 8 in (2, 6):           # snare on 2 and 4
            add(snare, 0.35)
        add(hat, 0.22 if i % 2 else 0.12)

    mix = _norm(pad, 1) * 0.5 + _norm(bass, 1) * 0.35 + _norm(drums, 1) * 0.55
    fade_in, fade_out = _n(0.4), _n(1.2)
    mix[:fade_in] *= np.linspace(0, 1, fade_in)
    mix[-fade_out:] *= np.linspace(1, 0, fade_out)
    rms = np.sqrt(np.mean(mix ** 2)) or 1
    mix = mix / rms * 10 ** (-26 / 20)  # quiet bed (~ -26 dBFS RMS)
    write_wav(mix, path)


def write_wav(x, path):
    x = np.clip(x, -1, 1)
    data = (x * 32767).astype("<i2")
    stereo = np.repeat(data[:, None], 2, axis=1)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(stereo.tobytes())
