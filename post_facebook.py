"""Publishes a reel to a Facebook Page with Meta's official Reels Publishing API (free).

Needs:  FB_PAGE_ID, FB_PAGE_TOKEN  (a never-expiring Page access token, see README)
Optional: GRAPH_VERSION (default v26.0), POST_MODE = publish | draft
"""
import os
import time

import requests

GRAPH = os.getenv("GRAPH_VERSION", "v26.0")


def _check(r):
    if r.status_code >= 400:
        raise RuntimeError(f"Facebook API error {r.status_code}: {r.text[:500]}")
    return r.json()


def post_reel(video_path: str, description: str) -> str:
    page_id = os.environ["FB_PAGE_ID"]
    token = os.environ["FB_PAGE_TOKEN"]
    base = f"https://graph.facebook.com/{GRAPH}/{page_id}/video_reels"

    # 1) start an upload session
    start = _check(requests.post(base, json={"upload_phase": "start", "access_token": token}, timeout=60))
    video_id = start["video_id"]
    upload_url = start.get("upload_url") or f"https://rupload.facebook.com/video-upload/{GRAPH}/{video_id}"

    # 2) upload the file bytes
    size = os.path.getsize(video_path)
    with open(video_path, "rb") as f:
        _check(requests.post(upload_url, data=f, timeout=600, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)}))

    # 3) finish + publish (or save as draft for manual review)
    state = "DRAFT" if os.getenv("POST_MODE", "publish").lower() == "draft" else "PUBLISHED"
    _check(requests.post(base, timeout=60, data={
        "access_token": token, "video_id": video_id, "upload_phase": "finish",
        "video_state": state, "description": description}))

    # 4) wait for processing so failures show up in the run log
    for _ in range(40):
        st = _check(requests.get(f"https://graph.facebook.com/{GRAPH}/{video_id}",
                                 params={"fields": "status", "access_token": token}, timeout=30))
        status = st.get("status", {})
        vs = status.get("video_status")
        if vs in ("ready", "published") or status.get("publishing_phase", {}).get("status") == "complete":
            return video_id
        for phase in ("uploading_phase", "processing_phase", "publishing_phase"):
            err = status.get(phase, {}).get("error")
            if err:
                raise RuntimeError(f"Facebook {phase} error: {err}")
        if vs in ("error", "upload_failed", "expired"):
            raise RuntimeError(f"Facebook processing failed: {status}")
        time.sleep(15)
    return video_id  # still processing; it usually finishes on its own
