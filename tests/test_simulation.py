from __future__ import annotations

import json
from pathlib import Path

from core.simulation import SimulationEngine
from persistence.storage import StateRepository


def build_repository(tmp_path: Path) -> StateRepository:
    config = {
        "season_length": 2,
        "initial_player": {
            "name": "Test Player",
            "age": 18,
            "skills": {"driving": 50, "approach": 50, "short_game": 50, "putting": 50},
            "fatigue_physical": 0,
            "fatigue_mental": 0,
            "form": 50,
            "money": 1000,
            "reputation": 0,
            "motivation": 50,
        },
        "training": {
            "physical_fatigue": 10,
            "mental_fatigue": 6,
            "cost": 100,
            "skill_increase": 4,
        },
        "rest": {"physical_recovery": 12, "mental_recovery": 10, "form_gain": 2},
        "tournament": {
            "physical_fatigue": 15,
            "mental_fatigue": 9,
            "entry_fee": 150,
            "motivation_per_1000": 0.5,
            "motivation_per_reputation": 1.0,
            "motivation_loss_on_miss": 5,
        },
        "agent_chat": {"motivation_boost": 8, "mental_recovery": 5},
        "tournaments": [
            {
                "name": "Test Open",
                "week": 1,
                "difficulty": 0.4,
                "purse": 2000,
                "entry_fee": 120,
                "reputation_reward": 3,
            }
        ],
    }
    config_path = tmp_path / "config.json"
    state_path = tmp_path / "state.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return StateRepository(config_path=config_path, state_path=state_path)


def test_training_increases_skill_and_fatigue(tmp_path):
    repo = build_repository(tmp_path)
    engine = SimulationEngine(repository=repo, seed=1)

    initial_state = engine.get_state()
    driving_before = initial_state.golfer.skills["driving"]
    physical_before = initial_state.golfer.fatigue_physical
    mental_before = initial_state.golfer.fatigue_mental

    state = engine.perform_action("train", {"skill": "driving"})

    assert state.golfer.skills["driving"] == driving_before + 4
    assert state.golfer.fatigue_physical >= physical_before + 10
    assert state.golfer.fatigue_mental >= mental_before + 6
    assert state.season.current_week == 2
    last_result = state.last_tournament_result
    assert last_result is not None
    assert last_result.position == "NP"
    assert last_result.tournament_name == "Test Open"


def test_tournament_yields_prize_and_advances_week(tmp_path):
    repo = build_repository(tmp_path)
    engine = SimulationEngine(repository=repo, seed=42)

    initial_money = engine.get_state().golfer.money
    state = engine.perform_action("tournament")
    # Tournament should increase fatigue and potentially money. Always at least 0.
    assert state.golfer.fatigue_physical >= 15
    assert state.golfer.fatigue_mental >= 9
    assert state.season.current_week == 2
    assert len(state.ledger) == 1
    assert state.ledger[0].action == "Tournoi"
    assert state.golfer.money == initial_money + state.ledger[0].money_delta
    result = state.last_tournament_result
    assert result is not None
    assert result.tournament_name == "Test Open"
    assert result.position in {"1er", "2e", "Top 5", "Top 25", "Top 80", "MC"}
    assert result.missed_cut is (result.position == "MC")
    assert result.net_money == state.ledger[-1].money_delta
    assert result.prize_money >= 0
    assert result.entry_fee >= 0
    assert result.message
    assert len(result.round_scores) == 4
    assert all(score is None or isinstance(score, int) for score in result.round_scores)
    assert result.week == 1
    assert len(state.season_results) == 1
    assert state.season_summary is None
    assert len(state.season_rankings) == 200
    assert any(entry["is_user"] for entry in state.season_rankings if entry["name"] == "Test Player")


def test_tournament_entry_fee_applies_on_loss(tmp_path):
    config = {
        "season_length": 1,
        "initial_player": {
            "name": "Test Player",
            "age": 18,
            "skills": {"driving": 40, "approach": 40, "short_game": 40, "putting": 40},
            "fatigue_physical": 0,
            "fatigue_mental": 0,
            "form": 40,
            "money": 800,
            "reputation": 0,
            "motivation": 40,
        },
        "training": {"physical_fatigue": 10, "mental_fatigue": 6, "cost": 0, "skill_increase": 2},
        "rest": {"physical_recovery": 10, "mental_recovery": 8, "form_gain": 1},
        "tournament": {
            "physical_fatigue": 12,
            "mental_fatigue": 7,
            "entry_fee": 400,
            "motivation_per_1000": 0.5,
            "motivation_per_reputation": 1.0,
            "motivation_loss_on_miss": 5,
        },
        "agent_chat": {"motivation_boost": 5, "mental_recovery": 4},
        "tournaments": [
            {
                "name": "Difficult Event",
                "week": 1,
                "difficulty": 0.9,
                "purse": 300,
                "entry_fee": 400,
                "reputation_reward": 1,
            }
        ],
    }
    config_path = tmp_path / "config_loss.json"
    state_path = tmp_path / "state_loss.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    repo = StateRepository(config_path=config_path, state_path=state_path)
    engine = SimulationEngine(repository=repo, seed=2)

    initial_money = engine.get_state().golfer.money
    state = engine.perform_action("tournament")

    assert state.golfer.money == initial_money - 400
    assert state.ledger[-1].money_delta == -400
    result = state.last_tournament_result
    assert result is not None
    assert len(result.round_scores) == 4
    assert result.round_scores[2] is None
    assert result.round_scores[3] is None
    assert result.week == 1
    assert len(state.season_results) == 1
    assert state.season_summary is not None
    summary = state.season_summary
    assert summary.get('tournaments')[0]['position'] == result.position
    assert len(state.season_rankings) == 200
    assert any(entry["is_user"] for entry in state.season_rankings if entry["name"] == "Test Player")


def test_agent_chat_recovers_mental_fatigue_and_boosts_motivation(tmp_path):
    repo = build_repository(tmp_path)
    engine = SimulationEngine(repository=repo, seed=1)

    # Accumulate some mental fatigue through training
    engine.perform_action("train", {"skill": "driving"})
    state_before_chat = engine.get_state()
    mental_before = state_before_chat.golfer.fatigue_mental
    motivation_before = state_before_chat.golfer.motivation

    state_after_chat = engine.perform_action("agent_chat")

    assert state_after_chat.golfer.fatigue_mental <= mental_before
    assert state_after_chat.golfer.motivation >= motivation_before
    # agent chat should not have advanced the calendar week
    assert state_after_chat.season.current_week == state_before_chat.season.current_week
