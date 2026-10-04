#!/usr/bin/env python3
"""Fetch last result, next game, and record for each team and write data.json.

Uses ESPN's public site API for the Ravens and Michigan teams and
statsapi.mlb.com for the Orioles. Standard library only, so the GitHub
Action needs no pip install.
"""

import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data.json"
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
MLB = "https://statsapi.mlb.com/api/v1"
UA = {"User-Agent": "sports-hub/1.0 (+https://github.com/jonnylegal/sports-hub)"}

TEAMS = [
    {
        "key": "ravens",
        "name": "Baltimore Ravens",
        "short": "Ravens",
        "source": "espn",
        "path": "football/nfl",
        "id": "33",
        "colors": {"primary": "#241773", "secondary": "#9E7C0C", "text": "#FFFFFF"},
        "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/bal.png",
    },
    {
        "key": "orioles",
        "name": "Baltimore Orioles",
        "short": "Orioles",
        "source": "mlb",
        "id": 110,
        "colors": {"primary": "#DF4601", "secondary": "#000000", "text": "#FFFFFF"},
        "logo": "https://www.mlbstatic.com/team-logos/110.svg",
    },
    {
        "key": "michigan-football",
        "name": "Michigan Football",
        "short": "Wolverines",
        "source": "espn",
        "path": "football/college-football",
        "id": "130",
        "colors": {"primary": "#00274C", "secondary": "#FFCB05", "text": "#FFFFFF"},
        "logo": "https://a.espncdn.com/i/teamlogos/ncaa/500/130.png",
    },
    {
        "key": "michigan-basketball",
        "name": "Michigan Men's Basketball",
        "short": "Wolverines",
        "source": "espn",
        "path": "basketball/mens-college-basketball",
        "id": "130",
        "colors": {"primary": "#FFCB05", "secondary": "#00274C", "text": "#00274C"},
        "logo": "https://a.espncdn.com/i/teamlogos/ncaa/500/130.png",
    },
    {
        "key": "wake-forest-football",
        "name": "Wake Forest Football",
        "short": "Demon Deacons",
        "source": "espn",
        "path": "football/college-football",
        "id": "154",
        "colors": {"primary": "#000000", "secondary": "#9E7E38", "text": "#FFFFFF"},
        "logo": "https://a.espncdn.com/i/teamlogos/ncaa/500/154.png",
    },
    {
        "key": "wake-forest-basketball",
        "name": "Wake Forest Men's Basketball",
        "short": "Demon Deacons",
        "source": "espn",
        "path": "basketball/mens-college-basketball",
        "id": "154",
        "colors": {"primary": "#9E7E38", "secondary": "#000000", "text": "#000000"},
        "logo": "https://a.espncdn.com/i/teamlogos/ncaa/500/154.png",
    },
]


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def result_letter(us, them):
    if us is None or them is None:
        return None
    return "W" if us > them else "L" if us < them else "T"


# ---------------------------------------------------------------- ESPN


def espn_score(competitor):
    # The schedule endpoint returns score as {"value", "displayValue"};
    # the scoreboard endpoint returns a plain string.
    score = competitor.get("score")
    if isinstance(score, dict):
        score = score.get("value", score.get("displayValue"))
    try:
        return int(float(score))
    except (TypeError, ValueError):
        return None


def espn_game(event, team_id):
    comp = (event.get("competitions") or [{}])[0]
    competitors = comp.get("competitors") or []
    us = next((c for c in competitors if str(c.get("team", {}).get("id")) == team_id), None)
    them = next((c for c in competitors if c is not us), None)
    if not us or not them:
        return None
    status = (comp.get("status") or event.get("status") or {}).get("type", {})
    opp = them.get("team", {})
    broadcasts = comp.get("broadcasts") or []
    broadcast = None
    if broadcasts:
        b = broadcasts[0]
        broadcast = (b.get("media") or {}).get("shortName") or ", ".join(b.get("names") or []) or None
    game = {
        "id": str(event.get("id")),
        "date": comp.get("date") or event.get("date"),
        "state": status.get("state"),  # pre | in | post
        "timeTBD": comp.get("timeValid") is False,
        "detail": status.get("shortDetail") or status.get("detail"),
        "homeAway": us.get("homeAway"),
        "opponent": opp.get("displayName") or opp.get("name"),
        "opponentShort": opp.get("shortDisplayName") or opp.get("abbreviation"),
        "opponentLogo": ((opp.get("logos") or [{}])[0].get("href") or opp.get("logo")),
        "venue": (comp.get("venue") or {}).get("fullName"),
        "broadcast": broadcast,
        "neutral": bool(comp.get("neutralSite")),
        "note": ((comp.get("notes") or [{}])[0].get("headline")),
    }
    if status.get("state") in ("in", "post"):
        game["teamScore"] = espn_score(us)
        game["oppScore"] = espn_score(them)
        if status.get("state") == "post":
            game["result"] = (
                "W" if us.get("winner") else "L" if them.get("winner") else
                result_letter(game["teamScore"], game["oppScore"])
            )
    if status.get("name") in ("STATUS_POSTPONED", "STATUS_CANCELED"):
        game["state"] = "canceled"
    return game


def espn_schedule(cfg, season=None):
    events = []
    for seasontype in (2, 3):  # regular season + postseason (playoffs, bowls, tourney)
        url = f"{ESPN}/{cfg['path']}/teams/{cfg['id']}/schedule?seasontype={seasontype}"
        if season:
            url += f"&season={season}"
        try:
            data = get_json(url)
        except Exception as e:  # postseason page may 404 or be empty
            print(f"  warn: {url}: {e}", file=sys.stderr)
            continue
        events.extend(data.get("events") or [])
        season = season or (data.get("season") or {}).get("year")
    return events, season


def tally(games):
    by_id = {g["id"]: g for g in games if g["state"] == "post"}
    results = [g.get("result") for g in by_id.values()]
    w, l, t = results.count("W"), results.count("L"), results.count("T")
    if not w + l + t:
        return None
    return f"{w}-{l}-{t}" if t else f"{w}-{l}"


def season_label(cfg, year):
    # ESPN names basketball seasons by the year they end in (2026 = 2025-26).
    if "basketball" in cfg["path"]:
        return f"{year - 1}-{str(year)[-2:]}"
    return str(year)


def fetch_espn(cfg):
    team = get_json(f"{ESPN}/{cfg['path']}/teams/{cfg['id']}").get("team", {})
    record_items = (team.get("record") or {}).get("items") or []
    total = next((r for r in record_items if r.get("type") == "total"), record_items[0] if record_items else {})

    events, season = espn_schedule(cfg)
    games = [g for g in (espn_game(e, cfg["id"]) for e in events) if g]
    # Between seasons the default season may have nothing upcoming (or nothing
    # played yet), so look one season ahead/behind.
    if season and not any(g["state"] in ("pre", "in") for g in games):
        more, _ = espn_schedule(cfg, season + 1)
        games += [g for g in (espn_game(e, cfg["id"]) for e in more) if g]
    prev_games = []
    if season and not any(g["state"] == "post" for g in games):
        more, _ = espn_schedule(cfg, season - 1)
        prev_games = [g for g in (espn_game(e, cfg["id"]) for e in more) if g]
        games += prev_games

    # In the preseason ESPN reports no record at all, so fall back to last
    # season's final record, tallied from its games.
    record, record_note = total.get("summary"), None
    if not record and prev_games:
        record = tally(prev_games)
        if record:
            record_note = f"{season_label(cfg, season - 1)} final"

    return {
        "record": record,
        "recordNote": record_note,
        "standing": team.get("standingSummary"),
        "logo": ((team.get("logos") or [{}])[0].get("href")),
        "games": games,
    }


# ---------------------------------------------------------------- MLB


def mlb_game(g, team_id):
    side = "home" if g["teams"]["home"]["team"]["id"] == team_id else "away"
    other = "away" if side == "home" else "home"
    us, them = g["teams"][side], g["teams"][other]
    abstract = g.get("status", {}).get("abstractGameState")  # Preview | Live | Final
    detailed = g.get("status", {}).get("detailedState")
    state = {"Preview": "pre", "Live": "in", "Final": "post"}.get(abstract, "pre")
    if detailed in ("Postponed", "Cancelled", "Suspended"):
        state = "canceled"
    opp = them["team"]
    game = {
        "id": str(g["gamePk"]),
        "date": g.get("gameDate"),
        "timeTBD": (g.get("status") or {}).get("startTimeTBD", False),
        "state": state,
        "detail": detailed,
        "homeAway": side,
        "opponent": opp.get("name"),
        "opponentShort": opp.get("teamName") or opp.get("abbreviation"),
        "opponentLogo": f"https://www.mlbstatic.com/team-logos/{opp['id']}.svg",
        "venue": (g.get("venue") or {}).get("name"),
        "broadcast": None,
        "neutral": False,
        "note": g.get("seriesDescription") if g.get("gameType") not in ("R", None) else None,
    }
    tv = [b.get("name") for b in g.get("broadcasts") or [] if b.get("type") == "TV"]
    if tv:
        game["broadcast"] = ", ".join(dict.fromkeys(tv))
    if state in ("in", "post"):
        game["teamScore"] = us.get("score")
        game["oppScore"] = them.get("score")
        if state == "in":
            ls = g.get("linescore") or {}
            if ls.get("currentInningOrdinal"):
                game["detail"] = f"{ls.get('inningHalf', '')} {ls['currentInningOrdinal']}".strip()
        else:
            game["result"] = (
                "W" if us.get("isWinner") else "L" if them.get("isWinner") else
                result_letter(game["teamScore"], game["oppScore"])
            )
    return game


def fetch_mlb(cfg):
    today = datetime.now(timezone.utc).date()
    start, end = today - timedelta(days=200), today + timedelta(days=200)
    sched = get_json(
        f"{MLB}/schedule?sportId=1&teamId={cfg['id']}"
        f"&startDate={start}&endDate={end}&hydrate=team,linescore,broadcasts(all)"
    )
    games = [mlb_game(g, cfg["id"]) for d in sched.get("dates", []) for g in d.get("games", [])]
    # Spring training games aren't worth calling a "last result".
    games = [g for g in games if not (g["state"] == "post" and g["note"] == "Spring Training")]

    record = standing = None
    for season in (today.year, today.year - 1):
        standings = get_json(f"{MLB}/standings?leagueId=103,104&season={season}&standingsTypes=regularSeason")
        for div in standings.get("records", []):
            for tr in div.get("teamRecords", []):
                if tr["team"]["id"] == cfg["id"]:
                    record = f"{tr['wins']}-{tr['losses']}"
                    rank, gb = tr.get("divisionRank"), tr.get("divisionGamesBack")
                    if rank:
                        standing = f"{ordinal(int(rank))} in AL East"
                        if gb and gb != "-":
                            standing += f" ({gb} GB)"
        if record:
            break
    return {"record": record, "recordNote": None, "standing": standing, "logo": None, "games": games}


def ordinal(n):
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ---------------------------------------------------------------- main


def pick_games(games):
    games = sorted({g["id"]: g for g in games}.values(), key=lambda g: g["date"] or "")
    live = next((g for g in games if g["state"] == "in"), None)
    last = next((g for g in reversed(games) if g["state"] == "post"), None)
    nxt = next((g for g in games if g["state"] == "pre"), None)
    return live, last, nxt


def build_team(cfg, previous):
    base = {k: cfg[k] for k in ("key", "name", "short", "colors", "logo")}
    try:
        print(f"Fetching {cfg['name']}...", file=sys.stderr)
        raw = fetch_espn(cfg) if cfg["source"] == "espn" else fetch_mlb(cfg)
        live, last, nxt = pick_games(raw["games"])
        return {
            **base,
            "logo": raw["logo"] or cfg["logo"],
            "record": raw["record"],
            "recordNote": raw["recordNote"],
            "standing": raw["standing"],
            "live": live,
            "last": last,
            "next": nxt,
        }
    except Exception as e:
        # Keep the last good data rather than blanking the card.
        print(f"  error: {cfg['name']}: {e}", file=sys.stderr)
        if previous:
            return {**previous, "stale": True}
        return {**base, "record": None, "standing": None, "live": None, "last": None, "next": None, "error": str(e)}


def main():
    old = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text())
        except ValueError:
            pass
    prev_teams = {t["key"]: t for t in old.get("teams", [])}

    teams = [build_team(cfg, prev_teams.get(cfg["key"])) for cfg in TEAMS]
    if all(t.get("stale") or t.get("error") for t in teams):
        print("All sources failed; leaving data.json unchanged.", file=sys.stderr)
        return 1

    if teams == old.get("teams"):
        print("No changes.", file=sys.stderr)
        return 0
    data = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "teams": teams}
    OUT.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Wrote {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
