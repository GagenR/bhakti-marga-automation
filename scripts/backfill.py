#!/usr/bin/env python3
"""
EENMALIG backfill-script.

Telegram's publieke preview-pagina (t.me/s/<kanaal>) toont standaard alleen
de nieuwste ~20 berichten. Dit script bladert via Telegram's
"?before=<bericht-ID>"-paginering achteruit door het kanaal, verzamelt alle
berichten vanaf CUTOFF_DATE, en verwerkt ze daarna in chronologische
volgorde (oudste eerst).
"""

import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram_to_instapaper import (
    CHANNEL,
    PREVIEW_URL,
    add_to_instapaper,
    build_title,
    fetch_messages,
    generate_page,
    load_seen_ids,
    message_number,
    save_seen_ids,
)

CUTOFF_DATE = datetime(2026, 1, 1, tzinfo=ZoneInfo("Europe/Amsterdam"))
MAX_PAGES = 200
REQUEST_DELAY_SECONDS = 1.0


def collect_messages_since_cutoff() -> list[dict]:
    all_messages: dict[str, dict] = {}
    before_id: int | None = None

    for page_num in range(1, MAX_PAGES + 1):
        url = PREVIEW_URL if before_id is None else f"{PREVIEW_URL}?before={before_id}"
        print(f"Pagina {page_num}: {url}")

        try:
            messages = fetch_messages(url)
        except Exception as exc:
            print(f"  Kon pagina niet ophalen, stoppen met paginering: {exc}", file=sys.stderr)
            break

        if not messages:
            print("  Geen berichten meer gevonden -- begin van het kanaal bereikt.")
            break

        for msg in messages:
            all_messages[msg["post_id"]] = msg

        oldest_on_page = min(
            int(message_number(m["post_id"])) for m in messages
        )

        oldest_dt = min(
            (m["posted_at"] for m in messages if m["posted_at"] is not None),
            default=None,
        )

        if oldest_dt is not None and oldest_dt < CUTOFF_DATE:
            print(f"  Oudste bericht op deze pagina ({oldest_dt:%Y-%m-%d}) ligt al "
                  f"voor de cutoff-datum -- stoppen met verder terugbladeren.")
            break

        before_id = oldest_on_page
        time.sleep(REQUEST_DELAY_SECONDS)
    else:
        print(f"WAARSCHUWING: MAX_PAGES ({MAX_PAGES}) bereikt zonder de cutoff-datum "
              f"tegen te komen -- mogelijk is niet alles opgehaald.", file=sys.stderr)

    return list(all_messages.values())


def main() -> int:
    username = os.environ.get("INSTAPAPER_USERNAME")
    password = os.environ.get("INSTAPAPER_PASSWORD")
    pages_base_url = os.environ.get("PAGES_BASE_URL", "").rstrip("/")

    if not username or not password:
        print("FOUT: INSTAPAPER_USERNAME en/of INSTAPAPER_PASSWORD ontbreken.", file=sys.stderr)
        return 1
    if not pages_base_url:
        print("FOUT: PAGES_BASE_URL ontbreekt.", file=sys.stderr)
        return 1

    print(f"Backfill voor kanaal {CHANNEL}, vanaf {CUTOFF_DATE:%Y-%m-%d}...\n")

    all_messages = collect_messages_since_cutoff()

    relevant = [
        m for m in all_messages
        if m["posted_at"] is not None and m["posted_at"] >= CUTOFF_DATE
    ]
    relevant.sort(key=lambda m: m["posted_at"])

    print(f"\n{len(relevant)} bericht(en) gevonden vanaf {CUTOFF_DATE:%Y-%m-%d}.\n")

    seen_ids = load_seen_ids()
    to_process = [m for m in relevant if m["post_id"] not in seen_ids]
    skipped = len(relevant) - len(to_process)
    if skipped:
        print(f"{skipped} bericht(en) waren al eerder verwerkt, worden overgeslagen.\n")

    if not to_process:
        print("Niets nieuws te verwerken.")
        return 0

    print(f"Versturen van {len(to_process)} bericht(en) naar Instapaper, in chronologische volgorde...\n")

    for i, msg in enumerate(to_process, start=1):
        title = build_title(msg)
        try:
            generate_page(msg)
            page_url = f"{pages_base_url}/tweets/{message_number(msg['post_id'])}.html"
            add_to_instapaper(username, password, page_url, title)
            print(f"  [{i}/{len(to_process)}] OK: {page_url}")
            seen_ids.add(msg["post_id"])
        except Exception as exc:
            print(f"  [{i}/{len(to_process)}] MISLUKT: {msg['post_id']} -> {exc}", file=sys.stderr)

        save_seen_ids(seen_ids)
        time.sleep(REQUEST_DELAY_SECONDS)

    print("\nBackfill klaar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())