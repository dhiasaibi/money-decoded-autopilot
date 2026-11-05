"""Free voiceover with word timings. Tries engines in order until one works:

  1. edge-tts  (Microsoft neural voices, online, no key) - several voices, with retries
  2. Piper     (open-source neural voice, runs offline on the GitHub runner, no key)

All scenes of one reel always use the same engine + voice, so the voice never changes mid-video.
For each scene returns {"audio": path, "duration": seconds, "words": [{"text","start","end"}]}.
"""
import asyncio
import os
import subprocess
import time
import wave

TAIL = 0.18  # breath between scenes (seconds)
RATE = os.getenv("VOICE_RATE", "+10%")
EDGE_VOICES = [v for v in dict.fromkeys([
    os.getenv("VOICE", "en-US-AndrewMultilingualNeural"),
    "en-US-AndrewNeural", "en-US-GuyNeural", "en-US-ChristopherNeural", "en-US-BrianNeural",
]) if v]
PIPER_VOICE = os.getenv("PIPER_VOICE", "en_US-ryan-high")
PIPER_DIR = os.getenv("PIPER_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".piper"))


def _probe(path: str) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", path])
    return float(out.strip())


def _spread_words(text: str, duration: float, lead: float = 0.08):
    """Word timings estimated from the real clip length (weighted by word length)."""
    words = text.split()
    weights = [len(w.strip(".,!?;:\"'")) + 2 for w in words]
    total_w = sum(weights) or 1
    speech = max(0.3, duration - lead - 0.12)
    out, t = [], lead
    for w, k in zip(words, weights):
        d = speech * k / total_w
        out.append({"text": w, "start": t, "end": t + d * 0.92})
        t += d
    return out


# ---------- engine 1: edge-tts ----------
async def _edge(text: str, path: str, voice: str):
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate=RATE, boundary="WordBoundary")
    words = []
    with open(path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append({"text": chunk["text"], "start": start,
                              "end": start + chunk["duration"] / 1e7})
    return words


def _edge_all(scenes, workdir):
    last = None
    for voice in EDGE_VOICES:
        try:
            out = []
            for i, s in enumerate(scenes):
                path = os.path.join(workdir, f"scene_{i:02d}.mp3")
                for attempt in range(2):
                    try:
                        words = asyncio.run(_edge(s["say"], path, voice))
                        break
                    except Exception as e:  # noqa: BLE001
                        last = e
                        if attempt == 1:
                            raise
                        time.sleep(3 * (attempt + 1))
                dur = _probe(path)
                if not words:
                    words = _spread_words(s["say"], dur)
                out.append({"audio": path, "duration": dur + TAIL, "words": words})
            print(f"Voice: edge-tts {voice}")
            return out
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"edge-tts voice {voice} failed: {e}")
    raise RuntimeError(f"edge-tts unavailable ({last})")


# ---------- engine 2: Piper (offline) ----------
def _piper_model():
    os.makedirs(PIPER_DIR, exist_ok=True)
    onnx = os.path.join(PIPER_DIR, f"{PIPER_VOICE}.onnx")
    if not os.path.exists(onnx):
        subprocess.run(["python", "-m", "piper.download_voices", PIPER_VOICE,
                        "--data-dir", PIPER_DIR], check=True)
    return onnx


def _piper_all(scenes, workdir):
    from piper import PiperVoice, SynthesisConfig
    voice = PiperVoice.load(_piper_model())
    cfg = SynthesisConfig(length_scale=float(os.getenv("PIPER_SPEED", "0.88")))
    out = []
    for i, s in enumerate(scenes):
        wav_path = os.path.join(workdir, f"scene_{i:02d}.wav")
        with wave.open(wav_path, "wb") as wf:
            voice.synthesize_wav(s["say"], wf, syn_config=cfg)
        dur = _probe(wav_path)
        out.append({"audio": wav_path, "duration": dur + TAIL, "words": _spread_words(s["say"], dur)})
    print(f"Voice: Piper {PIPER_VOICE}")
    return out


# ---------- silent fallback, local tests only ----------
def _silent_all(scenes, workdir):
    out = []
    for i, s in enumerate(scenes):
        dur = 0.4 * len(s["say"].split()) + 0.3
        path = os.path.join(workdir, f"scene_{i:02d}.wav")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "anullsrc=r=24000:cl=mono", "-t", f"{dur:.3f}", path], check=True)
        out.append({"audio": path, "duration": dur + TAIL, "words": _spread_words(s["say"], dur)})
    return out


def make_voice(scenes: list, workdir: str) -> list:
    engines = [("edge-tts", _edge_all), ("piper", _piper_all)]
    if os.getenv("VOICE_ENGINE") == "piper":
        engines.reverse()
    errors = []
    for name, fn in engines:
        try:
            return fn(scenes, workdir)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
            print(f"Voice engine {name} failed, trying the next one")
    if os.getenv("ALLOW_SILENT_VOICE") == "1":
        return _silent_all(scenes, workdir)
    raise RuntimeError("Voice generation failed on every engine: " + " | ".join(errors))
