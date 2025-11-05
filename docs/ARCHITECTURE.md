# Architecture du simulateur de carrière de golfeur

Cette documentation détaille la structure du code, le rôle de chaque module
et décrit les principales classes et fonctions exposées.

## Vue d'ensemble

```
.
├── core/              # Règles métier de la simulation
├── data/              # Configuration et sauvegardes JSON
├── domain/            # Modèles de données (dataclasses)
├── persistence/       # Gestion de la configuration et de l'état persistant
├── routes/            # API FastAPI
├── tests/             # Tests unitaires
└── ui/                # Client terminal (curses)
```

Le serveur FastAPI (`routes/api.py`) instancie un `SimulationEngine`
(`core/simulation.py`) alimenté par un `StateRepository`
(`persistence/storage.py`). Le client terminal (`ui/client.py`) consomme l'API
pour afficher l'état courant et piloter les actions du joueur. Les modèles
(`domain/models.py`) décrivent l'état sérialisable partagé entre composants.

## Détails par module

### `domain/models.py`

| Nom | Type | Description |
| --- | --- | --- |
| `Tournament` | `@dataclass` | Décrit un tournoi du calendrier (semaine, difficulté, gains, frais d'inscription, réputation). Expose `from_dict`/`to_dict` pour la sérialisation JSON. |
| `LedgerEntry` | `@dataclass` | Représente un événement de la saison (action, variations d'argent, fatigue physique/mentale, réputation, motivation et évolutions de compétences). |
| `Golfer` | `@dataclass` | Modèle principal du joueur (identité, compétences, forme, fatigue physique, fatigue mentale, finances, réputation, motivation). |
| `Season` | `@dataclass` | État courant de la saison (semaine en cours, total de semaines, liste des tournois). Fournit `lookup_tournament(week)` pour retrouver le tournoi prévu. |
| `SimulationState` | `@dataclass` | Agrège `Golfer`, `Season`, `ledger` et `last_message`. Utilisé par tous les composants pour échanger l'état complet. |

Toutes les classes disposent de méthodes `from_dict` et `to_dict` pour assurer une
sérialisation cohérente via la persistance JSON.

### `persistence/storage.py`

| Nom | Type | Description |
| --- | --- | --- |
| `StateRepository` | Classe | Charge la configuration (`data/config.json`), instancie l'état initial, lit/écrit l'état courant (`data/state.json`). Expose : |
| | | • `load_state()` — crée ou recharge un `SimulationState` complet. |
| | | • `save_state(state)` — persiste l'état sur disque. |
| | | • `reset_state()` — recrée l'état initial à partir de la configuration. |
| | | • `training_rules`, `rest_rules`, `tournament_rules`, `agent_chat_rules` — accès aux paramètres métier configurables. |

### `core/simulation.py`

| Nom | Type | Description |
| --- | --- | --- |
| `SimulationEngine` | Classe | Implémente toute la logique métier. Méthodes principales : |
| | | • `get_state()` — retourne l'état courant sans le modifier. |
| | | • `reset()` — réinitialise la saison via le `StateRepository`. |
| | | • `perform_action(action, payload=None)` — applique les actions (`train`, `rest`, `tournament`, `agent_chat`), sauvegarde l'état, retourne la nouvelle version. |
| | | Méthodes internes : |
| | | • `_handle_training(payload)` — incrémente la compétence choisie, applique coût, fatigue physique et charge mentale. |
| | | • `_handle_rest()` — réduit les deux fatigues et augmente légèrement la forme. |
| | | • `_handle_tournament(payload)` — évalue la performance de la semaine (en tenant compte de la fatigue physique, de la fatigue mentale et de la motivation), prélève les frais d'inscription, calcule les gains nets et met à jour le ledger. |
| | | • `_handle_agent_chat(payload)` — modélise un échange avec l'agent : récupération mentale et variation de motivation sans avancer la semaine. |
| | | • `_advance_week()` — fait progresser la saison. |
| | | • `_evaluate_performance(tournament)` et `_compute_rewards(tournament, performance)` — helpers de calcul de score, gains et impact motivationnel. |

L'engine limite l'accès public à `get_state`, `perform_action` et `reset`, ce qui
simplifie l'intégration côté API ou tests.

### `routes/api.py`

| Élement | Description |
| --- | --- |
| `ActionRequest` | Modèle Pydantic validant le corps JSON (`action`, `skill`, ajustements de motivation ou de récupération mentale optionnels). |
| `app` | Instance FastAPI configurée (titre/description/version). |
| `GET /state` | Retourne l'état courant sérialisé via `SimulationEngine.get_state()`. |
| `POST /action` | Valide l'entrée et délègue à `SimulationEngine.perform_action()`. Gère les erreurs métier en renvoyant un HTTP 400. |
| `POST /reset` | Réinitialise la saison via `SimulationEngine.reset()`. |

Le module crée un `StateRepository` puis un `SimulationEngine` au démarrage du
processus afin de partager l'état entre requêtes.

### `ui/client.py`

| Nom | Type | Description |
| --- | --- | --- |
| `fetch_state(base_url)` | Fonction utilitaire — `GET /state`. |
| `post_action(base_url, action, payload=None)` | Fonction utilitaire — `POST /action`. |
| `ClientApp` | Classe gérant la boucle curses : |
| | | • `run()` / `_mainloop` — initialisent l'interface, rafraîchissent l'état et lisent les interactions clavier. |
| | | • `_handle_choice` — dispatch des entrées utilisateur (actions : entraînement, tournoi, repos, discussion avec l'agent, reset). |
| | | • `_training_flow` — invite à choisir une compétence, déclenche l'action `train`. |
| | | • `_execute_action` — enveloppe `post_action` avec gestion des erreurs. |
| | | • `_render` — dessine le tableau de bord (statistiques, compétences, niveaux de fatigue, motivation, dernières nouvelles) et colore la variation d'argent (gain/perte). |
| | | • `_render_ledger` (mode admin) — affiche les 5 dernières entrées avec variations financières colorées, fatigues et motivation. |
| | | • `_prompt` — fenêtre pop-up pour sélectionner une option numérique. |
| `parse_args()` | Parse `--url` et `--admin`. |
| `main()` | Point d'entrée du module (`python -m ui.client`). |

### `server.py`

| Nom | Type | Description |
| --- | --- | --- |
| `server.py` | Script minimal permettant de lancer Uvicorn via `python server.py`. Importe `app` depuis `routes.api`. |

### `tests/test_simulation.py`

Couverture unitaire du moteur :

- `test_training_increases_skill_and_fatigue` — vérifie l'effet d'un entraînement sur les deux fatigues.
- `test_tournament_yields_prize_and_advances_week` — contrôle la progression de semaine, la création d'entrées de ledger, l'augmentation des fatigues et la cohérence du delta financier.
- `test_tournament_entry_fee_applies_on_loss` — garantit que les frais d'inscription sont déduits lorsque la performance ne rapporte aucun gain.
- `test_agent_chat_recovers_mental_fatigue_and_boosts_motivation` — confirme l'effet d'une discussion sur la motivation et la fatigue mentale sans avancer la semaine.

Les tests utilisent un `StateRepository` temporaire (via `tmp_path`) pour isoler
la persistance.

## Fichiers de données

- `data/config.json` — Paramètres de base : joueur initial, tournois, règles
  (coûts, fatigue, récompenses). Modifiable sans changer le code.
- `data/state.json` — Sauvegarde auto générée après chaque action.

## Flux d'exécution

1. **Démarrage du serveur** : FastAPI instancie `StateRepository` puis
   `SimulationEngine` qui charge ou crée l'état persistant.
2. **Interaction du client** : le client curses récupère l'état (`GET /state`),
   l'affiche et envoie les actions (`POST /action`).
3. **Logique métier** : `SimulationEngine` met à jour l'état, journalise dans le
   ledger, avance la semaine et sauvegarde via `StateRepository`.
4. **Persistance** : Chaque action écrit `data/state.json`, permettant de
   reprendre la partie au prochain lancement.

Cette architecture modulaire facilite l'ajout ultérieur de nouvelles actions,
compétences ou interfaces (web, IA, etc.) en conservant un cœur métier unique.
