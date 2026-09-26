#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coup d'envoi — collecteur de données.

Sources :
  - Football  : openfootball (Coupe du monde + Euro)
  - Rugby     : Top 14 (LNR), VI Nations (Wikipedia), Championnat des nations (Wikipedia)
"""

import json, re, sys, time, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone, timedelta

TIMEOUT = 30
UA = {"User-Agent": "coup-denvoi/1.0 (+github action; ana@connectes.be)"}

def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))

def get_text(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8")

def iso_z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def parse_openfootball_time(date, t):
    if not t:
        return None, True
    m = re.match(r"\s*(\d{1,2}):(\d{2})\s*UTC([+-]\d{1,2})", t)
    y, mo, d = (int(x) for x in date.split("-"))
    if not m:
        m2 = re.match(r"\s*(\d{1,2}):(\d{2})", t)
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
    if not date_iso or not time_str:
        return None
    try:
        y, mo, d = (int(x) for x in date_iso.split("-"))
        hh, mm = (int(x) for x in time_str.split(":"))
        is_dst = 3 < mo < 10 or (mo == 3 and d >= 28) or (mo == 10 and d < 28)
        offset_hours = 2 if is_dst else 1
        local = datetime(y, mo, d, hh, mm, tzinfo=timezone(timedelta(hours=offset_hours)))
        return iso_z(local)
    except Exception:
        return None

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
        sc = m.get("score") or {}
        final = sc.get("et") or sc.get("ft")   # score après prolongation prioritaire s'il existe
        score = f"{final[0]}\u2013{final[1]}" if final and len(final) == 2 else None
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

# LNR (Top 14 et Pro D2 : sites jumeaux, structure d'URL identique)
LNR_TOP14 = "https://top14.lnr.fr/calendrier-et-resultats"
LNR_PROD2 = "https://prod2.lnr.fr/calendrier-et-resultats"

def parse_french_date(date_fr, season_start_year):
    if not date_fr:
        return None
    parts = date_fr.lower().strip().split()
    if len(parts) < 3:
        return None
    try:
        day = int(parts[-2])
        month = MOIS_FR.get(parts[-1])
        if not month:
            return None
        year = season_start_year if month >= 8 else season_start_year + 1
        return f"{year:04d}-{month:02d}-{day:02d}"
    except (ValueError, IndexError):
        return None

def _lnr_parse_page(html, phase_label, season_start_year):
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
                else:
                    # Repli : pour les matchs à venir, la LNR place l'heure
                    # ailleurs dans la ligne (à côté des logos diffuseurs).
                    m = re.search(r"\b(\d{1,2})h(\d{2})\b",
                                  elem.get_text(" ", strip=True))
                    if m:
                        time_str = f"{int(m.group(1)):02d}:{m.group(2)}"
            matches.append({
                "phase": phase_label, "date": current_date_iso, "time_local": time_str,
                "home": home, "away": away, "score": score,
            })
    return matches

def collect_lnr(season, base, competition, id_prefix, n_journees):
    season_start = int(season.split("-")[0])
    phases = [(f"J{n}", f"j{n}") for n in range(1, n_journees + 1)]
    phases += [("Barrage", "barrage"), ("Demi-finale", "demi-finale"), ("Finale", "finale")]
    out = []
    for phase_label, slug_phase in phases:
        url = f"{base}/{season}/{slug_phase}"
        try:
            html = get_text(url)
        except Exception as e:
            print(f"  [!!] LNR {competition} {phase_label} : {e}", file=sys.stderr)
            continue
        for m in _lnr_parse_page(html, phase_label, season_start):
            start_utc = combine_date_time_paris(m["date"], m["time_local"]) if m["time_local"] else None
            out.append({
                "id": slug(id_prefix, m["date"], m["home"], m["away"]),
                "sport": "Rugby", "competition": competition,
                "date": m["date"], "start": start_utc,
                "tbd": start_utc is None and m["score"] is None,
                "home": m["home"], "away": m["away"], "score": m["score"],
                "status": "finished" if m["score"] else "scheduled",
                "group": m["phase"], "venue": None,
            })
        time.sleep(0.5)
    return out

def collect_top14(season="2025-2026"):
    return collect_lnr(season, LNR_TOP14, "Top 14", "top-14", 26)

def collect_prod2(season="2025-2026"):
    return collect_lnr(season, LNR_PROD2, "Pro D2", "pro-d2", 30)

# Wikipedia rugby helpers
WIKI_API = "https://fr.wikipedia.org/w/api.php"

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
    m = re.search(r"\{\{([A-Za-zÀ-ÿ\s\-]+?)\s+rugby(?:\s+(?:féminin|masculin|à\s+(?:XV|sept)))?\s*[|}]", text)
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
    # Cas {{Lien|langue=en|Nom du stade}}
    m = re.search(r"\{\{Lien\|[^}]*\|([^}|]+)\}\}", text)
    if m:
        stadium = m.group(1).strip()
        rest = text[m.end():]
        m2 = re.search(r"\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]", rest)
        if m2:
            city = re.sub(r"\s*\([^)]+\)$", "", m2.group(1).strip())
            return f"{stadium}, {city}"
        return stadium
    # Cas standard [[Stade]], [[Ville]]
    m = re.search(r"\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]", text)
    if m:
        stadium = m.group(1).strip()
        rest = text[m.end():]
        m2 = re.search(r"\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]", rest)
        if m2:
            city = re.sub(r"\s*\([^)]+\)$", "", m2.group(1).strip())
            return f"{stadium}, {city}"
        return stadium
    return text.strip() or None

def _wiki_parse_match_template(body):
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

def _wiki_find_section(wikitext, title_pattern):
    pattern = rf"==+\s*{title_pattern}\s*==+(.+?)(?===+\s*\S)"
    m = re.search(pattern, wikitext, re.DOTALL)
    return m.group(1) if m else ""

# Six Nations
JOURNEES_6N = [
    ("Première journée", "J1"),
    ("Deuxième journée", "J2"),
    ("Troisième journée", "J3"),
    ("Quatrième journée", "J4"),
    ("Cinquième journée", "J5"),
]

def collect_six_nations(year=2026):
    page = f"Tournoi_des_Six_Nations_{year}"
    url = f"{WIKI_API}?action=parse&page={page}&format=json&prop=wikitext&utf8=1"
    data = get_json(url)
    wikitext = data["parse"]["wikitext"]["*"]
    out = []
    for section_title, phase in JOURNEES_6N:
        section = _wiki_find_section(wikitext, re.escape(section_title))
        if not section:
            continue
        for tpl in _wiki_extract_templates(section):
            m = _wiki_parse_match_template(tpl)
            if not m.get("home") or not m.get("away"):
                continue
            start_utc = combine_date_time_paris(m["date"], m["time_local"]) if m["time_local"] else None
            out.append({
                "id": slug("six-nations", year, m["date"], m["home"], m["away"]),
                "sport": "Rugby", "competition": "Tournoi des VI Nations",
                "date": m["date"], "start": start_utc,
                "tbd": start_utc is None and m["score"] is None,
                "home": m["home"], "away": m["away"], "score": m["score"],
                "status": "finished" if m["score"] else "scheduled",
                "group": phase, "venue": m["venue"],
            })
    return out

# Championnat des nations
# Sections nommées "{{1re}} journée", "{{2e}} journée"... dans le wikicode
JOURNEES_NATIONS = [
    (r"\{\{1re\}\}\s+journée", "J1"),
    (r"\{\{2e\}\}\s+journée", "J2"),
    (r"\{\{3e\}\}\s+journée", "J3"),
    (r"\{\{4e\}\}\s+journée", "J4"),
    (r"\{\{5e\}\}\s+journée", "J5"),
    (r"\{\{6e\}\}\s+journée", "J6"),
]

def collect_nations_championship(year=2026):
    page = f"Championnat_des_nations_{year}"
    url = f"{WIKI_API}?action=parse&page={page}&format=json&prop=wikitext&utf8=1"
    data = get_json(url)
    wikitext = data["parse"]["wikitext"]["*"]
    out = []
    
    # 6 journées
    for section_pattern, phase in JOURNEES_NATIONS:
        section = _wiki_find_section(wikitext, section_pattern)
        if not section:
            continue
        for tpl in _wiki_extract_templates(section):
            m = _wiki_parse_match_template(tpl)
            if not m.get("home") or not m.get("away"):
                continue
            start_utc = combine_date_time_paris(m["date"], m["time_local"]) if m["time_local"] else None
            out.append({
                "id": slug("nations-championship", year, m["date"], m["home"], m["away"]),
                "sport": "Rugby", "competition": "Championnat des nations",
                "date": m["date"], "start": start_utc,
                "tbd": start_utc is None and m["score"] is None,
                "home": m["home"], "away": m["away"], "score": m["score"],
                "status": "finished" if m["score"] else "scheduled",
                "group": phase, "venue": m["venue"],
            })
    
    # Week-end final
    section = _wiki_find_section(wikitext, "Finales")
    if section:
        for tpl in _wiki_extract_templates(section):
            m = _wiki_parse_match_template(tpl)
            if not m.get("home") or not m.get("away"):
                continue
            start_utc = combine_date_time_paris(m["date"], m["time_local"]) if m["time_local"] else None
            out.append({
                "id": slug("nations-championship", year, "finale", m["date"], m["home"], m["away"]),
                "sport": "Rugby", "competition": "Championnat des nations",
                "date": m["date"], "start": start_utc,
                "tbd": start_utc is None and m["score"] is None,
                "home": m["home"], "away": m["away"], "score": m["score"],
                "status": "finished" if m["score"] else "scheduled",
                "group": "Finale", "venue": m["venue"],
            })
    
    return out

def collect_nations_cup(year=2026):
    # Coupe des nations (World Rugby Nations Cup) : second échelon du Championnat
    # des nations, biennal (années paires). Structure de page différente (deux
    # poules, fenêtres juillet/novembre, matchs de classement) -> on extrait tous
    # les {{Match rugby}} de la page plutôt que de deviner les titres de sections.
    page = f"Coupe_des_nations_{year}"
    url = f"{WIKI_API}?action=parse&page={page}&format=json&prop=wikitext&utf8=1"
    data = get_json(url)
    wikitext = data["parse"]["wikitext"]["*"]
    out, seen = [], set()
    for tpl in _wiki_extract_templates(wikitext):
        m = _wiki_parse_match_template(tpl)
        if not m.get("home") or not m.get("away"):
            continue
        key = (m["date"], m["home"], m["away"])
        if key in seen:
            continue
        seen.add(key)
        start_utc = combine_date_time_paris(m["date"], m["time_local"]) if m["time_local"] else None
        out.append({
            "id": slug("nations-cup", year, m["date"], m["home"], m["away"]),
            "sport": "Rugby", "competition": "Coupe des nations",
            "date": m["date"], "start": start_utc,
            "tbd": start_utc is None and m["score"] is None,
            "home": m["home"], "away": m["away"], "score": m["score"],
            "status": "finished" if m["score"] else "scheduled",
            "group": None, "venue": m["venue"],
        })
    return out

def combine_date_time_sydney(date_iso, time_str):
    # Sydney/Melbourne en oct.-nov. = heure d'été australienne (AEDT, UTC+11).
    if not date_iso or not time_str:
        return None
    try:
        y, mo, d = (int(x) for x in date_iso.split("-"))
        hh, mm = (int(x) for x in time_str.split(":"))
        local = datetime(y, mo, d, hh, mm, tzinfo=timezone(timedelta(hours=11)))
        return iso_z(local)
    except Exception:
        return None

def collect_rwc(year=2027, tz="paris"):
    # Coupe du monde de rugby (Australie 2027). Page à poules -> extraction entière.
    # tz="paris" par défaut : À VÉRIFIER quand les matchs seront datés, contre un
    # match connu (Australie-Hong Kong, 1 oct. 2027, Perth). Si les horaires du
    # wikicode sont en heure australienne, passer tz="sydney".
    page = f"Coupe_du_monde_masculine_de_rugby_à_XV_{year}"
    url = f"{WIKI_API}?action=parse&page={urllib.parse.quote(page)}&format=json&prop=wikitext&utf8=1"
    data = get_json(url)
    if "parse" not in data:
        return []
    wikitext = data["parse"]["wikitext"]["*"]
    conv = combine_date_time_sydney if tz == "sydney" else combine_date_time_paris
    out, seen = [], set()
    for tpl in _wiki_extract_templates(wikitext):
        m = _wiki_parse_match_template(tpl)
        if not m.get("home") or not m.get("away") or not m.get("date"):
            continue
        key = (m["date"], m["home"], m["away"])
        if key in seen:
            continue
        seen.add(key)
        start_utc = conv(m["date"], m["time_local"]) if m["time_local"] else None
        out.append({
            "id": slug("rwc", year, m["date"], m["home"], m["away"]),
            "sport": "Rugby", "competition": "Coupe du monde de rugby",
            "date": m["date"], "start": start_utc,
            "tbd": start_utc is None and m["score"] is None,
            "home": m["home"], "away": m["away"], "score": m["score"],
            "status": "finished" if m["score"] else "scheduled",
            "group": None, "venue": m["venue"],
        })
    return out

# Coupes d'Europe EPCR (Champions Cup / Challenge Cup) depuis Wikipedia.
# On vise la saison à venir, avec repli sur celle qui vient de finir tant que
# la page de la nouvelle édition n'a pas encore ses matchs.
def epcr_seasons():
    now = datetime.now(timezone.utc)
    y, m = now.year, now.month
    if m >= 6:
        return [f"{y}-{y+1}", f"{y-1}-{y}"]
    return [f"{y-1}-{y}", f"{y-2}-{y-1}"]

def edition_years():
    y = datetime.now(timezone.utc).year
    return [y + 1, y, y - 1]     # compétitions annuelles : édition la plus récente disponible

def collect_epcr_cup(competition, page_base, id_prefix):
    """Extrait tous les {{Match rugby}} de la page d'une édition EPCR."""
    for s in epcr_seasons():
        page = f"{page_base}_{s}"
        url = f"{WIKI_API}?action=parse&page={page}&format=json&prop=wikitext&utf8=1"
        try:
            data = get_json(url)
            wikitext = data["parse"]["wikitext"]["*"]
        except Exception:
            continue
        out = []
        for tpl in _wiki_extract_templates(wikitext):
            m = _wiki_parse_match_template(tpl)
            # Sans date, un match ne peut pas figurer dans l'agenda : on l'écarte
            # (l'EPCR publie les affiches avant les dates). Cohérent avec les
            # autres collecteurs rugby.
            if not m.get("home") or not m.get("away") or not m.get("date"):
                continue
            start_utc = combine_date_time_paris(m["date"], m["time_local"]) if m["time_local"] else None
            out.append({
                "id": slug(id_prefix, s, m["date"], m["home"], m["away"]),
                "sport": "Rugby", "competition": competition,
                "date": m["date"], "start": start_utc,
                "tbd": start_utc is None and m["score"] is None,
                "home": m["home"], "away": m["away"], "score": m["score"],
                "status": "finished" if m["score"] else "scheduled",
                "group": None, "venue": m["venue"],
            })
        if out:
            return out
    return []


# ================================================================ WXV (rugby féminin)
# Wikipédia EN, page "<année> WXV" : les rencontres y sont en lignes de TABLEAU
# (pas en {{Match rugby}}), avec des codes pays {{ruw|XXX}}.
WIKI_EN_API = "https://en.wikipedia.org/w/api.php"

EN_MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"], 1)}

# codes pays du modèle {{ruw|XXX}} — la source mêle JPN/JAP, HKG/HK, NED/NDL
WXV_TEAMS_FR = {
    "AUS": "Australie", "CAN": "Canada", "ENG": "Angleterre", "FRA": "France",
    "IRE": "Irlande", "ITA": "Italie", "JPN": "Japon", "JAP": "Japon",
    "NZL": "Nouvelle-Zélande", "SCO": "Écosse", "RSA": "Afrique du Sud",
    "USA": "États-Unis", "WAL": "Pays de Galles", "ESP": "Espagne",
    "BRA": "Brésil", "FIJ": "Fidji", "HKG": "Hong Kong", "HK": "Hong Kong",
    "NED": "Pays-Bas", "NDL": "Pays-Bas", "SAM": "Samoa",
}

WXV_TEAMS_EN = {
    "AUS": "Australia", "CAN": "Canada", "ENG": "England", "FRA": "France",
    "IRE": "Ireland", "ITA": "Italy", "JPN": "Japan", "JAP": "Japan",
    "NZL": "New Zealand", "SCO": "Scotland", "RSA": "South Africa",
    "USA": "United States", "WAL": "Wales", "ESP": "Spain",
    "BRA": "Brazil", "FIJ": "Fiji", "HKG": "Hong Kong", "HK": "Hong Kong",
    "NED": "Netherlands", "NDL": "Netherlands", "SAM": "Samoa",
}

# une ligne de rencontre : heure optionnelle, date, équipe1, équipe2, lieu
RE_ROW = re.compile(
    r"\|align=right\|\s*(?:(\d{1,2}):(\d{2})\s*<br\s*/?>\s*)?"      # heure (Challenger)
    r"(\d{1,2})\s+([A-Z][a-z]+)\s+(\d{4})"                          # 12 September 2026
    r"\s*\|\|align=right\|\s*\{\{ruw-rt\|([A-Za-z]+)[^}]*\}\}"       # équipe à domicile
    r"\s*\|\|align=center\|.*?"                                      # cellule « v »
    r"\|\|\s*\{\{ruw\|([A-Za-z]+)[^}]*\}\}"                          # équipe visiteuse
    r"(?:\s*\|\|\s*(.*?))?\s*$",                                     # lieu (optionnel)
    re.MULTILINE)


def _clean_venue(raw):
    if not raw:
        return None
    v = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", raw)   # [[A|B]] -> B
    v = re.sub(r"\[\[([^\]]*)\]\]", r"\1", v)              # [[A]]   -> A
    v = re.sub(r"\s+", " ", v).strip(" ,")
    return v or None


def parse_wxv(wikitext, names):
    """Retourne (matchs Global Series, matchs Challenger)."""
    split = wikitext.find("==WXV Global Series Challenger==")
    if split == -1:
        parts = [("WXV Global Series", wikitext)]
    else:
        parts = [("WXV Global Series", wikitext[:split]),
                 ("WXV Challenger", wikitext[split:])]

    out = {}
    for comp, chunk in parts:
        rows, seen = [], set()
        for m in RE_ROW.finditer(chunk):
            hh, mm, day, mon_en, year, home_c, away_c, venue = m.groups()
            mon = EN_MONTHS.get(mon_en)
            if not mon:
                continue
            home, away = names.get(home_c), names.get(away_c)
            if not home or not away:
                continue                       # code pays inconnu -> on ignore
            date = f"{int(year):04d}-{mon:02d}-{int(day):02d}"
            key = (date, home, away)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "date": date,
                "time_local": f"{int(hh):02d}:{mm}" if hh else None,
                "home": home, "away": away,
                "venue": _clean_venue(venue),
            })
        out[comp] = rows
    return out


def combine_date_time_hongkong(date_iso, time_str):
    """Le Challenger se joue à Hong Kong (UTC+8, pas d'heure d'été)."""
    if not date_iso or not time_str:
        return None
    try:
        y, mo, d = (int(x) for x in date_iso.split("-"))
        hh, mm = (int(x) for x in time_str.split(":"))
        local = datetime(y, mo, d, hh, mm, tzinfo=timezone(timedelta(hours=8)))
        return iso_z(local)
    except Exception:
        return None

def collect_wxv(names, wanted, id_prefix="wxv"):
    """wanted : libellés de compétition à retenir -> {clé parseur: nom affiché}."""
    for year in (datetime.now(timezone.utc).year + 1, datetime.now(timezone.utc).year):
        page = f"{year}_WXV"
        url = (f"{WIKI_EN_API}?action=parse&page={page}"
               f"&format=json&prop=wikitext&utf8=1&redirects=1")
        try:
            data = get_json(url)
        except Exception:
            continue
        if "parse" not in data:
            continue
        parsed = parse_wxv(data["parse"]["wikitext"]["*"], names)
        rows = []
        for key, label in wanted.items():
            for m in parsed.get(key, []):
                # Global Series : heures non publiées -> date seule.
                # Challenger : heures locales de Hong Kong.
                start = (combine_date_time_hongkong(m["date"], m["time_local"])
                         if m["time_local"] else None)
                rows.append({
                    "id": slug(id_prefix, year, m["date"], m["home"], m["away"]),
                    "sport": "Rugby", "competition": label,
                    "date": m["date"], "start": start,
                    "tbd": start is None,
                    "home": m["home"], "away": m["away"], "score": None,
                    "status": "scheduled",
                    "group": None, "venue": m["venue"],
                })
        if rows:
            return rows, year
    return [], None


# ================================================================ RUGBYPASS
# Le JSON des rencontres est embarqué dans la page HTML. Chaque match porte un
# `epoch` (horodatage absolu) : aucune ambiguïté de fuseau, et le passage à
# l'heure d'hiver est géré tout seul. Sert en source principale pour les coupes
# d'Europe, et en complément horaire pour les compétitions dont la source
# principale (Wikipédia) ne donne que la date.
RP_BASE = "https://www.rugbypass.com"

def _rp_blocs_json(html):
    """Tableaux JSON de niveau racine commençant par [{"epoch":."""
    blocs, i = [], 0
    while True:
        d = html.find('[{"epoch":', i)
        if d == -1:
            break
        prof, j, dans_txt, echap = 0, d, False, False
        while j < len(html):
            c = html[j]
            if echap:
                echap = False
            elif c == "\\":
                echap = True
            elif c == '"':
                dans_txt = not dans_txt
            elif not dans_txt:
                if c in "[{":
                    prof += 1
                elif c in "]}":
                    prof -= 1
                    if prof == 0:
                        blocs.append(html[d:j+1]); break
            j += 1
        i = j + 1
    return blocs

def rp_matchs(uri):
    """Rencontres d'une compétition RugbyPass (uri = segment d'URL)."""
    html = get_text(f"{RP_BASE}/{uri}/fixtures-results/")
    out, vus = [], set()
    for bloc in _rp_blocs_json(html):
        try:
            data = json.loads(bloc)
        except Exception:
            continue
        for jour in data:
            tournois = jour.get("tournaments")
            listes = tournois if isinstance(tournois, list) else list((tournois or {}).values())
            for t in listes:
                for g in t.get("games", []):
                    h = (g.get("homeTeam") or {}).get("name")
                    a = (g.get("awayTeam") or {}).get("name")
                    ep = g.get("epoch")
                    if not h or not a or not ep:
                        continue          # phase finale : équipes encore inconnues
                    cle = (ep, h, a)
                    if cle in vus:
                        continue
                    vus.add(cle)
                    out.append({
                        "epoch": ep, "home": h, "away": a,
                        "round": g.get("round") or None,
                        "venue": g.get("venue") or None,
                        "hs": g.get("homeScore"), "as": g.get("awayScore"),
                        "played": bool(g.get("played")),
                    })
    return out

def collect_rugbypass(uri, competition, id_prefix, names=None):
    """Source principale : construit directement les matchs de l'appli.
    names : table de traduction des noms (RugbyPass publie en anglais).
    Les clubs gardent leur nom ; seules les sélections sont traduites."""
    def _nom(n):
        if not names:
            return n
        base = n[:-6].strip() if n.endswith(" Women") else n
        return names.get(base, n)
    rows = []
    for m in rp_matchs(uri):
        dt = datetime.fromtimestamp(m["epoch"], tz=timezone.utc)
        date = dt.strftime("%Y-%m-%d")
        score = (f"{m['hs']}\u2013{m['as']}"
                 if m["played"] and m["hs"] is not None else None)
        rows.append({
            "id": slug(id_prefix, date, _nom(m["home"]), _nom(m["away"])),
            "sport": "Rugby", "competition": competition,
            "date": date, "start": iso_z(dt),
            "tbd": False,
            "home": _nom(m["home"]), "away": _nom(m["away"]), "score": score,
            "status": "finished" if score else "scheduled",
            "group": m["round"], "venue": m["venue"],
        })
    return rows

# --- complément horaire -------------------------------------------------
# Noms RugbyPass -> noms utilisés par nos collecteurs Wikipédia (FR).
RP_VERS_FR = {
    "New Zealand": "Nouvelle-Zélande", "England": "Angleterre",
    "South Africa": "Afrique du Sud", "Wales": "Pays de Galles",
    "United States": "États-Unis", "USA": "États-Unis",
    "Ireland": "Irlande", "Italy": "Italie", "Scotland": "Écosse",
    "Japan": "Japon", "Spain": "Espagne", "Australia": "Australie",
    "France": "France", "Canada": "Canada", "Brazil": "Brésil",
    "Fiji": "Fidji", "Netherlands": "Pays-Bas", "Samoa": "Samoa",
    "Hong Kong": "Hong Kong", "Hong Kong China": "Hong Kong",
    "Georgia": "Géorgie", "Portugal": "Portugal", "Romania": "Roumanie",
    "Uruguay": "Uruguay", "Chile": "Chili", "Tonga": "Tonga",
    "Zimbabwe": "Zimbabwe", "Argentina": "Argentine",
}

# nos noms (EN ou FR) ramenés à la même clé que RugbyPass
# Clé canonique = le nom français. Indispensable quand plusieurs noms anglais
# désignent le même pays ("United States" / "USA") : sans cela ils reçoivent
# des clés différentes et ne s'apparient jamais.
_ALIAS = {}
for _en, _fr in RP_VERS_FR.items():
    _ALIAS[_en.casefold()] = _fr.casefold()
    _ALIAS[_fr.casefold()] = _fr.casefold()

def _norm_equipe(nom):
    """'New Zealand Women' et 'Nouvelle-Zélande' -> même clé d'appariement."""
    n = (nom or "").strip()
    for suff in (" Women", " Men"):
        if n.endswith(suff):
            n = n[: -len(suff)]
    return _ALIAS.get(n.casefold(), n.casefold())

def index_rugbypass(uris):
    """{(jour, {équipe1, équipe2}): epoch} pour compléter les horaires."""
    idx = {}
    for uri in uris:
        try:
            ms = rp_matchs(uri)
        except Exception as e:
            print(f"  [!] RugbyPass {uri}: {e}", file=sys.stderr)
            continue
        for m in ms:
            dt = datetime.fromtimestamp(m["epoch"], tz=timezone.utc)
            paire = frozenset({_norm_equipe(m["home"]), _norm_equipe(m["away"])})
            idx[(dt.strftime("%Y-%m-%d"), paire)] = m["epoch"]
        time.sleep(0.5)
    return idx

def completer_horaires(matches, idx):
    """Ajoute l'heure aux matchs qui n'ont qu'une date. Tolérance ±1 jour
    (un match en Nouvelle-Zélande peut basculer de date une fois en UTC)."""
    n = 0
    for m in matches:
        if m.get("start") or not m.get("date") or m.get("sport") != "Rugby":
            continue
        paire = frozenset({_norm_equipe(m.get("home")), _norm_equipe(m.get("away"))})
        base = datetime.strptime(m["date"], "%Y-%m-%d")
        for delta in (0, -1, 1):
            jour = (base + timedelta(days=delta)).strftime("%Y-%m-%d")
            ep = idx.get((jour, paire))
            if ep:
                dt = datetime.fromtimestamp(ep, tz=timezone.utc)
                m["start"] = iso_z(dt)
                m["date"] = dt.strftime("%Y-%m-%d")
                m["tbd"] = False
                n += 1
                break
    return n

# compétitions dont on va chercher les horaires chez RugbyPass
RP_COMPLEMENT = [
    "womens-rugby/wxv", "womens-rugby/wxv-challenger",
    "womens-internationals",   # RugbyPass y range certains matchs WXV
    "internationals",          # idem côté masculin
    "six-nations", "womens-six-nations",
    "nations-championship", "world-rugby-nations-cup",
    "rugby-world-cup",
]


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

    # Top 14 et Pro D2 débranchés (sept. 2026). Pour les réactiver : retirer les #.
    # try:
    #     rows, used = [], None
    #     for s in epcr_seasons():        # vise la saison à venir (2026-2027), repli sur 2025-2026
    #         rows = collect_top14(s)
    #         if rows:
    #             used = s
    #             break
    #     matches += rows
    #     sources.append({"name": "Top 14", "sport": "Rugby", "ok": True, "count": len(rows), "season": used})
    #     print(f"[ok] Top 14 ({used}): {len(rows)} matchs")
    # except Exception as e:
    #     sources.append({"name": "Top 14", "sport": "Rugby", "ok": False, "error": str(e)})
    #     print(f"[!!] Top 14: {e}", file=sys.stderr)
    #
    # try:
    #     rows, used = [], None
    #     for s in epcr_seasons():        # même logique de saison que le Top 14
    #         rows = collect_prod2(s)
    #         if rows:
    #             used = s
    #             break
    #     matches += rows
    #     sources.append({"name": "Pro D2", "sport": "Rugby", "ok": True, "count": len(rows), "season": used})
    #     print(f"[ok] Pro D2 ({used}): {len(rows)} matchs")
    # except Exception as e:
    #     sources.append({"name": "Pro D2", "sport": "Rugby", "ok": False, "error": str(e)})
    #     print(f"[!!] Pro D2: {e}", file=sys.stderr)

    try:
        rows, used = [], None
        for yr in edition_years():          # édition à venir d'abord, repli sur la précédente
            try:
                r = collect_six_nations(yr)
            except Exception:
                r = []
            if r:
                rows, used = r, yr
                break
        matches += rows
        sources.append({"name": "Tournoi des VI Nations", "sport": "Rugby", "ok": True, "count": len(rows), "year": used})
        print(f"[ok] Tournoi des VI Nations ({used}): {len(rows)} matchs")
    except Exception as e:
        sources.append({"name": "Tournoi des VI Nations", "sport": "Rugby", "ok": False, "error": str(e)})
        print(f"[!!] Tournoi des VI Nations: {e}", file=sys.stderr)

    try:
        rows, used = [], None
        for yr in edition_years():
            try:
                r = collect_nations_championship(yr)
            except Exception:
                r = []
            if r:
                rows, used = r, yr
                break
        matches += rows
        sources.append({"name": "Championnat des nations", "sport": "Rugby", "ok": True, "count": len(rows), "year": used})
        print(f"[ok] Championnat des nations ({used}): {len(rows)} matchs")
    except Exception as e:
        sources.append({"name": "Championnat des nations", "sport": "Rugby", "ok": False, "error": str(e)})
        print(f"[!!] Championnat des nations: {e}", file=sys.stderr)

    try:
        rows, used = [], None
        for yr in edition_years():
            try:
                r = collect_nations_cup(yr)
            except Exception:
                r = []
            if r:
                rows, used = r, yr
                break
        matches += rows
        sources.append({"name": "Coupe des nations", "sport": "Rugby", "ok": True, "count": len(rows), "year": used})
        print(f"[ok] Coupe des nations ({used}): {len(rows)} matchs")
    except Exception as e:
        sources.append({"name": "Coupe des nations", "sport": "Rugby", "ok": False, "error": str(e)})
        print(f"[!!] Coupe des nations: {e}", file=sys.stderr)

    # Coupe du monde de rugby 2027 (Australie). Dormant tant que Wikipédia n'a pas
    # daté les matchs ; le fuseau (Paris vs Sydney) reste à vérifier au moment venu.
    try:
        # RugbyPass d'abord : World Rugby a publié le calendrier, pas Wikipédia.
        # Noms traduits en français pour rester cohérent avec le reste de l'appli.
        rwc, provenance = [], None
        try:
            rwc = collect_rugbypass("rugby-world-cup", "Coupe du monde de rugby",
                                    "rwc", names=RP_VERS_FR)
            provenance = "RugbyPass"
        except Exception as e:
            print(f"  [!] RugbyPass Coupe du monde de rugby: {e}", file=sys.stderr)
        if not rwc:
            rwc = collect_rwc(2027, tz="paris")
            provenance = "Wikipédia"
        matches += rwc
        entry = {"name": "Coupe du monde de rugby", "sport": "Rugby", "ok": True,
                 "count": len(rwc), "year": 2027, "source": provenance}
        if rwc:
            s = rwc[0]
            entry["sample"] = f"{s['home']} v {s['away']} {s['date']} start={s['start']}"
        sources.append(entry)
        print(f"[ok] Coupe du monde de rugby (2027, {provenance}): {len(rwc)}"
              + (f"  ex: {entry.get('sample')}" if rwc else ""))
    except Exception as e:
        sources.append({"name": "Coupe du monde de rugby", "sport": "Rugby", "ok": False, "error": str(e)})
        print(f"[!!] Coupe du monde de rugby: {e}", file=sys.stderr)

    # Coupes d'Europe : RugbyPass en principal (dates + horaires fiables),
    # Wikipédia en secours si RugbyPass ne renvoie rien.
    for competition, uri, page_base, id_prefix in [
        ("Champions Cup", "european-champions-cup", "Champions_Cup", "champions-cup"),
        ("Challenge Cup", "challenge-cup", "Challenge_Cup", "challenge-cup"),
    ]:
        rows, provenance = [], None
        try:
            rows = collect_rugbypass(uri, competition, id_prefix)
            provenance = "RugbyPass"
        except Exception as e:
            print(f"  [!] RugbyPass {competition}: {e}", file=sys.stderr)
        if not rows:
            try:
                rows = collect_epcr_cup(competition, page_base, id_prefix)
                provenance = "Wikipédia"
            except Exception as e:
                sources.append({"name": competition, "sport": "Rugby", "ok": False, "error": str(e)})
                print(f"[!!] {competition}: {e}", file=sys.stderr)
                continue
        matches += rows
        sources.append({"name": competition, "sport": "Rugby", "ok": True,
                        "count": len(rows), "source": provenance})
        print(f"[ok] {competition} ({provenance}): {len(rows)} matchs")


    # WXV (rugby féminin) — Wikipédia EN, tableaux de rencontres
    try:
        rows, yr = collect_wxv(WXV_TEAMS_FR, {"WXV Global Series": "WXV Global Series", "WXV Challenger": "WXV Challenger"})
        matches += rows
        from collections import Counter as _C
        for comp, n in _C(m["competition"] for m in rows).items():
            sources.append({"name": comp, "sport": "Rugby", "ok": True, "count": n, "year": yr})
            print(f"[ok] {comp} ({yr}): {n}")
        if not rows:
            for comp in {"WXV Global Series": "WXV Global Series", "WXV Challenger": "WXV Challenger"}.values():
                sources.append({"name": comp, "sport": "Rugby", "ok": True, "count": 0, "year": yr})
                print(f"[ok] {comp} ({yr}): 0")
    except Exception as e:
        sources.append({"name": "WXV", "sport": "Rugby", "ok": False, "error": str(e)})
        print(f"[!!] WXV: {e}", file=sys.stderr)

    # Complément horaire : pour les matchs datés sans heure (Wikipédia ne donne
    # souvent que la date), on va chercher l'horaire exact chez RugbyPass.
    sans_heure = sum(1 for m in matches
                     if m.get("sport") == "Rugby" and m.get("date") and not m.get("start"))
    if sans_heure:
        try:
            idx = index_rugbypass(RP_COMPLEMENT)
            comble = completer_horaires(matches, idx)
            print(f"[ok] Horaires complétés par RugbyPass : {comble}/{sans_heure}")
        except Exception as e:
            print(f"[!!] Complément RugbyPass: {e}", file=sys.stderr)

    # Récapitulatif : un 0 est ambigu (dormant ? parseur en échec ?), et un
    # manque d'horaires passe inaperçu. Ces lignes le rendent visible.
    from collections import Counter as _Cnt
    _tot, _avec_h = _Cnt(), _Cnt()
    for _m in matches:
        _c = _m.get("competition")
        _tot[_c] += 1
        if _m.get("start"):
            _avec_h[_c] += 1
    print("")
    print("--- récapitulatif ---")
    for _s in sources:
        _c = _s.get("name")
        _n, _h = _tot.get(_c, 0), _avec_h.get(_c, 0)
        if _n == 0:
            print(f"  {_c:26s} 0 match          <- dormant, ou source à vérifier")
        elif _h < _n:
            print(f"  {_c:26s} {_n:4d} matchs, {_n - _h} sans horaire")
        else:
            print(f"  {_c:26s} {_n:4d} matchs, horaires complets")
    print("")

    seen, uniq = set(), []
    for m in matches:
        if m["id"] in seen:
            continue
        seen.add(m["id"]); uniq.append(m)
    uniq.sort(key=lambda m: (m.get("start") or ((m.get("date") or "9999") + "T99")))

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
