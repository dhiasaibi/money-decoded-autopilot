"""Free neural voiceover with word timings (edge-tts, no API key).

For each scene: writes scene_XX.mp3 and returns
  {"audio": path, "duration": seconds, "words": [{"text":..,"start":..,"end":..}, ...]}
"""
import asyncio
import os
import subprocess

VOICE = os.getenv("VOICE", "en-US-AndrewMultilingualNeural")
RATE = os.getenv("VOICE_RATE", "+10%")
TAIL = 0.18  # breath between scenes (seconds)


def _probe(path: str) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", path])
    return float(out.strip())


async def _tts(text: str, path: str):
    import edge_tts
    comm = edge_tts.Communicate(text, VOICE, rate=RATE, boundary="WordBoundary")
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


def _estimate(text: str):
    """Silent fallback for local tests only (no network): ~2.7 words/sec."""
    words, t = [], 0.15
    for w in text.split():
        d = 0.16 + 0.045 * len(w)
        words.append({"text": w, "start": t, "end": t + d})
        t += d + 0.04
    return words, t + 0.2


def make_voice(scenes: list, workdir: str) -> list:
    out = []
    allow_silent = os.getenv("ALLOW_SILENT_VOICE") == "1"
    for i, s in enumerate(scenes):
        path = os.path.join(workdir, f"scene_{i:02d}.mp3")
        try:
            words = asyncio.run(_tts(s["say"], path))
            dur = _probe(path) + TAIL
        except Exception as e:  # noqa: BLE001
            if not allow_silent:
                raise RuntimeError(f"Voice generation failed: {e}") from e
            words, dur = _estimate(s["say"])
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            "anullsrc=r=24000:cl=mono", "-t", f"{dur:.3f}", path], check=True)
        out.append({"audio": path, "duration": dur, "words": words})
    return out
