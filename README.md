# OpenInApp AI v3 — AI-powered YouTube Bio Link Optimizer

This is a Python Flask MVP for smart YouTube bio links.

## What it does

- Creates smart `/l/<slug>` links for YouTube videos, Shorts, live links, and youtu.be links
- Desktop visitors auto-redirect to YouTube
- Mobile visitors see a smart landing page with an app-open CTA
- Detects Instagram/TikTok/Facebook in-app browsers and shows source-specific instructions
- Extracts YouTube metadata using YouTube oEmbed
- Tries to extract transcript text using `youtube-transcript-api`
- Uses OpenAI to generate:
  - video category
  - video summary
  - custom headline
  - custom description
  - 3 CTA variants
  - Instagram/TikTok/default mobile copy
  - friction score
  - friction reasons
  - recommendations
- Randomly shows CTA variants and tracks which variant was displayed
- Tracks events in local JSON files

## Run locally on Mac

```bash
cd ~/Downloads
unzip openinapp-ai-v3.zip
cd openinapp-ai-v3
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Open:

```text
http://127.0.0.1:8000
```

Use a different port:

```bash
python app.py 8001
```

## Enable AI

Open `.env` and add your OpenAI API key:

```env
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini
APP_BASE_URL=http://127.0.0.1:8000
```

If no API key is set, the app still works, but it uses fallback copy instead of AI-generated copy.

## Files

- `app.py` — main Flask app
- `templates/` — web pages
- `static/styles.css` — styling
- `data/links.json` — local smart links
- `data/events.json` — local analytics events

## Important note

Localhost/127.0.0.1 only works on your Mac. To test from Instagram on your phone, deploy the app online and set `APP_BASE_URL` to your public URL.

## Production upgrades

Before launch, replace JSON storage with Supabase/Postgres, add auth, add custom domains, and deploy with Gunicorn/Render/Fly/Railway.
