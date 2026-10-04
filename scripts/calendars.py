"""Write an iCalendar (.ics) feed of a team's schedule.

Each game keeps the same UID across runs (team key + the source's game ID),
so calendar apps update an event in place when its time, TV, or result
changes. An event's DTSTAMP and SEQUENCE only move when its content does,
so the files stay byte-identical (and nothing is committed) on quiet runs.
"""

import hashlib
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PRODID = "-//sports-hub//schedule feeds//EN"
UID_DOMAIN = "sports-hub.jonnylegal.github.io"
REFRESH = "PT3H"  # matches the workflow's cron


def escape(text):
    return (
        str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    )


def fold(line):
    """Fold a content line to 75 octets per RFC 5545 §3.1, never splitting a UTF-8 character."""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > 75:
            out.append(cur)
            cur, size = " ", 1
        cur += ch
        size += n
    out.append(cur)
    return "\r\n".join(out)


def vtimezone(tzid):
    """VTIMEZONE for a US zone on the current DST rules (2nd Sun Mar to 1st Sun Nov)."""
    tz = ZoneInfo(tzid)
    year = datetime.now().year
    winter, summer = datetime(year, 1, 1, tzinfo=tz), datetime(year, 7, 1, tzinfo=tz)

    def off(dt):
        mins = int(dt.utcoffset().total_seconds() // 60)
        sign = "-" if mins < 0 else "+"
        return f"{sign}{abs(mins) // 60:02d}{abs(mins) % 60:02d}"

    std, dst = off(winter), off(summer)
    return [
        "BEGIN:VTIMEZONE",
        f"TZID:{tzid}",
        "BEGIN:DAYLIGHT",
        f"TZOFFSETFROM:{std}",
        f"TZOFFSETTO:{dst}",
        f"TZNAME:{summer.tzname()}",
        "DTSTART:20070311T020000",
        "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU",
        "END:DAYLIGHT",
        "BEGIN:STANDARD",
        f"TZOFFSETFROM:{dst}",
        f"TZOFFSETTO:{std}",
        f"TZNAME:{winter.tzname()}",
        "DTSTART:20071104T020000",
        "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]


def parse_utc(iso):
    # ESPN uses "2026-10-04T17:00Z", MLB "2026-10-04T17:00:00Z".
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


def sport_emoji(cfg):
    if cfg["source"] == "mlb":
        return "⚾"
    return "🏀" if "basketball" in cfg["path"] else "🏈"


def summary(cfg, g):
    """e.g. "🏈 ✅ Cowboys 31 at Ravens 34 [Home]" or "🏀 Wolverines at Spartans [Away]"."""
    us, them = cfg["short"], g.get("opponentShort") or g.get("opponent")
    if g["state"] == "post" and g.get("teamScore") is not None:
        us, them = f"{us} {g['teamScore']}", f"{them} {g['oppScore']}"

    if g.get("neutral"):
        matchup, where = f"{us} vs {them}", "Neutral"
    elif g.get("homeAway") == "home":
        matchup, where = f"{them} at {us}", "Home"
    else:
        matchup, where = f"{us} at {them}", "Away"

    parts = [sport_emoji(cfg)]
    if g["state"] == "post":
        mark = {"W": "✅", "L": "❌"}.get(g.get("result"))
        if mark:
            parts.append(mark)
    parts.append(f"{matchup} [{where}]")
    if g["state"] == "canceled":
        parts.append(f"({g.get('detail') or 'Canceled'})")
    return " ".join(parts)


def event_body(cfg, g):
    """All of an event's properties except UID/DTSTAMP/SEQUENCE."""
    tzid = cfg["tz"]
    start = parse_utc(g["date"])
    lines = []
    if g.get("timeTBD"):
        # No kickoff time yet: an all-day event on the local calendar date.
        day = start.astimezone(ZoneInfo("America/New_York")).date()
        lines += [f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}"]
    else:
        local = start.astimezone(ZoneInfo(tzid))
        end = local + timedelta(minutes=cfg["duration"])
        lines += [f"DTSTART;TZID={tzid}:{local:%Y%m%dT%H%M%S}", f"DTEND;TZID={tzid}:{end:%Y%m%dT%H%M%S}"]

    lines.append(f"SUMMARY:{escape(summary(cfg, g))}")
    if g.get("location") or g.get("venue"):
        lines.append(f"LOCATION:{escape(g.get('location') or g['venue'])}")

    desc = []
    if g["state"] == "post" and g.get("teamScore") is not None:
        word = {"W": "Won", "L": "Lost", "T": "Tied"}.get(g.get("result"), "Final")
        desc.append(f"Final: {word} {g['teamScore']}-{g['oppScore']}")
    if g.get("timeTBD") and g["state"] == "pre":
        desc.append("Start time TBD")
    if g.get("broadcast"):
        desc.append(f"TV: {g['broadcast']}")
    if g.get("note"):
        desc.append(g["note"])
    if g.get("venue"):
        desc.append(f"Venue: {g['venue']}" + (" (neutral site)" if g.get("neutral") else ""))
    if cfg.get("site_url"):
        desc.append(cfg["site_url"])
    if desc:
        lines.append(f"DESCRIPTION:{escape(chr(10).join(desc))}")
    if cfg.get("site_url"):
        lines.append(f"URL:{cfg['site_url']}")
    lines.append("STATUS:" + ("CANCELLED" if g["state"] == "canceled" else "CONFIRMED"))
    lines.append("TRANSP:TRANSPARENT")  # don't mark the viewer as busy
    return lines


def read_previous(path):
    """Map UID -> (hash, DTSTAMP, SEQUENCE) from an existing feed."""
    prev = {}
    if not path.exists():
        return prev
    text = re.sub(r"\r?\n[ \t]", "", path.read_text(encoding="utf-8"))  # unfold
    for block in re.findall(r"BEGIN:VEVENT\r?\n(.*?)END:VEVENT", text, re.S):
        props = dict(line.split(":", 1) for line in block.splitlines() if ":" in line)
        if "UID" in props:
            prev[props["UID"]] = (
                props.get("X-SPORTSHUB-HASH"),
                props.get("DTSTAMP"),
                int(props.get("SEQUENCE", 0)),
            )
    return prev


def write_feed(path, cfg, games):
    """Write the team's .ics feed. Returns True if the file changed."""
    prev = read_previous(path)
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    games = sorted({g["id"]: g for g in games if g.get("date")}.values(), key=lambda g: g["date"])

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape(cfg['name'])}",
        f"X-WR-CALDESC:{escape(cfg['name'] + ' schedule, scores and TV')}",
        f"X-WR-TIMEZONE:{cfg['tz']}",
        f"REFRESH-INTERVAL;VALUE=DURATION:{REFRESH}",
        f"X-PUBLISHED-TTL:{REFRESH}",
        *vtimezone(cfg["tz"]),
    ]
    for g in games:
        uid = f"{cfg['key']}-{cfg['source']}-{g['id']}@{UID_DOMAIN}"
        body = event_body(cfg, g)
        digest = hashlib.sha1("\n".join(body).encode()).hexdigest()[:16]
        old_hash, old_stamp, old_seq = prev.get(uid, (None, None, -1))
        if old_hash == digest and old_stamp:
            stamp, seq = old_stamp, old_seq
        else:
            stamp, seq = now, old_seq + 1
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{stamp}",
            f"SEQUENCE:{seq}",
            *body,
            f"X-SPORTSHUB-HASH:{digest}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")

    content = "\r\n".join(fold(line) for line in lines) + "\r\n"
    if path.exists() and path.read_bytes() == content.encode("utf-8"):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))
    return True
