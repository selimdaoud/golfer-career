# Simulateur de carrière de golfeur – Phase M2

Cette version fournit un socle jouable complet composé d'un serveur FastAPI, d'un client terminal `curses` et désormais d'un client navigateur embarquant le terminal. La simulation couvre une saison complète de 36 semaines avec un plateau de 200 joueurs inspirés du classement OWGR. Chaque semaine, vous choisissez entre entraînement, tournoi (avec animation), repos ou coaching mental. Le nouveau client web permet de lancer plusieurs sessions concurrentes directement depuis votre navigateur avec un simple changement de thème pour basculer en mode « terminal 3270 ».

## Prérequis

- Python 3.12+
- `pip` pour installer les dépendances

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Lancement du serveur

```bash
uvicorn routes.api:app --reload
```

Le serveur expose les routes :

- `GET /state` : renvoie l'état courant du joueur et de la saison.
- `POST /action` : applique une action (`train`, `tournament`, `rest`, `agent_chat`).
- `POST /reset` : réinitialise la saison.

## Client terminal

Lancer le client dans un second terminal :

```bash
python -m ui.client --url http://127.0.0.1:8000
```

Options disponibles :

- `--admin` : affiche l'historique financier (ledger) en plus des informations du joueur.
- la ligne "Argent" indique la variation de la dernière action : le montant est affiché en vert lors d'un gain et en rouge en cas de perte.
- À chaque lancement, la saison est automatiquement réinitialisée et un popup d'introduction rappelle les contrôles (le joueur principal se nomme désormais **Eric Miles**).

## Client navigateur

Un client browser reprenant l'interface curses est disponible à l'adresse `http://127.0.0.1:8000/browser/`.

- Chaque onglet du navigateur ouvre sa propre session isolée (le serveur génère un nouvel état de saison par WebSocket).
- Un bouton « Redémarrer » est disponible dans l'entête, et un indicateur de date/heure UTC se met à jour en temps réel.
- Appuyez sur la touche `t` pour basculer entre le thème moderne et une skin « terminal 3270 » (avec police IBM3270 intégrée).

## Persistance

L'état de la partie hors sessions navigateur est stocké dans `data/state.json`. Les paramètres de configuration (joueur initial, règles, 36 tournois, liste des 200 joueurs) se trouvent dans `data/config.json`.
Chaque tournoi définit son `entry_fee` (frais d'inscription) en plus du `purse`. Une valeur par défaut peut être fournie dans la section `tournament` si une épreuve ne précise pas de frais spécifiques.
Les sessions lancées depuis le navigateur utilisent des fichiers temporaires distincts et sont détruites automatiquement à la fermeture du terminal embarqué.

## Tests

```bash
pytest
```

## Documentation d'architecture

Une description détaillée des modules, classes et fonctions principales est
disponible dans [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Exemple d'échange JSON

### Requête

```http
POST /action
Content-Type: application/json

{
  "action": "train",
  "skill": "driving"
}
```

### Réponse

```json
  {
    "golfer": {
      "name": "Eric Miles",
      "age": 18,
      "skills": {"driving": 58, "approach": 52, "short_game": 50, "putting": 51},
      "fatigue_physical": 22,
      "fatigue_mental": 13,
      "form": 52,
      "money": 1300,
      "reputation": 5,
      "motivation": 57
    },
    "season": {"current_week": 2, "total_weeks": 36, "tournaments": [...]},
    "ledger": [
      {
        "week": 1,
        "action": "Entraînement",
        "description": "Séance de travail sur driving",
        "money_delta": -200,
        "fatigue_physical_delta": 12,
        "fatigue_mental_delta": 8,
        "reputation_delta": 0,
        "motivation_delta": 0,
        "skill_changes": {"driving": 3}
      }
    ],
    "last_message": "Entraînement effectué sur driving. Compétence +3, fatigue physique +12, fatigue mentale +8."
  }
```

> Les valeurs sont données à titre d'exemple et peuvent varier en fonction de l'état courant.
