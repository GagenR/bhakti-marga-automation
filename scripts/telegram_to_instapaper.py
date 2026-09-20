#!/usr/bin/env python3
"""
Leest het publieke Telegram-kanaal Guruji108Tweets uit, genereert voor elk
nieuw bericht een eigen nette, leesbare HTML-pagina (inclusief foto, als die
er is), publiceert die via GitHub Pages, en stuurt die schone link door naar
Instapaper -- zodat op de Kobo alleen de tweet zelf te zien is, niet Telegram's
eigen rommelige "Download / Context / View in Channel"-pagina.

Werking:
1. Haalt de publieke preview-pagina op: https://t.me/s/<KANAAL>
2. Parseert alle berichten: tekst, eventuele foto, en unieke post-ID
   (bv. "Guruji108Tweets/1448")
3. Vergelijkt met seen_ids.json (bijgehouden in de repo) om te weten wat al
   verwerkt is
4. Voor elk nieuw bericht:
   a. Genereert een eigen HTML-pagina onder docs/tweets/<id>.html
   b. Stuurt de bijbehorende GitHub Pages-URL naar Instapaper
5. Schrijft seen_ids.json bij, zodat de volgende run niet dubbel stuurt

Benodigde environment variables (worden in GitHub Actions als secrets
aangeleverd):
- INSTAPAPER_USERNAME
- INSTAPAPER_PASSWORD
- PAGES_BASE_URL (bv. "https://gagenr.github.io/bhakti-marga-automation")
"""

import html
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# Telegram geeft tijden in UTC; we tonen ze in Nederlandse tijd, zodat de
# datum/tijd in de titel overeenkomt met wanneer Guruji 'm daadwerkelijk
# (lokaal gezien) postte.
LOCAL_TZ = ZoneInfo("Europe/Amsterdam")

CHANNEL = "Guruji108Tweets"
PREVIEW_URL = f"https://t.me/s/{CHANNEL}"
INSTAPAPER_ADD_URL = "https://www.instapaper.com/api/add"

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / "state" / "seen_ids.json"
PAGES_DIR = REPO_ROOT / "docs" / "tweets"

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Guruji — Bhakti Marga</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg: #ffffff;
    --text: #1a1a1a;
    --muted: #666666;
    --accent: #8a4b2f;
    --border: #e5e0da;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #111111;
      --text: #eaeaea;
      --muted: #999999;
      --accent: #c98a5e;
      --border: #333333;
    }}
  }}
  html, body {{
    margin: 0;
    padding: 0;
    background: var(--bg);
    color: var(--text);
  }}
  body {{
    font-family: Georgia, "Times New Roman", serif;
    line-height: 1.6;
    max-width: 40em;
    margin: 0 auto;
    padding: 2em 1.2em 3em;
  }}
  .label {{
    font-family: -apple-system, Helvetica, Arial, sans-serif;
    font-size: 0.75em;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--accent);
    margin-bottom: 0.3em;
  }}
  h1 {{
    font-family: -apple-system, Helvetica, Arial, sans-serif;
    font-size: 1.3em;
    margin: 0 0 0.4em;
  }}
  .posted-at {{
    font-family: -apple-system, Helvetica, Arial, sans-serif;
    font-size: 0.85em;
    color: var(--muted);
    margin: 0 0 1.2em;
    padding-bottom: 0.8em;
    border-bottom: 1px solid var(--border);
  }}
  .tweet-photo {{
    width: 100%;
    height: auto;
    border-radius: 6px;
    margin: 0 0 1.5em;
    display: block;
  }}
  .tweet-text {{
    font-size: 1.25em;
    white-space: pre-wrap;
    margin: 0 0 2em;
  }}
  .meta {{
    font-family: -apple-system, Helvetica, Arial, sans-serif;
    font-size: 0.85em;
    color: var(--muted);
    border-top: 1px solid var(--border);
    padding-top: 1em;
  }}
  .meta a {{
    color: var(--accent);
    text-decoration: none;
  }}
</style>
</head>
<body>
  <div class="label">Bhakti Marga · Guruji's Tweets</div>
  <h1>Paramahamsa Sri Swami Vishwananda</h1>
  <div class="posted-at">{posted_at_html}</div>
{photo_html}
  <div class="tweet-text">{text_html}</div>

  <div class="meta">
    <a href="{original_url}">Bekijk origineel bericht in Telegram →</a>
  </div>
</body>
</html>
"""


def load_seen_ids() -> set[str]:
    if not STATE_FILE.exists():
        return set()
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return set(data)
    except (json.JSONDecodeError, OSError):
        return set()


def save_seen_ids(seen_ids: set[str]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    trimmed = sorted(seen_ids)[-500:]
    STATE_FILE.write_text(json.dumps(trimmed, indent=2), encoding="utf-8")


def extract_timestamp(msg_div) -> datetime | None:
    """Telegram zet de exacte posttijd in een <time datetime="..."> element
    binnen de datum-link van elk bericht. Geeft een timezone-aware datetime
    terug in Nederlandse tijd, of None als het niet te vinden is."""
    time_tag = msg_div.select_one(".tgme_widget_message_date time")
    if not time_tag or not time_tag.get("datetime"):
        return None

    raw = time_tag["datetime"]
    try:
        dt_utc = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None

    return dt_utc.astimezone(LOCAL_TZ)


def extract_photo_url(msg_div) -> str | None:
    """Telegram's preview-pagina zet foto's als achtergrond-afbeelding in een
    <a class="tgme_widget_message_photo_wrap" style="background-image:url('...')">.
    Deze functie pakt die URL eruit, als die er is."""
    photo_wrap = msg_div.select_one(".tgme_widget_message_photo_wrap")
    if not photo_wrap:
        return None

    style = photo_wrap.get("style", "")
    match = re.search(r"background-image:\s*url\(['\"]?(.*?)['\"]?\)", style)
    return match.group(1) if match else None


def fetch_messages() -> list[dict]:
    """Haalt de publieke Telegram-preview op en geeft een lijst berichten terug,
    elk als dict met 'post_id', 'source_url', 'text' en 'photo_url' (of None)."""
    resp = requests.get(PREVIEW_URL, timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (compatible; GurujiTweetsBot/1.0)"
    })
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    messages = []

    for msg_div in soup.select("div.tgme_widget_message"):
        post_id = msg_div.get("data-post")
        if not post_id:
            continue

        text_div = msg_div.select_one(".tgme_widget_message_text")
        text = text_div.get_text(separator="\n").strip() if text_div else ""
        photo_url = extract_photo_url(msg_div)
        posted_at = extract_timestamp(msg_div)

        # Sommige berichten zijn puur een foto zonder onderschrift -- geef
        # die dan een simpele placeholder-titel/tekst zodat de pagina niet
        # helemaal leeg oogt.
        if not text and photo_url:
            text = "(Foto van Guruji)"

        messages.append({
            "post_id": post_id,
            "source_url": f"https://t.me/s/{post_id}",
            "text": text,
            "photo_url": photo_url,
            "posted_at": posted_at,
        })

    return messages


def message_number(post_id: str) -> str:
    """'Guruji108Tweets/1448' -> '1448' -- gebruikt als bestandsnaam."""
    return post_id.rsplit("/", 1)[-1]


def format_datetime_nl(dt: datetime) -> str:
    """bv. 'zaterdag 20 september 2026, 14:32'"""
    dagen = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
    maanden = ["januari", "februari", "maart", "april", "mei", "juni", "juli",
               "augustus", "september", "oktober", "november", "december"]
    dag_naam = dagen[dt.weekday()]
    maand_naam = maanden[dt.month - 1]
    return f"{dag_naam} {dt.day} {maand_naam} {dt.year}, {dt:%H:%M}"


def generate_page(msg: dict) -> Path:
    """Genereert de HTML-pagina voor één bericht en schrijft die weg onder
    docs/tweets/<id>.html. Geeft het pad terug."""
    PAGES_DIR.mkdir(parents=True, exist_ok=True)

    photo_html = ""
    if msg["photo_url"]:
        photo_html = f'  <img class="tweet-photo" src="{html.escape(msg["photo_url"])}" alt="">\n'

    posted_at_html = format_datetime_nl(msg["posted_at"]) if msg["posted_at"] else ""

    page_html = PAGE_TEMPLATE.format(
        photo_html=photo_html,
        posted_at_html=html.escape(posted_at_html),
        text_html=html.escape(msg["text"]).replace("\n", "<br>"),
        original_url=html.escape(msg["source_url"]),
    )

    file_path = PAGES_DIR / f"{message_number(msg['post_id'])}.html"
    file_path.write_text(page_html, encoding="utf-8")
    return file_path


def build_title(msg: dict) -> str:
    """Bouwt de titel die in Instapaper/op de Kobo getoond wordt. Begint met
    datum + tijd (JJJJ-MM-DD HH:MM) zodat items chronologisch sorteren en in
    één oogopslag te zien is wat de nieuwste tweet is, gevolgd door de eerste
    regel van de tweet zelf."""
    first_line = (msg["text"].splitlines()[0] if msg["text"] else "Guruji tweet") or "Guruji tweet"
    if msg["posted_at"]:
        date_prefix = msg["posted_at"].strftime("%Y-%m-%d %H:%M")
        return f"{date_prefix} — {first_line}"
    return first_line


def add_to_instapaper(username: str, password: str, url: str, title: str) -> None:
    """Stuurt één URL naar Instapaper via de Simple API."""
    resp = requests.post(
        INSTAPAPER_ADD_URL,
        auth=(username, password),
        data={"url": url, "title": title[:200] if title else ""},
        timeout=30,
    )

    if resp.status_code == 201:
        return
    if resp.status_code == 400:
        raise RuntimeError("Instapaper: ongeldig verzoek of rate limit bereikt")
    if resp.status_code == 403:
        raise RuntimeError(
            "Instapaper: ongeldige gebruikersnaam/wachtwoord "
            "(check de GitHub secrets INSTAPAPER_USERNAME / INSTAPAPER_PASSWORD)"
        )
    resp.raise_for_status()


def main() -> int:
    username = os.environ.get("INSTAPAPER_USERNAME")
    password = os.environ.get("INSTAPAPER_PASSWORD")
    pages_base_url = os.environ.get("PAGES_BASE_URL", "").rstrip("/")

    if not username or not password:
        print("FOUT: INSTAPAPER_USERNAME en/of INSTAPAPER_PASSWORD ontbreken.", file=sys.stderr)
        return 1
    if not pages_base_url:
        print("FOUT: PAGES_BASE_URL ontbreekt (bv. https://gagenr.github.io/bhakti-marga-automation).", file=sys.stderr)
        return 1

    seen_ids = load_seen_ids()
    messages = fetch_messages()

    if not messages:
        print("Geen berichten gevonden op de Telegram-preview-pagina — "
              "kanaalnaam of pagina-opmaak gewijzigd?")
        return 0

    new_messages = [m for m in messages if m["post_id"] not in seen_ids]

    if not new_messages:
        print("Geen nieuwe berichten sinds de vorige run.")
        return 0

    print(f"{len(new_messages)} nieuw(e) bericht(en) gevonden, versturen naar Instapaper...")

    for msg in new_messages:
        title = build_title(msg)
        try:
            generate_page(msg)
            page_url = f"{pages_base_url}/tweets/{message_number(msg['post_id'])}.html"
            add_to_instapaper(username, password, page_url, title)
            print(f"  OK: {page_url}")
            seen_ids.add(msg["post_id"])
        except Exception as exc:
            print(f"  MISLUKT: {msg['post_id']} -> {exc}", file=sys.stderr)

    save_seen_ids(seen_ids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
