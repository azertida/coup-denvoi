#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coup d'envoi — collecteur de données.

Agrège plusieurs sources d'horaires sportifs en UN seul fichier matches.json,
normalisé, servi ensuite par la PWA (même origine -> zéro CORS).

Sources :
  - Football  : openfootball (domaine public, JSON brut GitHub, sans clé)
                -> Coupe du monde + Euro
  - Rugby     : Top 14 via scraping top14.lnr.fr (site officiel LNR)
                Tournoi des VI Nations via API Wikipedia (wikicode parsé)

Tout est exécuté dans une GitHub Action : aucune clé sensible, dépendances
minimales (beautifulsoup4 + lxml pour le scraping LNR).
"""

import json, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

TIMEOUT = 30
UA = {"User-Agent": "coup-denvoi/1.0 (+github action; ana@connectes.be)"}

# ---------------------------------------------------------------- HTTP
def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))

def get_text(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8")

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

def slug(*parts):
    s = "-".join(str(p) for p in parts if p)
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:80]

MOIS_FR = {
    "janvier": 1, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
}

def combine_date_time_paris(date_iso, time_str):
    """
    Convertit une date ISO (2026-06-27) + horaire local Paris ("21:05")
    en datetime UTC ISO. Si l'heure est absente, renvoie None.
    """
    if not date_iso or not time_str:
        return None
    try:
        y, mo, d = (int(x) for x in date_iso.split("-"))
        hh, mm = (int(x) for x in time_str.split(":"))
        # Paris/Bruxelles : CET (UTC+1) hiver, CEST (UTC+2) été.
        # Approximation : DST de fin mars à fin octobre.
        is_dst = 3 < mo < 10 or (mo == 3 and d >= 28) or (mo == 10 and d < 28)
        offset_hours = 2 if is_dst else 1
        local = datetime(y, mo, d, hh, mm, tzinfo=timezone(timedelta(hours=offset_hours)))
        return iso_z(local)
    except Exception:
        return None

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

# ---------------------------------------------------------------- rugby Top 14 (LNR)
LNR_BASE = "https://top14.lnr.fr/calendrier-et-resultats"

def parse_french_date(date_fr, season_start_year):
    """Convertit 'samedi 30 mai' en date ISO en s'appuyant sur l'année de début de saison."""
    if not date_fr:
        return None
    parts = date_fr.lower().strip().split()
    if len(parts) < 3:
        return None
    try:
        day = int(parts[-2])
        month_name = parts[-1]
        month = MOIS_FR.get(month_name)
        if not month:
            return None
        # Saison X-Y : août-déc en X, jan-juil en Y
        year = season_start_year if month >= 8 else season_start_year + 1
        return f"{year:04d}-{month:02d}-{day:02d}"
    except (ValueError, IndexError):
        return None

def _lnr_parse_page(html, phase_label, season_start_year):
    """Parse une page LNR et renvoie une liste de matchs normalisés."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    container = soup.select_one(".page-builder-fixtures")
    if not container:
        return []
    
    matches = []
    current_date_iso = None
    
    for elem in container.find_all("div"):
        classes = elem.get("class") or []
        
        if "calendar-results__fixture-date" in classes:
            current_date_iso = parse_french_date(elem.get_text(strip=True), season_start_year)
            continue
        
        if "match-line" in classes and "match-line__wrapper" not in classes:
            clubs = elem.select(".club-line__name")
            if len(clubs) != 2:
                continue
            home = clubs[0].get_text(strip=True)
            away = clubs[1].get_text(strip=True)
            
            score_elem = elem.select_one(".match-line__score")
            raw = score_elem.get_text(strip=True) if score_elem else ""
            
            score = None
            time_str = None
            m = re.match(r"^(\d+)\s*-\s*(\d+)$", raw)
            if m:
                score = f"{m.group(1)}\u2013{m.group(2)}"
            else:
                m = re.match(r"^(\d{1,2})h(\d{2})$", raw)
                if m:
                    time_str = f"{int(m.group(1)):02d}:{m.group(2)}"
            
            matches.append({
                "phase": phase_label,
                "date": current_date_iso,
                "time_local": time_str,
                "home": home,
                "away": away,
                "score": score,
            })
    return matches

def collect_top14(season="2025-2026"):
    """Scrape toutes les phases du Top 14 (26 journées + barrage + demi-finale + finale)."""
    season_start = int(season.split("-")[0])
    phases = [(f"J{n}", f"j{n}") for n in range(1, 27)]
    phases += [
        ("Barrage", "barrage"),
        ("Demi-finale", "demi-finale"),
        ("Finale", "finale"),
    ]
    
    out = []
    for phase_label, slug_phase in phases:
        url = f"{LNR_BASE}/{season}/{slug_phase}"
        try:
            html = get_text(url)
        except Exception as e:
            print(f"  [!!] LNR {phase_label} : {e}", file=sys.stderr)
            continue
        
        for m in _lnr_parse_page(html, phase_label, season_start):
            start_utc = combine_date_time_paris(m["date"], m["time_local"]) if m["time_local"] else None
            out.append({
                "id": slug("top-14", m["date"], m["home"], m["away"]),
                "sport": "Rugby",
                "competition": "Top 14",
                "date": m["date"],
                "start": start_utc,
                "tbd": start_utc is None and m["score"] is None,
                "home": m["home"],
                "away": m["away"],
                "score": m["score"],
                "status": "finished" if m["score"] else "scheduled",
                "group": m["phase"],
                "venue": None,
            })
        time.sleep(0.5)
    
    return out

# ---------------------------------------------------------------- rugby Six Nations (Wikipedia)
WIKI_API = "https://fr.wikipedia.org/w/api.php"

JOURNEES_6N = [
    ("Première journée", "J1"),
    ("Deuxième journée", "J2"),
    ("Troisième journée", "J3"),
    ("Quatrième journée", "J4"),
    ("Cinquième journée", "J5"),
]

def _wiki_parse_date(text):
    if not text:
        return None
    m = re.search(r"\{\{date\|([^}|]+)", text)
    if m:
        text = m.group(1)
    text = text.strip().lower()
    m = re.match(r"(\d{1,2})\s+(\w+)\s+(\d{4})", text)
    if m:
        day = int(m.group(1))
        month = MOIS_FR.get(m.group(2))
        year = int(m.group(3))
        if month:
            return f"{year:04d}-{month:02d}-{day:02d}"
    return None

def _wiki_parse_heure(text):
    if not text:
        return None
    m = re.search(r"\{\{heure\|(\d{1,2})\|(\d{2})", text)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    m = re.match(r"\s*(\d{1,2})[h:](\d{2})", text)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return None

def _wiki_parse_team(text):
    if not text:
        return None
    text = text.replace("'''", "")
    m = re.search(r"\{\{([A-Za-zÀ-ÿ\s\-]+?)\s+rugby\s*[|}]", text)
    if m:
        return m.group(1).strip()
    m = re.search(r"\[\[(?:Équipe d['e]\s+)?([^\]|]+?)(?:\s+de rugby[^]]*)?(?:\|[^\]]*)?\]\]", text)
    if m:
        return m.group(1).strip()
    text = re.sub(r"\{\{[^}]+\}\}", "", text)
    text = re.sub(r"\[\[[^]]+\]\]", "", text)
    return text.strip() or None

def _wiki_parse_score(text):
    if not text:
        return None
    text = text.replace("'''", "").strip()
    m = re.match(r"^\s*(\d+)\s*[-\u2013]\s*(\d+)", text)
    if m:
        return f"{m.group(1)}\u2013{m.group(2)}"
    return None

def _wiki_parse_lieu(text):
    if not text:
        return None
    m = re.search(r"\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]", text)
    if m:
        return m.group(1).strip()
    return text.strip() or None

def _wiki_parse_match_template(body):
    """Parse les champs d'un modèle {{Match rugby | ... }}."""
    if body.startswith("{{"):
        body = body[2:]
    if body.endswith("}}"):
        body = body[:-2]
    
    parts, current = [], []
    depth_braces = depth_brackets = 0
    i = 0
    while i < len(body):
        c, nxt = body[i], body[i+1] if i+1 < len(body) else ""
        if c == "{" and nxt == "{":
            depth_braces += 1; current.append(c); current.append(nxt); i += 2; continue
        if c == "}" and nxt == "}":
            depth_braces -= 1; current.append(c); current.append(nxt); i += 2; continue
        if c == "[" and nxt == "[":
            depth_brackets += 1; current.append(c); current.append(nxt); i += 2; continue
        if c == "]" and nxt == "]":
            depth_brackets -= 1; current.append(c); current.append(nxt); i += 2; continue
        if c == "|" and depth_braces == 0 and depth_brackets == 0:
            parts.append("".join(current)); current = []; i += 1; continue
        current.append(c); i += 1
    if current:
        parts.append("".join(current))
    
    fields = {}
    for part in parts[1:]:
        if "=" in part:
            k, _, v = part.partition("=")
            fields[k.strip().lower()] = v.strip()
    
    return {
        "date": _wiki_parse_date(fields.get("date", "")),
        "time_local": _wiki_parse_heure(fields.get("heure", "")),
        "home": _wiki_parse_team(fields.get("équipe1", "")),
        "away": _wiki_parse_team(fields.get("équipe2", "")),
        "score": _wiki_parse_score(fields.get("score", "")),
        "venue": _wiki_parse_lieu(fields.get("lieu", "")),
    }

def _wiki_extract_templates(wikitext):
    """Trouve tous les blocs {{Match rugby ...}} en gérant les imbrications."""
    out = []
    i = 0
    while i < len(wikitext):
        idx = wikitext.find("{{Match rugby", i)
        if idx == -1:
            break
        depth, j = 0, idx
        while j < len(wikitext):
            if wikitext[j:j+2] == "{{":
                depth += 1; j += 2
            elif wikitext[j:j+2] == "}}":
                depth -= 1; j += 2
                if depth == 0:
                    out.append(wikitext[idx:j]); break
            else:
                j += 1
        i = j
    return out

def _wiki_find_section(wikitext, title):
    pattern = rf"==+\s*{re.escape(title)}\s*==+(.+?)(?===+\s*\S)"
    m = re.search(pattern, wikitext, re.DOTALL)
    return m.group(1) if m else ""

def collect_six_nations(year=2026):
    """Scrape un Tournoi des Six Nations via l'API Wikipedia."""
    page = f"Tournoi_des_Six_Nations_{year}"
    url = f"{WIKI_API}?action=parse&page={page}&format=json&prop=wikitext&utf8=1"
    data = get_json(url)
    wikitext = data["parse"]["wikitext"]["*"]
    
    out = []
    for section_title, phase in JOURNEES_6N:
        section = _wiki_find_section(wikitext, section_title)
        if not section:
            continue
        for tpl in _wiki_extract_templates(section):
            m = _wiki_parse_match_template(tpl)
            if not m.get("home") or not m.get("away"):
                continue
            start_utc = combine_date_time_paris(m["date"], m["time_local"]) if m["time_local"] else None
            out.append({
                "id": slug("six-nations", year, m["date"], m["home"], m["away"]),
                "sport": "Rugby",
                "competition": "Tournoi des VI Nations",
                "date": m["date"],
                "start": start_utc,
                "tbd": start_utc is None and m["score"] is None,
                "home": m["home"],
                "away": m["away"],
                "score": m["score"],
                "status": "finished" if m["score"] else "scheduled",
                "group": phase,
                "venue": m["venue"],
            })
    return out

# ---------------------------------------------------------------- main
def main():
    matches, sources = [], []

    # Football
    for name, url in OPENFOOTBALL:
        try:
            rows = collect_openfootball(name, url)
            matches += rows
            sources.append({"name": name, "sport": "Football", "ok": True, "count": len(rows)})
            print(f"[ok] {name}: {len(rows)} matchs")
        except Exception as e:
            sources.append({"name": name, "sport": "Football", "ok": False, "error": str(e)})
            print(f"[!!] {name}: {e}", file=sys.stderr)

    # Rugby Top 14
    try:
        rows = collect_top14("2025-2026")
        matches += rows
        sources.append({"name": "Top 14", "sport": "Rugby", "ok": True, "count": len(rows)})
        print(f"[ok] Top 14: {len(rows)} matchs")
    except Exception as e:
        sources.append({"name": "Top 14", "sport": "Rugby", "ok": False, "error": str(e)})
        print(f"[!!] Top 14: {e}", file=sys.stderr)

    # Rugby Tournoi des Six Nations
    try:
        rows = collect_six_nations(2026)
        matches += rows
        sources.append({"name": "Tournoi des VI Nations", "sport": "Rugby", "ok": True, "count": len(rows)})
        print(f"[ok] Tournoi des VI Nations: {len(rows)} matchs")
    except Exception as e:
        sources.append({"name": "Tournoi des VI Nations", "sport": "Rugby", "ok": False, "error": str(e)})
        print(f"[!!] Tournoi des VI Nations: {e}", file=sys.stderr)

    # dédoublonnage + tri
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
