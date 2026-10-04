# sports-hub

Tracker for Jon's favorite teams: Ravens, Orioles, Michigan football, and Michigan men's basketball. Each card shows the current record, the last result, and the next game, plus the live score when a game is in progress.

- `scripts/fetch_data.py` pulls from ESPN's public site API (Ravens, Michigan) and `statsapi.mlb.com` (Orioles) and writes `data.json`. It uses only the standard library.
- `index.html` is a static page that reads `data.json`.
- `.github/workflows/update.yml` runs the script every 3 hours, commits `data.json` when it changes, and deploys the site to GitHub Pages.

## Setup

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. **Actions → Update scores and deploy → Run workflow** to do the first fetch and deploy right away.

## Local

```sh
python3 scripts/fetch_data.py
python3 -m http.server   # then open http://localhost:8000
```

If one source fails, that team keeps its last good data and gets a "couldn't refresh" note. If every source fails, `data.json` is left as is and the run fails so you notice.
