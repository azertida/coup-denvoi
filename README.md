# 🏟️ Coup d'envoi

Agenda multisport perso, à l'heure de Bruxelles. Pattern Radar Polar : une
GitHub Action collecte les horaires, les fusionne en un seul `matches.json`,
et la PWA lit ce fichier en local (même origine → **zéro CORS, zéro clé côté navigateur**).

## Sources
- **Football** — Coupe du monde 2026 + Euro 2028 via **openfootball** (domaine public, JSON brut, sans clé).
- **Rugby** — Tournoi des VI Nations + Top 14 via **TheSportsDB** (clé gratuite « 123 », appelée *côté serveur* dans l'Action).
- Tennis : abandonné (pas de calendrier ouvert fiable).

## Structure du dépôt
```
.
├── index.html                       ← la PWA
├── build_data.py                    ← le collecteur
├── matches.json                     ← généré par l'Action (peut être commité tel quel pour démarrer)
├── icon.png                         ← à ajouter (180×180) pour l'install iPhone
└── .github/workflows/maj-horaires.yml
```

## Mise en place (5 min)
1. Crée un dépôt GitHub, pousse `index.html`, `build_data.py`, `matches.json` et le dossier `.github/workflows/`.
2. Ajoute un `icon.png` 180×180 à la racine (ton générateur d'icônes fait ça).
3. **Settings → Pages** : source = branche `main`, dossier `/ (root)`.
4. **Settings → Actions → General → Workflow permissions** : coche *Read and write permissions* (l'Action commit `matches.json`).
5. **Onglet Actions → Maj horaires → Run workflow** pour un premier remplissage. Ensuite ça tourne tout seul 2×/jour.
6. Ouvre l'URL Pages → « Ajouter à l'écran d'accueil » sur iPhone.

> Le rugby renvoie *403* si tu lances `build_data.py` depuis certains environnements bridés (liste blanche réseau). Sur GitHub Actions, pas de restriction : VI Nations + Top 14 se peuplent normalement.

## Ajouter une compétition plus tard
- **Foot** : ajoute une ligne `(nom, url_raw)` dans `OPENFOOTBALL` (ex. un nouveau World Cup/Euro quand le fichier existe).
- **Autre sport TheSportsDB** : ajoute `(nom, "sous-chaîne du nom de ligue", "Sport")` dans `TSDB_SOURCES`. L'id de ligue est résolu automatiquement par nom.

## Mises à jour dans le temps
- Les matchs d'un tournoi/saison se mettent à jour à chaque run (scores, équipes des phases finales).
- Nouvelle édition (ex. Euro 2028 → équipes/heures qui se remplissent) : automatique, c'est le même fichier source.
- Nouveau tournoi avec un nouveau chemin de fichier : une ligne à ajouter dans la config.
