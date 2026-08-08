# Decks à pictogrammes — Fist of Five & Vote romain

> **Date** 2026-08-08 · **Statut** conception validée, implémentation à planifier
> **Repos concernés** `Poker_server` (référentiel, snapshot, résolution) et
> `Poker_frontend` (rendu des cartes, registre d'icônes, traductions).
> Complète `2026-07-08-data-model.md`, dont les principes P1 et §3.6 restent la référence.

## 1. Objet

Ajouter deux types de vote au produit, à côté du Delegation Poker existant :

- **Fist of Five** — 6 cartes, `0` à `5`, gradation d'adhésion **sans règle de véto** :
  le `0` signifie « je n'adhère pas du tout », pas « je bloque ».
- **Vote romain** — 3 cartes, `+1` / `0` / `-1` : pour, neutre, contre.

Les cartes des deux decks sont **muettes** : un pictogramme plein cadre, aucun texte.
Elles partagent un unique fond, `decks/cards/front_cartes_foxugly.png`.

Les deux decks sont **réservés aux équipes payantes** (`free_tier=False`).

## 2. Ce que l'existant permet déjà

Trois vérifications faites sur le code avant conception, qui réduisent fortement le périmètre :

| Constat | Conséquence |
|---|---|
| Le moteur de vote est générique : `revealed_payload()` compte les votes par valeur, `act_result()` valide l'appartenance au deck. Aucune logique propre à la délégation. | Ajouter un type de vote est un travail de **référentiel**, pas de machine à états. |
| Aucune notion de véto, blocage ou consensus n'existe dans le backend. | « Fist of Five sans véto » est le comportement par défaut : **rien à implémenter**. |
| `decks/selection.py` est entièrement générique (`available_decks`, `decks_for_team`). | Un deck actif devient jouable automatiquement ; le filtrage `free_tier` s'applique seul. |

Le seul manque réel est **le rendu d'une icône** : le pipeline actuel ne connaît que des
couches de texte, et le composant carte écrase délibérément la police portée par le snapshot.

## 3. Référentiel ajouté

Peuplé par une commande de gestion calquée sur `seed_delegation_deck`, idempotente
(elle s'abstient si le deck standard du type existe déjà).

| | Fist of Five | Vote romain |
|---|---|---|
| `VoteType.code` | `fist_of_five` | `roman_vote` |
| `VoteType.resolution_strategy` | `fist_of_five_v1` | `roman_v1` |
| `Deck.free_tier` | `False` | `False` |
| `Deck.is_standard` | `True` | `True` |
| Valeurs de carte (`Card.value`) | `0` `1` `2` `3` `4` `5` | `+1` `0` `-1` |
| `Card.background_image` | `decks/cards/front_cartes_foxugly.png` (partagé) | idem |
| Couches par carte | 1, de type `icon` | 1, de type `icon` |
| Clés d'icône | `fist-0` … `fist-5` | `thumb-up`, `thumb-side`, `thumb-down` |

`Deck.name` (champ parler) est traduit en 5 langues — seul texte à rédiger, inévitable
puisqu'il s'affiche dans le sélecteur de type de poker.

### Pourquoi ces valeurs de carte

`Card.value` est la valeur canonique stockée dans `Vote.card_value` et `Result.chosen_value`.
Elle **ressort telle quelle dans quatre surfaces** dès lors que la carte n'a pas de couche
`i18n` — ce qui est le cas ici, les cartes étant muettes :

| Surface | Code |
|---|---|
| Liste déroulante « valeur retenue » du facilitateur | `room.component.ts:191` |
| Bandeau de résultat en salle | `room.component.ts:194` |
| Historique d'équipe (SPA) | `history/api_views.py:25` → `history-detail.component.ts:80` |
| E-mail d'historique | `history/email.py:26` |

`+1` / `0` / `-1` se lisent dans les 5 langues sans une seule traduction ; des valeurs
verbales (`up` / `neutral` / `down`) auraient fui en anglais dans ces quatre surfaces.

## 4. La couche `icon`

`TextLayerKind` gagne une troisième valeur, `icon`. La couche **réutilise tous les champs
existants** — `pos_x`, `pos_y`, `font_size` (taille en `cqh`), `color`, `align` — et son
`content` porte la clé d'icône au lieu d'une prose. Aucun champ nouveau ; la migration
n'ajoute qu'un choix.

**Point de vigilance.** `_layer_text()` (`rooms/snapshot.py:21`) transforme aujourd'hui toute
couche non-`static` en dictionnaire par langue. Une couche `icon` doit être traitée **comme
une couche `static`** et sortir en chaîne simple : une clé d'icône ne se traduit pas.

**Ce qui ne bouge pas.** `cardName()` (front) et `_level_name()` (back) cherchent strictement
`kind == "i18n"`. Ils ignoreront donc les couches `icon` et retomberont sur la valeur brute
de la carte — exactement le comportement voulu. Ces deux fonctions ne sont pas modifiées.

## 5. Rendu — registre de pictogrammes

Un module `shared/ui/card-icons/` associe chaque clé à un SVG inline (`viewBox` normalisé,
`fill="currentColor"`). Le composant `delegation-card` branche sur le type de couche :
`icon` → le SVG du registre, tout le reste → le `<span>` actuel, inchangé. Position, taille
et couleur restent héritées de la couche, donc `currentColor` fait fonctionner la
personnalisation de couleur par équipe sans traitement particulier.

### Le jeu de 9 pictogrammes

Les neuf sont dessinés **comme un seul jeu cohérent**, pouces compris — mêmes proportions,
même épaisseur de trait, même angle de poignet. Emprunter les pouces à PrimeIcons aurait
mélangé des icônes d'interface pensées pour 16 px avec des mains dessinées, ce qui se
verrait à l'échelle d'une carte. Dessiner les trois pouces règle en outre proprement le
pouce « neutre », qui serait sinon un pouce levé pivoté de 90° en CSS.

Deux contraintes de dessin explicites :

- **`fist-3` et `fist-4` doivent se distinguer d'un coup d'œil** — écartement franc des
  doigts, silhouettes nettement différentes. C'est la faiblesse connue d'un deck muet.
- **`fist-0` n'est pas un veto.** Poing dessiné dans la continuité des autres mains (même
  paume, même angle, simplement aucun doigt levé), et non un poing brandi de face, qui se
  lirait « stop » et contredirait la nature du deck.

Aucun jeu d'icônes libre ne propose une main comptant 0 à 5 doigts — ni PrimeIcons, ni
Font Awesome, ni Unicode (les emoji couvrent ✊ ✌️ ✋ mais pas 3 ni 4 doigts). Ces six
mains sont donc à produire quelle que soit l'approche retenue ; les loger dans un registre
versionné avec le code les rend réutilisables et recolorables, contrairement à des pixels
cuits dans une illustration.

## 6. Résolution — activation de `resolution_strategy`

`VoteType.resolution_strategy` existe depuis l'origine, voyage dans le snapshot, et
n'est routé nulle part. Ce chantier lui donne son usage prévu par le principe **P1** de
`2026-07-08-data-model.md` : « la DB décrit un type de vote, le code décide du comportement ».

`revealed_payload()` (`realtime/services.py:426`) calcule aujourd'hui un écart min/max sur
les votes dont la valeur passe `isdigit()`. Une table de routage déclare désormais les
stratégies **ordinales**, dont les valeurs forment une échelle :

| Stratégie | Écart min/max |
|---|---|
| `delegation_v1` | calculé — comportement actuel strictement inchangé |
| `fist_of_five_v1` | calculé — toutes les valeurs sont numériques, l'écart est pertinent |
| `roman_v1` | **non calculé** → `{min: null, max: null}` |

Pour `roman_v1`, la garde de `room.component.html:82` (`min !== null && max !== null`)
masque alors l'affichage. Sans ce routage, `+1` et `-1` échoueraient à `isdigit()` tandis
que `0` le passerait, et l'écran afficherait « 0 – 0 » — un faux consensus — sous un vote
romain pourtant partagé.

C'est le seul changement de comportement du moteur. Il est neutre pour toutes les salles
existantes.

## 7. Mise à disposition

Aucun code de sélection à écrire : `available_decks()` et `decks_for_team()` prennent les
nouveaux decks en compte automatiquement. `free_tier=False` les écarte des salles sans
compte ; une équipe abonnée les active depuis son sélecteur de decks, qui les listera seul.

Deux clés de traduction à ajouter dans les 5 catalogues, à côté de `delegation_poker` :
`room.deck.type.fist_of_five` et `room.deck.type.roman_vote`.

## 8. Tests

**Backend**

- La commande de peuplement crée bien 6 et 3 cartes, et reste idempotente.
- Une couche `icon` sort du snapshot en **chaîne simple**, pas en dictionnaire par langue.
- L'écart est calculé pour `fist_of_five_v1`, absent pour `roman_v1`, inchangé pour
  `delegation_v1`.
- `act_result` accepte `+1` et `-1` comme valeurs retenues.
- Une salle sans compte ne peut jouer ni l'un ni l'autre deck (`free_tier=False`).

**Frontend**

- Le composant carte rend un SVG pour une couche `icon`, un `<span>` pour les autres.
- **Test de complétude du registre** : toute valeur de carte des deux decks a une icône
  associée, pour qu'un oubli échoue en intégration continue plutôt qu'en salle.

## 9. Hors périmètre

- Aucune logique de véto, de blocage ou de quorum.
- Aucune refonte de `cardName()` ni de `_level_name()`.
- Aucune nouvelle illustration de fond — le fond est partagé et déjà en ligne.
- La clé de traduction `poker_planning`, déjà présente et inutilisée, le reste.
- Les pages publiques (tarifs, fonctionnalités) ne sont pas mises à jour ici ; si les
  nouveaux decks doivent devenir un argument commercial, c'est un chantier de contenu
  distinct.
