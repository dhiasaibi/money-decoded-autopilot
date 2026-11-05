# Money Decoded Autopilot

Makes and posts **2 Facebook Reels a day** to the Money Decoded page, on its own, for $0.

```
topics.txt ─► Gemini (free) writes a 25s script ─► edge-tts (free) voice + word timings
          ─► Pillow + FFmpeg render 1080×1920 in the Money Decoded look ─► Meta Reels API posts it
```
Runs on **GitHub Actions** (free) on a schedule, so your computer can be off.

| Piece | Tool | Cost |
|---|---|---|
| Server / scheduler | GitHub Actions | Free (unlimited on a public repo, 2,000 min/month private; each run ≈ 4 min) |
| Script writing | Google Gemini API free tier (Flash models) | Free, no card |
| Voiceover | edge-tts (Microsoft neural voices) | Free, no key |
| Video | Pillow + FFmpeg (in this repo) | Free |
| Posting | Meta Graph API, Reels Publishing | Free |

---

## Setup (about 30 minutes, once)

### 1. Put the code on GitHub
1. Create a free account at github.com.
2. New repository → name it `money-decoded-autopilot` → **Private** is fine.
3. Upload every file in this folder (drag and drop on the repo page works). Keep the
   `.github/workflows/autopost.yml` path exactly as it is.

### 2. Free Gemini key
1. Go to **aistudio.google.com** → *Get API key* → *Create API key*.
2. Do **not** add billing — staying unbilled keeps it on the free tier.

### 3. Facebook Page token (the only fiddly step)
1. Go to **developers.facebook.com** → *My Apps* → *Create App* → use case *Other* → type **Business**.
   Leave the app in Development mode; you don't need App Review to post to a Page you admin.
2. Open **Graph API Explorer** (Tools menu). Pick your app, then *User Token*, and tick:
   `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`.
   Click *Generate Access Token* and allow Money Decoded.
3. In the app's *Settings → Basic* copy the **App ID** and **App Secret**.
4. On your computer run `pip install requests` then `python get_page_token.py` and paste the three values.
   It prints **FB_PAGE_ID** and a never-expiring **FB_PAGE_TOKEN**.

### 4. Add the secrets to GitHub
Repo → *Settings → Secrets and variables → Actions → New repository secret*:

| Name | Value |
|---|---|
| `GEMINI_API_KEY` | from step 2 |
| `FB_PAGE_ID` | from step 3 |
| `FB_PAGE_TOKEN` | from step 3 |

Optional *Variables* (same page, Variables tab):
- `POST_MODE` = `draft` → reels land as drafts in Meta Business Suite so you approve each one. Good for week one.
- `VOICE` = another edge-tts voice, e.g. `en-US-GuyNeural`, `en-US-ChristopherNeural`, `en-GB-RyanNeural`.

### 5. Test, then let it run
Repo → *Actions* → *Money Decoded autopilot* → *Run workflow*.
- Set **post = false** first: the run renders a reel you can download from the run page (*Artifacts*).
- Happy with it? Run again with **post = true**. From then on it posts by itself at 16:47 and 00:23 UTC
  (late morning and evening in the US). Change the times in `autopost.yml`.

---

## Customising
- **Topics:** edit `topics.txt` (one per line). Used topics are tracked in `history.json`.
- **Music:** drop royalty-free tracks you're allowed to use (e.g. YouTube Audio Library) into `assets/music/`.
  One is picked at random and mixed quietly under the voice. Never use chart music — it blocks monetization.
- **Post frequency:** add or remove `cron` lines. Meta allows up to 30 API reels a day, but 1–3 good ones beat 10 weak ones.
- **Render a script you wrote yourself:** `python run.py --script samples/sample_script.json --no-post`

## If something breaks
- *Gemini 404 / model not found*: Google renamed models. Set a repo variable `GEMINI_MODELS`
  to the current free Flash model names from aistudio.google.com (comma separated).
- *Gemini 429*: free-tier limit hit; the run retries and falls back to the next model.
- *Facebook error 190*: token invalid — rerun `get_page_token.py`.
- *Facebook error 200 / permissions*: regenerate the user token with the three permissions above.
- GitHub pauses schedules after 60 days without commits; each run commits `history.json`, so it stays active.
