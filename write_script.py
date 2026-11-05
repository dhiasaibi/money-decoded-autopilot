"""Writes one 20-30 second Money Decoded reel script with the free Gemini API.

Output is a dict:
{
  "topic": str,
  "scenes": [ {"say": str, "visual": {...}} , ...],
  "caption": str            # Facebook description incl. hashtags
}
Visual kinds the renderer understands:
  hook       {"kind":"hook", "line1": "0% INTEREST?", "line2": "HOW DO THEY", "accent": "MAKE MONEY?"}
  big_number {"kind":"big_number", "label": "ONE-TIME INVESTMENT", "value": "$10,000", "sub": "30 years · 7%"}
  list       {"kind":"list", "title": "5-MINUTE FIX", "items": ["...", "...", "..."]}
  compare    {"kind":"compare", "left_title": "...", "left": "...", "right_title": "...", "right": "...", "winner": "left"|"right"}
  bars       {"kind":"bars", "items": [{"label":"NEEDS","value":50,"note":"Rent, food"} ...]}   # percentages
  text       {"kind":"text", "small": "...", "big": "..."}
  cta        {"kind":"cta", "big": "FOLLOW", "small": "for one money trick a day"}
"""
import json
import os
import random
import re
import time

import requests

GEMINI_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_MODELS", "gemini-3.8-flash,gemini-3.6-flash,gemini-3.5-flash-lite"
).split(",") if m.strip()]
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

BANNED = ["guaranteed", "guarantee", "get rich", "risk-free", "risk free", "can't lose",
          "100% safe", "buy now", "this stock", "this coin"]

PROMPT = """You write viral 20-30 second Facebook Reels for a personal-finance page called "Money Decoded".
Audience: young adults (18-35) in the US/UK/Canada who are bad with money and want quick, clear wins.

TOPIC: {topic}

Write ONE reel. Rules that decide whether people keep watching:
1. The FIRST scene is a hook that creates a question or a shock in under 2 seconds of speech
   (max 9 words spoken). Never start with "Did you know", "Hey guys", "In this video", or the page name.
2. 5 to 7 scenes total. Total spoken words between 60 and 80 (that is ~25 seconds). Short punchy sentences.
3. Every scene teaches or reveals something. No filler, no "let's dive in".
4. Use one concrete example with simple numbers ($2,000, 24%, 3 months). Numbers must be correct math
   and realistic; label them as an example where relevant.
5. The second-to-last scene is the payoff (the actual answer / action). The last scene is a short CTA
   that loops back to the hook (e.g. "Follow, so the bank stops winning.").
6. Educational only. No specific stocks, coins, apps, banks or brokers. No promises of returns.
   No "guaranteed", "get rich", "risk-free".
7. On-screen text is SHORT: hook lines max 3 words each, list items max 5 words, big values like "$12,000" or "24%".

Visual kinds (pick the best per scene; use at least 3 different kinds; scene 1 MUST be "hook"; last MUST be "cta"):
- hook: {{"kind":"hook","line1":"...","line2":"...","accent":"..."}}  (accent is the gold punchline)
- big_number: {{"kind":"big_number","label":"...","value":"...","sub":"..."}}
- list: {{"kind":"list","title":"...","items":["...","...","..."]}}  (2-4 items)
- compare: {{"kind":"compare","left_title":"...","left":"...","right_title":"...","right":"...","winner":"left" or "right"}}
- bars: {{"kind":"bars","items":[{{"label":"...","value":50,"note":"..."}}]}}  (2-4 items, values are percentages)
- text: {{"kind":"text","small":"...","big":"..."}}
- cta: {{"kind":"cta","big":"FOLLOW","small":"..."}}

Also write "caption": a Facebook description of 1-2 short lines that adds curiosity (not a summary),
then a line with 4-6 hashtags like #moneytips #personalfinance.

Return ONLY JSON: {{"topic":"...","scenes":[{{"say":"...","visual":{{...}}}}],"caption":"..."}}
Do not repeat these recent topics or their angles: {recent}
"""


def _call_gemini(prompt: str) -> str:
    key = os.environ["GEMINI_API_KEY"]
    last_err = None
    for model in GEMINI_MODELS:
        for attempt in range(3):
            try:
                r = requests.post(
                    API.format(model=model),
                    headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                    json={
                        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.9,
                                             "responseMimeType": "application/json"},
                    },
                    timeout=90,
                )
                if r.status_code == 429 or r.status_code >= 500:
                    last_err = f"{model}: HTTP {r.status_code}"
                    time.sleep(10 * (attempt + 1))
                    continue
                if r.status_code == 404:
                    last_err = f"{model}: model not found"
                    break  # try next model
                r.raise_for_status()
                parts = r.json()["candidates"][0]["content"]["parts"]
                return "".join(p.get("text", "") for p in parts)
            except requests.RequestException as e:
                last_err = f"{model}: {e}"
                time.sleep(5)
    raise RuntimeError(f"Gemini failed on every model ({last_err})")


def validate(script: dict) -> list:
    problems = []
    scenes = script.get("scenes") or []
    if not 4 <= len(scenes) <= 8:
        problems.append(f"needs 5-7 scenes, got {len(scenes)}")
    if scenes and scenes[0].get("visual", {}).get("kind") != "hook":
        problems.append("first scene must be a hook")
    if scenes and scenes[-1].get("visual", {}).get("kind") != "cta":
        problems.append("last scene must be a cta")
    words = sum(len(s.get("say", "").split()) for s in scenes)
    if not 50 <= words <= 95:
        problems.append(f"spoken words {words}, need 60-80")
    if scenes and len(scenes[0].get("say", "").split()) > 12:
        problems.append("hook too long")
    blob = json.dumps(script).lower()
    for b in BANNED:
        if b in blob:
            problems.append(f"banned phrase: {b}")
    for s in scenes:
        if not s.get("say") or not isinstance(s.get("visual"), dict):
            problems.append("scene missing say/visual")
    if not script.get("caption"):
        problems.append("missing caption")
    return problems


def write_script(topic: str, recent: list) -> dict:
    prompt = PROMPT.format(topic=topic, recent="; ".join(recent[-40:]) or "none")
    feedback = ""
    for _ in range(4):
        raw = _call_gemini(prompt + feedback)
        raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.M).strip()
        try:
            script = json.loads(raw)
        except json.JSONDecodeError:
            feedback = "\n\nYour last answer was not valid JSON. Return only JSON."
            continue
        problems = validate(script)
        if not problems:
            script.setdefault("topic", topic)
            return script
        feedback = "\n\nFix these problems from your last attempt: " + "; ".join(problems)
    raise RuntimeError(f"Could not get a valid script for '{topic}'")


def pick_topic(topics_file: str, history: list) -> str:
    with open(topics_file, encoding="utf-8") as f:
        topics = [t.strip() for t in f if t.strip() and not t.startswith("#")]
    used = {h["topic_seed"] for h in history if "topic_seed" in h}
    fresh = [t for t in topics if t not in used]
    if not fresh:  # bank exhausted: start a new round, avoiding the last 20
        recent = {h.get("topic_seed") for h in history[-20:]}
        fresh = [t for t in topics if t not in recent] or topics
    return random.choice(fresh)
