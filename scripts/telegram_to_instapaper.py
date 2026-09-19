#!/usr/bin/env python3
"""
Leest het publieke Telegram-kanaal Guruji108Tweets uit en stuurt nieuwe
berichten door naar Instapaper, zodat ze automatisch op de Kobo verschijnen
(via Instapaper-sync) zonder dat er iets handmatig hoeft te gebeuren.

Werking:
1. Haalt de publieke preview-pagina op: https://t.me/s/<KANAAL>
2. Parseert alle berichten en hun unieke post-ID (bv. "Guruji108Tweets/4821")
3. Vergelijkt met seen_ids.json (bijgehouden in de repo) om te weten wat al
   verwerkt is
4. Voor elk nieuw bericht: POST naar Instapaper's Simple API
5. Schrijft seen_ids.json bij, zodat de volgende run niet dubbel stuurt

Benodigde environment variables (worden in GitHub Actions als secrets
aangeleverd):
- INSTAPAPER_USERNAME
- INSTAPAPER_PASSWORD
"""

import json
import os
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

CHANNEL = "Guruji108Tweets"
PREVIEW_URL = f"https://t.me/s/{CHANNEL}"
INSTAPAPER_ADD_URL = "https://www.instapaper.com/api/add"

# Pad naar het bestand dat bijhoudt welke berichten al verwerkt zijn.
# Dit bestand staat in de repo zelf en wordt door de GitHub Action
# na elke run automatisch weer gecommit.
STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "seen_ids.json"


def load_seen_ids() -> set[str]:
    if not STATE_FILE.exists():
        return set()
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return set(data)
    except (json.JSONDecodeError, OSError):
        # Corrupt of leeg bestand: begin gewoon opnieuw i.p.v. te crashen.
        return set()


def save_seen_ids(seen_ids: set[str]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Bewaar alleen de laatste 500 om het bestand niet oneindig te laten groeien.
    trimmed = sorted(seen_ids)[-500:]
    STATE_FILE.write_text(json.dumps(trimmed, indent=2), encoding="utf-8")


def fetch_messages() -> list[dict]:
    """Haalt de publieke Telegram-preview op en geeft een lijst berichten terug,
    elk als dict met 'post_id', 'url' en 'text'."""
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

        messages.append({
            "post_id": post_id,
            "url": f"https://t.me/{post_id}",
            "text": text,
        })

    return messages


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

    if not username or not password:
        print("FOUT: INSTAPAPER_USERNAME en/of INSTAPAPER_PASSWORD ontbreken.", file=sys.stderr)
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
        title = (msg["text"].splitlines()[0] if msg["text"] else "Guruji tweet") or "Guruji tweet"
        try:
            add_to_instapaper(username, password, msg["url"], title)
            print(f"  OK: {msg['url']}")
            seen_ids.add(msg["post_id"])
        except Exception as exc:
            # Eén mislukt bericht mag de rest niet blokkeren; probeer het
            # gewoon bij de volgende run opnieuw (post_id wordt niet
            # toegevoegd aan seen_ids).
            print(f"  MISLUKT: {msg['url']} -> {exc}", file=sys.stderr)

    save_seen_ids(seen_ids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
