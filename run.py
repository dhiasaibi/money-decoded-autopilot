"""Money Decoded autopilot: topic -> script -> voice -> video -> Facebook Reel.

  python run.py                     # full run (needs GEMINI_API_KEY, FB_PAGE_ID, FB_PAGE_TOKEN)
  python run.py --no-post           # make the video only (output/latest.mp4)
  python run.py --script samples/sample_script.json --no-post   # render a script you wrote
"""
import argparse
import datetime as dt
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from pipeline.render import render  # noqa: E402
from pipeline.voice import make_voice  # noqa: E402

HISTORY = os.path.join(HERE, "history.json")
OUT_DIR = os.path.join(HERE, "output")


def load_history():
    if os.path.exists(HISTORY):
        with open(HISTORY, encoding="utf-8") as f:
            return json.load(f)
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", help="use this script JSON instead of writing a new one")
    ap.add_argument("--no-post", action="store_true", help="render only, do not post")
    args = ap.parse_args()

    history = load_history()
    if args.script:
        with open(args.script, encoding="utf-8") as f:
            script = json.load(f)
        seed = script.get("topic", "manual")
    else:
        from pipeline.write_script import pick_topic, write_script
        seed = pick_topic(os.path.join(HERE, "topics.txt"), history)
        print(f"Topic: {seed}")
        script = write_script(seed, [h.get("topic", "") for h in history])

    os.makedirs(OUT_DIR, exist_ok=True)
    work = tempfile.mkdtemp(prefix="md_")
    try:
        voice = make_voice(script["scenes"], work)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M")
        out = os.path.join(OUT_DIR, f"reel-{stamp}.mp4")
        _, seconds = render(script, voice, out, work)
        shutil.copy(out, os.path.join(OUT_DIR, "latest.mp4"))
        with open(os.path.join(OUT_DIR, "latest.json"), "w", encoding="utf-8") as f:
            json.dump(script, f, indent=2, ensure_ascii=False)
        print(f"Rendered {out} ({seconds:.1f}s)")

        video_id = None
        if not args.no_post:
            from pipeline.post_facebook import post_reel
            video_id = post_reel(out, script["caption"])
            print(f"Posted reel, video id {video_id}")

        history.append({"date": stamp, "topic_seed": seed, "topic": script.get("topic", seed),
                        "seconds": round(seconds, 1), "video_id": video_id,
                        "posted": bool(video_id)})
        if not args.script:
            with open(HISTORY, "w", encoding="utf-8") as f:
                json.dump(history[-500:], f, indent=1, ensure_ascii=False)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
