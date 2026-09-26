# Sources de données — mémo de suivi

À lire quand une compétition tombe à **0** ou perd ses horaires.
Mis à jour le 26 septembre 2026.

---

## 1. Lire le récapitulatif de fin de run

Chaque exécution se termine par :

```
--- récapitulatif ---
  Top 14                      185 matchs, horaires complets
  Coupe du monde de rugby       0 match          <- dormant, ou source à vérifier
  Champions Cup                48 matchs, 12 sans horaire
```

| Ce que dit la ligne | Interprétation | Action |
|---|---|---|
| `horaires complets` | Tout va bien | — |
| `N sans horaire` | Les matchs sont là, pas les heures | Voir §3 (complément RugbyPass) |
| `0 match` | Deux causes possibles | Voir §2 |

**Un 0 n'est pas forcément un bug.** Certains sont attendus (§5).

---

## 2. Distinguer un « 0 » dormant d'un « 0 » cassé

Wikipédia publie les affiches **avant** les dates, et les dates avant les
horaires. Un collecteur qui écarte les matchs sans date renverra donc 0
alors que la page est pleine.

Pour trancher, ouvrir le wikicode de la page :
`https://fr.wikipedia.org/wiki/<PAGE>?action=raw`
(fonctionne **même avec une IP bloquée en écriture**)

- Aucun `{{Match rugby}}` → la page n'est pas encore écrite : **dormant**
- Des `{{Match rugby}}` sans `|date=` → l'organisateur n'a pas publié le
  calendrier : **dormant**
- Des `{{Match rugby}}` avec dates, mais 0 chez nous → **bug de lecture**,
  il faut adapter le parseur

---

## 3. Sources par compétition

| Compétition | Source | Remarque |
|---|---|---|
| Coupe du monde, Euro | openfootball | dépôts dédiés, JSON |
| VI Nations, Championnat des nations, Coupe des nations | Wikipédia **FR** | `{{Match rugby}}`, sections par journée |
| Coupe du monde de rugby 2027 | **RugbyPass** (principal) | bascule sur Wikipédia si vide |
| WXV Global Series / Challenger | Wikipédia **EN** | tableaux + codes `{{ruw\|FRA}}` |
| Champions Cup, Challenge Cup | **RugbyPass** (principal) | bascule sur Wikipédia si vide |
| *Horaires manquants* | **RugbyPass** (complément) | voir ci-dessous |

### RugbyPass — pourquoi il est fiable
Son JSON, embarqué dans la page, porte un `epoch` : un horodatage **absolu**.
Aucun fuseau à deviner, et le passage à l'heure d'hiver se fait seul —
contrairement à Wikipédia, où il faut interpréter « 20:45 CET/CEST ».

Deux usages :
- **source principale** des coupes d'Europe (l'EPCR publie ses dates tard,
  Wikipédia reste vide des semaines)
- **complément horaire** pour tout match rugby daté sans heure

L'appariement se fait sur **date ± 1 jour + paire d'équipes** — la tolérance
d'un jour est indispensable : un match en Nouvelle-Zélande change de date
une fois converti en UTC.

### LNR — n'est plus utilisée
Le Top 14 et la Pro D2 ont été retirés volontairement. Le code
(`collect_lnr`, `collect_top14`, `collect_prod2`) reste dans le fichier mais
n'est plus appelé. La LNR ne gère **que** ces deux championnats : elle n'a
jamais été une source pour les coupes d'Europe (EPCR) ni l'international.

---

## 4. Pièges déjà rencontrés

- **Horaires LNR** : ils ne figurent pas au même endroit selon que le match
  est joué (score) ou à venir (heure). Le parseur cherche désormais le motif
  horaire dans toute la ligne.
- **Alias non canoniques** : « United States » et « USA » pointaient vers des
  clés différentes, empêchant l'appariement avec RugbyPass. La clé canonique
  est le nom français.
- **Nom d'équipe accentué** : « Stade Français » n'est pas confondu avec
  « France » (le ç diffère du c) — vérifié, mais à garder en tête pour toute
  nouvelle équipe suivie.
- **Cache** : `matches.json` est rechargé avec `?t=`, mais pas `index.html`.
  Après un changement d'affichage, fermer et rouvrir l'appli. Pour une
  icône, supprimer et recréer le raccourci.

---

## 5. En attente (rien à faire, se remplira seul)

- **Coupe du monde de rugby 2027** — désormais lue chez RugbyPass, qui a le
  calendrier publié par World Rugby (Wikipédia ne l'a pas daté). Les horaires
  viennent d'un `epoch` absolu : **plus de question de fuseau**, malgré un
  tournoi en Australie. Les noms sont traduits en français.
- **Euro 2028** — les équipes sont des places à pourvoir (« A1 vs A2 »)
  jusqu'au tirage, début 2028. D'où les matchs sans horaire.
- **WXV Global Series** — Wikipédia ne donne que les dates ; les horaires
  viennent de RugbyPass au fil des annonces des fédérations.
