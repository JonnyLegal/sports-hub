# sports-hub

Tracker for Jon's favorite teams: Ravens, Orioles, Michigan football and men's basketball, and Wake Forest football and men's basketball, and the USMNT. Each card shows the current record, the last result, and the next game, plus the live score when a game is in progress.

- `scripts/fetch_data.py` pulls from ESPN's public site API (Ravens, Michigan, Wake Forest, USMNT) and `statsapi.mlb.com` (Orioles) and writes `data.json`. It uses only the standard library.
- `scripts/calendars.py` writes `calendars/<team>.ics`, a subscribable feed of each team's full schedule with venue, TV and final scores. Event UIDs come from the source's game IDs, so a rescheduled game updates in place in calendar apps.
- `index.html` is a static page that reads `data.json`, with Subscribe, Google Calendar and .ics links for each team. It follows the Sports Hub design system: Barlow Condensed and Barlow (in `fonts/`, SIL Open Font License), square corners, and a three-tone angled card header built from each team's `colors` (`primary`, `shade`, `secondary`, `text`, `onSecondary`) and its `headerName` (one line, 20 characters at most).
  During a game it polls that game's ESPN or MLB scoreboard from the browser every 30 seconds for the live score and clock, since `data.json` only refreshes hourly. If that fails it shows the hourly score marked "as of", plus a Follow live link to the game page.
- `.github/workflows/update.yml` runs the script every hour, commits `data.json` and the calendars when they change, and deploys the site to GitHub Pages.

## Setup

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. **Actions → Update scores and deploy → Run workflow** to do the first fetch and deploy right away.

## Local

```sh
python3 scripts/fetch_data.py
python3 -m http.server   # then open http://localhost:8000
```

If one source fails, that team keeps its last good data and gets a "couldn't refresh" note. If every source fails, `data.json` is left as is and the run fails so you notice.
