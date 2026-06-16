#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coup d'envoi — collecteur de données.

Agrège plusieurs sources d'horaires sportifs en UN seul fichier matches.json,
normalisé, servi ensuite par la PWA (même origine -> zéro CORS).

Sources :
  - Football  : openfootball (domaine public, JSON brut GitHub, sans clé)
                -> Coupe du monde + Euro
  - Rugby     : TheSportsDB V1 (clé gratuite "123"), récupéré côté serveur ici
                -> Tournoi des VI Nations + Top 14
  - Tennis    : TheSportsDB V1, best-effort (couverture incertaine assumée)

Tout est exécuté dans une GitHub Action : aucune clé sensible, aucune
dépendance externe (stdlib uniquement).
"""

import json, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

TIMEOUT = 25
UA = {"User-Agent": "coup-denvoi/1.0 (+github action)"}

# ---------------------------------------------------------------- HTTP
def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))

# ---------------------------------------------------------------- helpers temps
def iso_z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def parse_openfootball_time(date, t):
    """ '13:00 UTC-6' -> ('2026-06-11T19:00:00Z', tbd=False). Sans heure -> (None, True)."""
    if not t:
        return None, True
    m = re.match(r"\s*(\d{1,2}):(\d{2})\s*UTC([+-]\d{1,2})", t)
    y, mo, d = (int(x) for x in date.split("-"))
    if not m:
        m2 = re.match(r"\s*(\d{1,2}):(\d{2})", t)  # heure sans fuseau -> traitée comme UTC
        if not m2:
            return None, True
        hh, mm = int(m2.group(1)), int(m2.group(2))
        return iso_z(datetime(y, mo, d, hh, mm, tzinfo=timezone.utc)), False
    hh, mm, off = int(m.group(1)), int(m.group(2)), int(m.group(3))
    local = datetime(y, mo, d, hh, mm, tzinfo=timezone(timedelta(hours=off)))
    return iso_z(local), False

def parse_tsdb_time(ev):
    ts = ev.get("strTimestamp")
    if ts:
        ts = ts.replace(" ", "T").replace("Z", "").split("+")[0]
        try:
            return iso_z(datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)), False
        except ValueError:
            pass
    d, t = ev.get("dateEvent"), ev.get("strTime")
    if d and t and t != "00:00:00":
        try:
            return iso_z(datetime.fromisoformat(f"{d}T{t}").replace(tzinfo=timezone.utc)), False
        except ValueError:
            pass
    if d:
        return None, True
    return None, True

def slug(*parts):
    s = "-".join(str(p) for p in parts if p)
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:80]

# ---------------------------------------------------------------- football (openfootball)
OPENFOOTBALL = [
    ("Coupe du monde 2026", "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"),
    ("Euro 2028",           "https://raw.githubusercontent.com/openfootball/euro.json/master/2028/euro.json"),
]

def collect_openfootball(name, url):
    data = get_json(url)
    out = []
    for m in data.get("matches", []):
        date = m.get("date")
        if not date:
            continue
        start, tbd = parse_openfootball_time(date, m.get("time"))
        ft = (m.get("score") or {}).get("ft")
        score = f"{ft[0]}\u2013{ft[1]}" if ft and len(ft) == 2 else None
        h, a = m.get("team1"), m.get("team2")
        out.append({
            "id": slug(name, date, h, a),
            "sport": "Football",
            "competition": name,
            "date": date,
            "start": start,
            "tbd": tbd,
            "home": h, "away": a,
            "score": score,
            "status": "finished" if score else "scheduled",
            "group": m.get("group") or m.get("round"),
            "venue": m.get("ground"),
        })
    return out

# ---------------------------------------------------------------- TheSportsDB
TSDB = "https://www.thesportsdb.com/api/v1/json/123"

def season_guesses():
    now = datetime.now(timezone.utc)
    y, mth = now.year, now.month
    s = y if mth >= 7 else y - 1
    return [f"{s}-{s+1}", f"{y}", f"{y}-{y+1}"]

_league_cache = None
def tsdb_all_leagues():
    global _league_cache
    if _league_cache is None:
        _league_cache = get_json(f"{TSDB}/all_leagues.php").get("leagues") or []
    return _league_cache

def resolve_league(substr, sport):
    for l in tsdb_all_leagues():
        nm = (l.get("strLeague") or "")
        if substr.lower() in nm.lower() and (l.get("strSport") == sport):
            return l.get("idLeague"), nm
    return None, None

def tsdb_events(idl):
    try:
        evs = get_json(f"{TSDB}/eventsnextleague.php?id={idl}").get("events") or []
        if evs:
            return evs
    except Exception:
        pass
    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    for s in season_guesses():
        try:
            evs = get_json(f"{TSDB}/eventsseason.php?id={idl}&s={s}").get("events") or []
        except Exception:
            evs = []
        upcoming = []
        for e in evs:
            iso, _ = parse_tsdb_time(e)
            if iso and datetime.fromisoformat(iso.replace("Z", "+00:00")) > cutoff:
                upcoming.append(e)
        if upcoming:
            return upcoming
        time.sleep(0.4)  # respect du rate limit
    return []

def collect_tsdb(name, substr, sport):
    idl, real = resolve_league(substr, sport)
    if not idl:
        raise RuntimeError(f"ligue introuvable ({substr}/{sport})")
    out = []
    for e in tsdb_events(idl):
        start, tbd = parse_tsdb_time(e)
        h = e.get("strHomeTeam") or e.get("strEvent")
        a = e.get("strAwayTeam")
        hs, as_ = e.get("intHomeScore"), e.get("intAwayScore")
        score = f"{hs}\u2013{as_}" if hs not in (None, "") and as_ not in (None, "") else None
        out.append({
            "id": slug(name, e.get("idEvent")),
            "sport": sport,
            "competition": real or name,
            "date": e.get("dateEvent"),
            "start": start,
            "tbd": tbd,
            "home": h, "away": a,
            "score": score,
            "status": "finished" if score else "scheduled",
            "group": e.get("strRound") or None,
            "venue": e.get("strVenue") or None,
        })
        time.sleep(0.4)
    return out

TSDB_SOURCES = [
    ("Tournoi des VI Nations", "Six Nations",   "Rugby"),
    ("Top 14",                 "French Top 14", "Rugby"),
]

# ---------------------------------------------------------------- main
def main():
    matches, sources = [], []

    for name, url in OPENFOOTBALL:
        try:
            rows = collect_openfootball(name, url)
            matches += rows
            sources.append({"name": name, "sport": "Football", "ok": True, "count": len(rows)})
            print(f"[ok] {name}: {len(rows)} matchs")
        except Exception as e:
            sources.append({"name": name, "sport": "Football", "ok": False, "error": str(e)})
            print(f"[!!] {name}: {e}", file=sys.stderr)

    for name, substr, sport in TSDB_SOURCES:
        try:
            rows = collect_tsdb(name, substr, sport)
            matches += rows
            sources.append({"name": name, "sport": sport, "ok": True, "count": len(rows)})
            print(f"[ok] {name}: {len(rows)} matchs")
        except Exception as e:
            sources.append({"name": name, "sport": sport, "ok": False, "error": str(e)})
            print(f"[!!] {name}: {e}", file=sys.stderr)

    # dédoublonnage + tri (sans date en dernier)
    seen, uniq = set(), []
    for m in matches:
        if m["id"] in seen:
            continue
        seen.add(m["id"]); uniq.append(m)
    uniq.sort(key=lambda m: (m.get("start") or (m.get("date", "9999") + "T99")))

    out = {
        "generated": iso_z(datetime.now(timezone.utc)),
        "sources": sources,
        "count": len(uniq),
        "matches": uniq,
    }
    with open("matches.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nTotal: {len(uniq)} matchs -> matches.json")

if __name__ == "__main__":
    main()
