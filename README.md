# Guruji Tweets naar Kobo

Haalt automatisch nieuwe berichten op uit het publieke Telegram-kanaal
`Guruji108Tweets` en stuurt ze naar Instapaper, zodat ze vanzelf op de Kobo
verschijnen zodra die wifi heeft — waar dan ook, niet gebonden aan één netwerk.

## Eenmalige setup

1. **Nieuwe GitHub-repo aanmaken**
   Maak op github.com een nieuwe (private mag) repo aan, bijv.
   `guruji-tweets-to-kobo`, en upload alle bestanden uit deze map ernaartoe
   (via de GitHub-website "upload files", of via git push vanaf je Mac).

2. **Instapaper-account**
   Zorg dat je vrouw een Instapaper-account heeft (gratis aan te maken op
   instapaper.com) en dat Instapaper gekoppeld is aan haar Kobo
   (Kobo-instellingen → Instapaper → inloggen).

3. **GitHub Secrets instellen**
   Ga in de repo naar **Settings → Secrets and variables → Actions → New
   repository secret** en voeg twee secrets toe:
   - `INSTAPAPER_USERNAME` — haar Instapaper e-mailadres
   - `INSTAPAPER_PASSWORD` — haar Instapaper-wachtwoord

   Deze staan dan veilig versleuteld opgeslagen en zijn nergens in de code
   zichtbaar.

4. **Testen**
   Ga naar de **Actions**-tab in de repo → kies de workflow "Check nieuwe
   Guruji tweets en stuur naar Instapaper" → klik **Run workflow** om hem
   handmatig één keer te starten, in plaats van 20 minuten te wachten.
   Klik op de run om de logs te bekijken: je ziet daar of berichten gevonden
   en verstuurd zijn, of een foutmelding als er iets mis is.

5. **Klaar**
   Vanaf nu draait de workflow zelf elke 20 minuten, geen server of Docker
   meer nodig. Nieuwe tweets in het Telegram-kanaal komen vanzelf in haar
   Instapaper-account, en haar Kobo haalt ze op zodra hij wifi heeft.

## Hoe het werkt

- `scripts/telegram_to_instapaper.py` haalt `https://t.me/s/Guruji108Tweets`
  op, leest de berichten uit, en stuurt nieuwe berichten via Instapaper's
  Simple API door.
- `state/seen_ids.json` onthoudt welke berichten al verstuurd zijn, zodat
  niks dubbel naar Instapaper gaat. Dit bestand wordt door de GitHub Action
  zelf bijgewerkt en teruggecommit na elke run.
- `.github/workflows/check-new-tweets.yml` is de planning: draait elke 20
  minuten automatisch, gratis binnen GitHub's free tier (2000 gratis
  minuten/maand voor private repos, dit gebruikt er slechts een handjevol
  per dag van).

## Problemen oplossen

- **"Geen berichten gevonden"** → Telegram heeft mogelijk de pagina-opmaak
  gewijzigd, of het kanaal is niet meer publiek. Check handmatig
  `https://t.me/s/Guruji108Tweets` in je browser.
- **"Ongeldige gebruikersnaam/wachtwoord"** → check de twee GitHub secrets,
  precies zoals ingevoerd op Instapaper.
- Wil je de frequentie aanpassen? Verander de `cron`-regel in het
  workflow-bestand (bijv. `*/10 * * * *` voor elke 10 minuten).
