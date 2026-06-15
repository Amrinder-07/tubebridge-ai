import json
import os
import random
import re
import string
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except Exception:  # pragma: no cover
    YouTubeTranscriptApi = None

load_dotenv()

APP_ROOT = Path(__file__).parent
DATA_DIR = APP_ROOT / "data"
LINKS_FILE = DATA_DIR / "links.json"
EVENTS_FILE = DATA_DIR / "events.json"

app = Flask(__name__)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def read_json(path, default):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(default, indent=2))
        return default
    try:
        return json.loads(path.read_text() or json.dumps(default))
    except json.JSONDecodeError:
        return default


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def slugify(text):
    text = (text or "smart-link").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:45] or "smart-link"


def random_suffix(n=5):
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(n))


def unique_slug(base):
    links = read_json(LINKS_FILE, [])
    slugs = {link["slug"] for link in links}
    candidate = base
    while candidate in slugs:
        candidate = f"{base}-{random_suffix()}"
    return candidate


def extract_youtube_id(url):
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().replace("www.", "")
    if host == "youtu.be":
        return parsed.path.strip("/").split("/")[0]
    if "youtube.com" in host:
        qs = parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            return qs["v"][0]
        parts = [p for p in parsed.path.split("/") if p]
        if parts:
            if parts[0] in {"shorts", "embed", "live"} and len(parts) > 1:
                return parts[1]
    return None


def youtube_watch_url(video_id):
    return f"https://www.youtube.com/watch?v={video_id}"


def youtube_app_url(video_id):
    return f"youtube://watch?v={video_id}"


def android_intent_url(video_id):
    return (
        f"intent://www.youtube.com/watch?v={video_id}"
        "#Intent;scheme=https;package=com.google.android.youtube;"
        "S.browser_fallback_url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3D"
        f"{video_id};end"
    )


def fetch_youtube_oembed(url):
    try:
        response = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            timeout=8,
        )
        if response.ok:
            return response.json()
    except Exception:
        return {}
    return {}


def fetch_transcript(video_id):
    if YouTubeTranscriptApi is None:
        return {"available": False, "text": "", "reason": "Transcript package unavailable."}
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
        chunks = [item.get("text", "") for item in transcript[:120]]
        text = " ".join(chunks)
        text = re.sub(r"\s+", " ", text).strip()
        return {"available": True, "text": text[:5000], "reason": ""}
    except Exception as exc:
        return {"available": False, "text": "", "reason": str(exc)[:220]}


def default_ai_pack(title, author, transcript_available=False):
    topic = title or "this video"
    source_note = "Instagram may open this inside its browser, where viewers are often not signed in."
    return {
        "content_category": "YouTube video",
        "summary": f"A YouTube video from {author or 'the creator'}: {topic}",
        "goal": "Get more viewers to open YouTube where they can like, comment, and subscribe.",
        "headline": f"Watch “{topic}” on YouTube",
        "description": f"{source_note} Tap below to open YouTube for the best experience.",
        "cta_variants": [
            "Open in YouTube App",
            "Open YouTube to Like & Subscribe",
            "Watch on YouTube",
        ],
        "source_specific_copy": {
            "instagram": "Instagram opened this in its browser. Tap below to open YouTube, where you’re more likely to already be signed in.",
            "tiktok": "TikTok may keep this inside its browser. Tap below to open YouTube for likes, comments, and subscribing.",
            "default_mobile": "Open this in the YouTube app for the best viewing experience.",
        },
        "friction_score": 72,
        "friction_reasons": [
            "Social apps often open links inside an in-app browser.",
            "Viewers may not be signed into YouTube inside that browser.",
            "A user-tapped button usually works better than an automatic redirect from in-app browsers.",
        ],
        "recommendations": [
            "Use a clear CTA that mentions YouTube, likes, comments, or subscribing.",
            "Keep desktop visitors on auto-redirect so they are not interrupted.",
            "A/B test at least two CTA variants from Instagram traffic.",
        ],
        "transcript_used": transcript_available,
        "ai_mode": "fallback_rules",
    }


def generate_ai_pack(video_id, metadata, transcript):
    title = metadata.get("title", "")
    author = metadata.get("author_name", "")
    base = default_ai_pack(title, author, transcript.get("available", False))

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or OpenAI is None:
        return base

    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    transcript_text = transcript.get("text", "")

    prompt = {
        "video_id": video_id,
        "title": title,
        "channel": author,
        "transcript_available": transcript.get("available", False),
        "transcript_excerpt": transcript_text[:4500],
        "product": "AI-powered YouTube bio link optimizer for creators",
        "goal": "Generate concise high-converting landing page text for social bio traffic, especially Instagram/TikTok in-app browsers. Desktop visitors auto-redirect and do not need landing copy.",
    }

    schema_instruction = """
Return only valid JSON with this exact shape:
{
  "content_category": "short category, e.g. tutorial, vlog, music video, podcast, review, comedy, fitness",
  "summary": "1 sentence about what the video is about",
  "goal": "conversion goal for this link",
  "headline": "short headline, max 70 chars",
  "description": "short mobile landing page description, max 220 chars",
  "cta_variants": ["CTA 1", "CTA 2", "CTA 3"],
  "source_specific_copy": {
    "instagram": "copy for Instagram in-app browser visitors, max 180 chars",
    "tiktok": "copy for TikTok in-app browser visitors, max 180 chars",
    "default_mobile": "copy for regular mobile browser visitors, max 160 chars"
  },
  "friction_score": 0,
  "friction_reasons": ["reason 1", "reason 2", "reason 3"],
  "recommendations": ["action 1", "action 2", "action 3"]
}
The friction_score should be 0-100, where 100 means very high chance users get stuck in an in-app browser instead of opening YouTube. Be honest and do not claim app-opening is guaranteed.
"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a conversion-focused product AI for creator smart links. You write clear, honest, short copy. Never promise guaranteed app opens."},
                {"role": "user", "content": schema_instruction + "\nINPUT:\n" + json.dumps(prompt, ensure_ascii=False)},
            ],
            temperature=0.8,
        )
        raw = response.choices[0].message.content.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)
        merged = {**base, **data}
        merged["transcript_used"] = transcript.get("available", False)
        merged["ai_mode"] = "openai"
        return merged
    except Exception as exc:
        base["ai_error"] = str(exc)[:240]
        return base


def detect_context(user_agent, referrer):
    ua = (user_agent or "").lower()
    ref = (referrer or "").lower()
    is_mobile = any(token in ua for token in ["iphone", "android", "mobile", "ipad"])
    is_ios = any(token in ua for token in ["iphone", "ipad", "ipod"])
    is_android = "android" in ua
    is_instagram = "instagram" in ua or "instagram" in ref
    is_tiktok = "tiktok" in ua or "tiktok" in ref
    is_facebook = "fbav" in ua or "fban" in ua or "facebook" in ref
    source = "instagram" if is_instagram else "tiktok" if is_tiktok else "facebook" if is_facebook else "default_mobile" if is_mobile else "desktop"
    return {
        "user_agent": user_agent or "",
        "referrer": referrer or "",
        "is_mobile": is_mobile,
        "is_ios": is_ios,
        "is_android": is_android,
        "is_instagram": is_instagram,
        "is_tiktok": is_tiktok,
        "is_facebook": is_facebook,
        "source": source,
    }


def log_event(link_id, event_type, extra=None):
    events = read_json(EVENTS_FILE, [])
    events.append({
        "id": random_suffix(10),
        "link_id": link_id,
        "event_type": event_type,
        "created_at": now_iso(),
        "user_agent": request.headers.get("User-Agent", ""),
        "referrer": request.headers.get("Referer", ""),
        "extra": extra or {},
    })
    write_json(EVENTS_FILE, events)


def find_link(slug):
    links = read_json(LINKS_FILE, [])
    for link in links:
        if link.get("slug") == slug:
            return link
    return None


@app.route("/", methods=["GET"])
def home():
    links = read_json(LINKS_FILE, [])
    base_url = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")
    return render_template("index.html", links=list(reversed(links))[:20], base_url=base_url)


@app.route("/create", methods=["POST"])
def create_link():
    youtube_url = request.form.get("youtube_url", "").strip()
    desired_slug = request.form.get("slug", "").strip()
    goal = request.form.get("goal", "subscribers").strip()

    video_id = extract_youtube_id(youtube_url)
    if not video_id:
        return render_template("error.html", message="Please paste a valid YouTube video, Shorts, live, or youtu.be link."), 400

    canonical_url = youtube_watch_url(video_id)
    metadata = fetch_youtube_oembed(canonical_url)
    transcript = fetch_transcript(video_id)
    ai_pack = generate_ai_pack(video_id, metadata, transcript)
    ai_pack["selected_goal"] = goal

    base_slug = slugify(desired_slug or metadata.get("title") or f"youtube-{video_id}")
    slug = unique_slug(base_slug)
    link_id = random_suffix(12)
    link = {
        "id": link_id,
        "slug": slug,
        "video_id": video_id,
        "original_url": canonical_url,
        "youtube_app_url": youtube_app_url(video_id),
        "android_intent_url": android_intent_url(video_id),
        "title": metadata.get("title", "YouTube Video"),
        "author_name": metadata.get("author_name", ""),
        "thumbnail_url": metadata.get("thumbnail_url", ""),
        "provider_name": metadata.get("provider_name", "YouTube"),
        "goal": goal,
        "ai_pack": ai_pack,
        "transcript_status": {"available": transcript.get("available", False), "reason": transcript.get("reason", "")},
        "created_at": now_iso(),
    }
    links = read_json(LINKS_FILE, [])
    links.append(link)
    write_json(LINKS_FILE, links)
    return redirect(url_for("dashboard_link", slug=slug))


@app.route("/dashboard/<slug>")
def dashboard_link(slug):
    link = find_link(slug)
    if not link:
        return render_template("error.html", message="Smart link not found."), 404
    events = [e for e in read_json(EVENTS_FILE, []) if e.get("link_id") == link.get("id")]
    counts = {}
    for event in events:
        counts[event["event_type"]] = counts.get(event["event_type"], 0) + 1
    base_url = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")
    public_url = f"{base_url}/l/{slug}"
    return render_template("dashboard.html", link=link, counts=counts, events=list(reversed(events))[:25], public_url=public_url)


@app.route("/l/<slug>")
def smart_link(slug):
    link = find_link(slug)
    if not link:
        return render_template("error.html", message="Smart link not found."), 404

    ctx = detect_context(request.headers.get("User-Agent", ""), request.headers.get("Referer", ""))
    log_event(link["id"], "page_view", {"source": ctx["source"], "is_mobile": ctx["is_mobile"]})

    if not ctx["is_mobile"]:
        log_event(link["id"], "desktop_auto_redirect", {"to": link["original_url"]})
        return render_template("redirecting.html", destination=link["original_url"])

    ai_pack = link.get("ai_pack", {})
    source_copy = ai_pack.get("source_specific_copy", {}).get(ctx["source"]) or ai_pack.get("source_specific_copy", {}).get("default_mobile")
    ctas = ai_pack.get("cta_variants") or ["Open in YouTube App"]
    variant_index = random.randint(0, min(2, len(ctas) - 1))
    selected_cta = ctas[variant_index]
    log_event(link["id"], "cta_variant_shown", {"variant": selected_cta, "variant_index": variant_index, "source": ctx["source"]})

    return render_template("landing.html", link=link, ctx=ctx, source_copy=source_copy, selected_cta=selected_cta, variant_index=variant_index)


@app.route("/api/event", methods=["POST"])
def api_event():
    payload = request.get_json(silent=True) or {}
    link_id = payload.get("link_id")
    event_type = payload.get("event_type")
    if not link_id or not event_type:
        return jsonify({"ok": False}), 400
    log_event(link_id, event_type, payload.get("extra", {}))
    return jsonify({"ok": True})


@app.route("/health")
def health():
    return jsonify({"ok": True, "time": now_iso()})


if __name__ == "__main__":
    port = 8000
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    app.run(host="127.0.0.1", port=port, debug=True)
