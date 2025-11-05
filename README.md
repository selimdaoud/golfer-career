# Simulateur de carrière de golfeur – Phase M1

Cette première version fournit un socle minimal jouable composé d'un serveur FastAPI et d'un client terminal basé sur `curses`. La simulation couvre une saison simplifiée d'une dizaine de tournois avec quatre actions disponibles chaque semaine : entraînement, tournoi, repos ou discussion avec l'agent.

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

## Persistance

L'état de la partie est stocké dans `data/state.json`. Les paramètres de configuration (joueur initial, règles, liste de tournois) sont dans `data/config.json`.
Chaque tournoi définit son `entry_fee` (frais d'inscription) en plus du `purse`. Une valeur par défaut peut être fournie dans la section `tournament` si une épreuve ne précise pas de frais spécifiques.

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
      "name": "Alex Martin",
      "age": 18,
      "skills": {"driving": 58, "approach": 52, "short_game": 50, "putting": 51},
      "fatigue_physical": 22,
      "fatigue_mental": 13,
      "form": 52,
      "money": 1300,
      "reputation": 5,
      "motivation": 57
    },
    "season": {"current_week": 2, "total_weeks": 10, "tournaments": [...]},
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
