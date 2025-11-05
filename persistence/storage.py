"""Persistence helpers for loading and storing simulation state."""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Dict, List

from domain.models import (
    Golfer,
    PlayerSeasonStats,
    Season,
    SeasonPlayer,
    SimulationState,
    Tournament,
)


class StateRepository:
    """Handles persistence of the simulation state on disk."""

    def __init__(self, config_path: Path, state_path: Path) -> None:
        self.config_path = config_path
        self.state_path = state_path
        self.config = self._load_config()

    def _load_config(self) -> Dict:
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found at {self.config_path}."
            )
        with self.config_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _create_initial_state(self) -> SimulationState:
        player_data = self.config["initial_player"]
        golfer = Golfer.from_dict(player_data)
        tournaments = [
            Tournament.from_dict(tournament)
            for tournament in self.config.get("tournaments", [])
        ]
        season = Season(
            current_week=1,
            total_weeks=int(self.config.get("season_length", len(tournaments))),
            tournaments=tournaments,
        )
        season_players = self._load_season_players(golfer)
        player_stats = PlayerSeasonStats(player_id="USER")
        return SimulationState(
            golfer=golfer,
            season=season,
            ledger=[],
            season_players=season_players,
            player_stats=player_stats,
        )

    def load_state(self) -> SimulationState:
        if not self.state_path.exists():
            state = self._create_initial_state()
            self.save_state(state)
            return state

        with self.state_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        return SimulationState.from_dict(raw)

    def save_state(self, state: SimulationState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w", encoding="utf-8") as handle:
            json.dump(state.to_dict(), handle, indent=2)

    def reset_state(self) -> SimulationState:
        state = self._create_initial_state()
        self.save_state(state)
        return state

    # Convenience accessors to configuration knobs ------------------------

    @property
    def training_rules(self) -> Dict:
        return self.config.get("training", {})

    @property
    def rest_rules(self) -> Dict:
        return self.config.get("rest", {})

    @property
    def tournament_rules(self) -> Dict:
        return self.config.get("tournament", {})

    @property
    def agent_chat_rules(self) -> Dict:
        return self.config.get("agent_chat", {})

    # Internal helpers ----------------------------------------------------
    def _load_season_players(self, golfer: Golfer) -> List[SeasonPlayer]:
        players_config = self.config.get("season_players") or []
        rng = random.Random(1337)
        avg_skill = sum(golfer.skills.values()) / max(1, len(golfer.skills))
        if players_config:
            players: List[SeasonPlayer] = []
            for idx, entry in enumerate(players_config, start=1):
                player_id = entry.get("player_id") or f"P{idx:03d}"
                name = entry.get("name", f"Pro {idx:03d}")
                base_skill = self._compute_initial_base_skill(avg_skill, rng)
                players.append(
                    SeasonPlayer(player_id=player_id, name=name, base_skill=base_skill)
                )
            return players
        return self._generate_season_players(count=199, avg_skill=avg_skill, rng=rng)

    def _generate_season_players(self, count: int, avg_skill: float, rng: random.Random) -> List[SeasonPlayer]:
        players: List[SeasonPlayer] = []
        for idx in range(1, count + 1):
            player_id = f"P{idx:03d}"
            name = f"Pro {idx:03d}"
            base_skill = self._compute_initial_base_skill(avg_skill, rng)
            players.append(
                SeasonPlayer(
                    player_id=player_id,
                    name=name,
                    base_skill=base_skill,
                )
            )
        return players

    @staticmethod
    def _compute_initial_base_skill(avg_skill: float, rng: random.Random) -> float:
        base = avg_skill + rng.gauss(0, 4.0)
        return max(40.0, min(70.0, base))
