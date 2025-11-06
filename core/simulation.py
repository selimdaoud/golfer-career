"""Core simulation logic for the golfer career game."""
from __future__ import annotations

import random
from typing import Dict, List, Optional

from domain.models import (
    LedgerEntry,
    PlayerSeasonStats,
    SeasonPlayer,
    SimulationState,
    Tournament,
    TournamentResult,
)
from persistence.storage import StateRepository


class SimulationEngine:
    """Encapsulates the business rules for the simulation."""

    def __init__(self, repository: StateRepository, seed: Optional[int] = None) -> None:
        self.repository = repository
        self._random = random.Random(seed)
        self.state = self.repository.load_state()
        self._ensure_season_players()
        self._ensure_player_stats()
        if self.state.season_results is None:
            self.state.season_results = []
        if self.state.season_summary is None:
            self.state.season_summary = None
        self.state.season_rankings = self._build_season_rankings()
        self._fatigue_floor = 0
        self._fatigue_ceiling = 100
        self._motivation_floor = 0
        self._motivation_ceiling = 100
        self._tournament_processed = False

    # ------------------------------------------------------------------
    # Public API
    def get_state(self) -> SimulationState:
        return self.state

    def reset(self) -> SimulationState:
        self.state = self.repository.reset_state()
        self._ensure_season_players()
        self._ensure_player_stats()
        self.state.season_rankings = self._build_season_rankings()
        self.state.season_results = []
        self.state.season_summary = None
        self._tournament_processed = False
        return self.state

    def perform_action(self, action: str, payload: Optional[Dict] = None) -> SimulationState:
        payload = dict(payload or {})
        skip_advance = bool(payload.pop("skip_advance", False))
        action = action.lower()
        self._tournament_processed = False

        if self._season_completed:
            self.state.last_message = "La saison est terminée. Veuillez redémarrer pour continuer."
            self._finalize_season_summary()
            return self.state

        if action == "train":
            self._handle_training(payload)
        elif action == "rest":
            self._handle_rest()
        elif action == "tournament":
            self._handle_tournament(payload)
        elif action == "agent_chat":
            self._handle_agent_chat(payload)
        else:
            raise ValueError(f"Action inconnue: {action}")

        # Agent chat is designed as an auxiliary interaction that does not
        # consume a calendar week. All other actions advance the schedule.
        if action != "agent_chat" and not skip_advance:
            self._advance_week()
        if self._season_completed:
            if action == "tournament" and self.state.last_message:
                self.state.last_message += " Saison terminée !"
            self._finalize_season_summary()
        self.state.season_rankings = self._build_season_rankings()
        self.repository.save_state(self.state)
        return self.state

    # ------------------------------------------------------------------
    # Internal helpers
    def _handle_training(self, payload: Dict) -> None:
        rules = self.repository.training_rules
        skill = payload.get("skill")
        if not skill:
            # default to best return (random skill)
            skill = self._random.choice(list(self.state.golfer.skills.keys()))

        skill_increase = int(rules.get("skill_increase", 2))
        self.state.golfer.skills[skill] = self.state.golfer.skills.get(skill, 0) + skill_increase
        physical_change = int(rules.get("physical_fatigue", rules.get("fatigue", 10)))
        mental_change = int(rules.get("mental_fatigue", max(physical_change // 2, 0)))
        cost = int(rules.get("cost", 0))

        self.state.golfer.fatigue_physical = self._bounded_fatigue(
            self.state.golfer.fatigue_physical + physical_change
        )
        self.state.golfer.fatigue_mental = self._bounded_fatigue(
            self.state.golfer.fatigue_mental + mental_change
        )
        self.state.golfer.money -= cost
        self.state.golfer.form = min(100, self.state.golfer.form + 1)

        entry = LedgerEntry(
            week=self.state.season.current_week,
            action="Entraînement",
            description=f"Séance de travail sur {skill}",
            money_delta=-cost,
            fatigue_physical_delta=physical_change,
            fatigue_mental_delta=mental_change,
            reputation_delta=0,
            motivation_delta=0,
            skill_changes={skill: skill_increase},
        )
        self._append_ledger(entry)
        self.state.last_message = (
            "Entraînement effectué sur {skill}. Compétence +{skill_increase}, "
            "fatigue physique +{physical_change}, fatigue mentale +{mental_change}."
        ).format(
            skill=skill,
            skill_increase=skill_increase,
            physical_change=physical_change,
            mental_change=mental_change,
        )

    def _handle_rest(self) -> None:
        rules = self.repository.rest_rules
        physical_recovery = int(rules.get("physical_recovery", rules.get("fatigue_recovery", 15)))
        mental_recovery = int(rules.get("mental_recovery", physical_recovery // 2))
        form_gain = int(rules.get("form_gain", 7))

        previous_physical = self.state.golfer.fatigue_physical
        previous_mental = self.state.golfer.fatigue_mental
        self.state.golfer.fatigue_physical = self._bounded_fatigue(
            previous_physical - physical_recovery
        )
        self.state.golfer.fatigue_mental = self._bounded_fatigue(
            previous_mental - mental_recovery
        )
        self.state.golfer.form = min(100, self.state.golfer.form + form_gain)

        entry = LedgerEntry(
            week=self.state.season.current_week,
            action="Repos",
            description="Semaine de repos",
            money_delta=0,
            fatigue_physical_delta=self.state.golfer.fatigue_physical - previous_physical,
            fatigue_mental_delta=self.state.golfer.fatigue_mental - previous_mental,
            reputation_delta=0,
            motivation_delta=0,
        )
        self._append_ledger(entry)
        self.state.last_message = (
            "Repos bien mérité. Fatigue physique {prev_phy}->{new_phy}, "
            "fatigue mentale {prev_ment}->{new_ment}, forme +{form_gain}."
        ).format(
            prev_phy=previous_physical,
            new_phy=self.state.golfer.fatigue_physical,
            prev_ment=previous_mental,
            new_ment=self.state.golfer.fatigue_mental,
            form_gain=form_gain,
        )

    def _handle_tournament(self, payload: Dict) -> None:
        rules = self.repository.tournament_rules
        week = self.state.season.current_week
        tournament = self.state.season.lookup_tournament(week)
        if not tournament:
            self.state.last_message = "Aucun tournoi prévu cette semaine."
            self.state.last_tournament_result = None
            entry = LedgerEntry(
                week=week,
                action="Tournoi",
                description="Aucun tournoi disputé",
                money_delta=0,
                fatigue_physical_delta=0,
                fatigue_mental_delta=0,
                reputation_delta=0,
                motivation_delta=0,
            )
            self._append_ledger(entry)
            return

        physical_fatigue = int(rules.get("physical_fatigue", rules.get("fatigue", 18)))
        mental_fatigue = int(rules.get("mental_fatigue", max(physical_fatigue // 2, 0)))
        self.state.golfer.fatigue_physical = self._bounded_fatigue(
            self.state.golfer.fatigue_physical + physical_fatigue
        )
        self.state.golfer.fatigue_mental = self._bounded_fatigue(
            self.state.golfer.fatigue_mental + mental_fatigue
        )

        entry_fee = tournament.entry_fee
        if entry_fee is None:
            entry_fee = int(rules.get("entry_fee", 0))
        entry_fee = max(entry_fee, 0)
        if entry_fee:
            self.state.golfer.money -= entry_fee

        simulation = self._simulate_tournament(tournament)
        prize_money = simulation["prize_money"]
        reputation_gain = simulation["reputation_gain"]
        message = simulation["message"]
        self.state.golfer.money += prize_money
        net_money = prize_money - entry_fee
        self.state.golfer.reputation = max(0, self.state.golfer.reputation + reputation_gain)
        self.state.golfer.form = min(100, self.state.golfer.form + max(reputation_gain, 0))

        form_penalty_value = min(5, max(0, self.state.golfer.form))
        if form_penalty_value:
            self.state.golfer.form = max(0, self.state.golfer.form - form_penalty_value)

        motivation_delta = self._compute_motivation_from_tournament(net_money, reputation_gain, rules)
        actual_motivation_delta = self._adjust_motivation(motivation_delta)

        if actual_motivation_delta:
            message = f"{message} Motivation {'+' if actual_motivation_delta > 0 else ''}{actual_motivation_delta}."
        if form_penalty_value:
            message = f"{message} Forme -{form_penalty_value}."
        final_message = self._augment_tournament_message(message, entry_fee, net_money)
        final_message = self._add_result_to_message(final_message, simulation["position"])
        final_message = self._append_round_summary(final_message, simulation["round_summary"])
        skill_decay = self._apply_tournament_skill_decay()
        if skill_decay:
            decay_text = ", ".join(f"{skill} {delta:+d}" for skill, delta in skill_decay.items())
            final_message = f"{final_message} Compétences ajustées: {decay_text}."

        result_record = TournamentResult(
            week=week,
            tournament_name=tournament.name,
            position=simulation["position"],
            missed_cut=simulation["missed_cut"],
            performance=simulation["performance"],
            entry_fee=entry_fee,
            prize_money=prize_money,
            net_money=net_money,
            reputation_delta=reputation_gain,
            motivation_delta=actual_motivation_delta,
            message=final_message,
            round_scores=simulation["round_scores"],
        )
        self.state.last_tournament_result = result_record
        self.state.season_results.append(result_record)

        entry = LedgerEntry(
            week=week,
            action="Tournoi",
            description=final_message,
            money_delta=net_money,
            fatigue_physical_delta=physical_fatigue,
            fatigue_mental_delta=mental_fatigue,
            reputation_delta=reputation_gain,
            motivation_delta=actual_motivation_delta,
            skill_changes=skill_decay,
        )
        self._append_ledger(entry)
        self.state.last_message = final_message
        self._tournament_processed = True

    def _handle_agent_chat(self, payload: Dict) -> None:
        rules = self.repository.agent_chat_rules
        motivation_delta = int(payload.get("motivation_delta", rules.get("motivation_boost", 6)))
        mental_recovery = int(payload.get("mental_recovery", rules.get("mental_recovery", 5)))

        actual_motivation_delta = self._adjust_motivation(motivation_delta)
        previous_mental = self.state.golfer.fatigue_mental
        self.state.golfer.fatigue_mental = self._bounded_fatigue(
            previous_mental - mental_recovery
        )
        mental_delta = self.state.golfer.fatigue_mental - previous_mental

        entry = LedgerEntry(
            week=self.state.season.current_week,
            action="Discussion",
            description="Échange avec l'agent", 
            money_delta=0,
            fatigue_physical_delta=0,
            fatigue_mental_delta=mental_delta,
            reputation_delta=0,
            motivation_delta=actual_motivation_delta,
        )
        self._append_ledger(entry)
        self.state.last_message = (
            "Discussion avec l'agent. Motivation {sign}{motivation}, fatigue mentale {prev}->{new}."
        ).format(
            sign="+" if actual_motivation_delta >= 0 else "",
            motivation=actual_motivation_delta,
            prev=previous_mental,
            new=self.state.golfer.fatigue_mental,
        )

    def _advance_week(self) -> None:
        self._process_skipped_tournament()
        if self.state.season.current_week >= self.state.season.total_weeks:
            self.state.season.current_week = self.state.season.total_weeks + 1
        else:
            self.state.season.current_week += 1

    def _append_ledger(self, entry: LedgerEntry) -> None:
        self.state.ledger.append(entry)
        self.state.ledger = self.state.ledger[-50:]  # keep last entries only

    def _process_skipped_tournament(self) -> None:
        if self._tournament_processed:
            return
        week = self.state.season.current_week
        tournament = self.state.season.lookup_tournament(week)
        if not tournament:
            return
        result = self._simulate_tournament(tournament, include_player=False)
        self._tournament_processed = True
        message = result.get("message") or f"{tournament.name} disputé sans vous."
        winner_name = result.get("winner") or "un adversaire"
        summary = TournamentResult(
            week=week,
            tournament_name=tournament.name,
            position="NP",
            missed_cut=False,
            performance=0.0,
            entry_fee=0,
            prize_money=0,
            net_money=0,
            reputation_delta=0,
            motivation_delta=0,
            message=message,
            round_scores=[None, None, None, None],
        )
        self.state.last_tournament_result = summary
        self.state.season_results.append(summary)
        if self.state.last_message:
            self.state.last_message = f"{self.state.last_message} {message}"
        else:
            self.state.last_message = message

    @property
    def _season_completed(self) -> bool:
        return self.state.season.current_week > self.state.season.total_weeks

    # Tournament outcome helpers -----------------------------------------
    def _simulate_tournament(self, tournament: Tournament, include_player: bool = True) -> Dict:
        par_per_round = 72
        rounds = 4
        field_size = 200
        cut_count = 80
        week = self.state.season.current_week

        season_players = self._ensure_season_players()
        ai_slots = field_size - (1 if include_player else 0)
        ai_pool = season_players[:ai_slots]
        participants: List[Dict] = [
            self._build_ai_entry(ai_player, tournament, par_per_round, rounds)
            for ai_player in ai_pool
        ]

        if include_player:
            player_rounds = self._generate_player_rounds(tournament, par_per_round, rounds)
            participants.append(
                {
                    "raw_rounds": player_rounds,
                    "is_player": True,
                    "made_cut": False,
                    "season_player": None,
                }
            )

        for entry in participants:
            rounds_scores = entry["raw_rounds"]
            entry["first_two"] = sum(rounds_scores[:2])
            entry["total_raw"] = sum(rounds_scores)

        cut_order = sorted(
            participants,
            key=lambda item: (item["first_two"], item["raw_rounds"][1], item["raw_rounds"][0]),
        )
        for idx, entry in enumerate(cut_order):
            entry["made_cut"] = idx < cut_count

        for entry in participants:
            rounds_scores = entry["raw_rounds"]
            if entry["made_cut"]:
                entry["display_rounds"] = rounds_scores[:]
                entry["rounds_played"] = rounds
                entry["total_played"] = entry["total_raw"]
                entry["final_total"] = entry["total_raw"]
                entry["tie_break"] = rounds_scores[3]
            else:
                entry["display_rounds"] = rounds_scores[:2] + [None, None]
                entry["rounds_played"] = 2
                entry["total_played"] = entry["first_two"]
                entry["final_total"] = entry["first_two"] + 400  # push missed cuts to bottom
                entry["tie_break"] = rounds_scores[1]

        final_order = sorted(
            participants,
            key=lambda item: (item["final_total"], item["tie_break"], item["raw_rounds"][0]),
        )

        purse = tournament.purse
        base_rep = tournament.reputation_reward

        for placement, entry in enumerate(final_order, start=1):
            prize, reputation_gain, position_label, points = self._rank_outcome(
                placement, entry["made_cut"], purse, base_rep, cut_count
            )
            entry["rank"] = placement
            entry["prize"] = prize
            entry["reputation_gain"] = reputation_gain
            entry["position_label"] = position_label
            entry["points"] = points

        winner_entry = final_order[0] if final_order else None
        winner_name = (
            winner_entry["season_player"].name if winner_entry and winner_entry.get("season_player") else "un adversaire"
        )

        result: Dict[str, object]
        if include_player:
            player_entry = next(item for item in participants if item.get("is_player"))
            rank = final_order.index(player_entry) + 1
            made_cut = player_entry["made_cut"]
            percentile = 1.0 - ((rank - 1) / (field_size - 1))
            prize = player_entry["prize"]
            reputation = player_entry["reputation_gain"]
            position = player_entry["position_label"]
            round_summary = self._format_round_summary(player_entry["display_rounds"], par_per_round)
            if position == "1er":
                base_message = (
                    f"Victoire au {tournament.name} avec {player_entry['total_played']} coups "
                    f"({self._format_relative_score(player_entry['total_played'] - par_per_round * 4)})."
                )
            elif position == "2e":
                base_message = (
                    f"Podium au {tournament.name} avec {player_entry['total_played']} coups "
                    f"({self._format_relative_score(player_entry['total_played'] - par_per_round * 4)})."
                )
            elif position == "Top 5":
                base_message = (
                    f"Top 5 au {tournament.name}. Total {player_entry['total_played']} "
                    f"({self._format_relative_score(player_entry['total_played'] - par_per_round * 4)})."
                )
            elif position == "Top 25":
                base_message = (
                    f"Belle prestation au {tournament.name}. Total {player_entry['total_played']} "
                    f"({self._format_relative_score(player_entry['total_played'] - par_per_round * 4)})."
                )
            elif position == "Top 80":
                base_message = (
                    f"Week-end compliqué mais cut franchi au {tournament.name}. Total {player_entry['total_played']} "
                    f"({self._format_relative_score(player_entry['total_played'] - par_per_round * 4)})."
                )
            else:
                base_message = (
                    f"Coupe manquée au {tournament.name} après deux tours "
                    f"({self._format_relative_score(player_entry['total_played'] - par_per_round * 2)})."
                )
            self._update_player_stats(player_entry, position)
            result = {
                "include_player": True,
                "prize_money": prize,
                "reputation_gain": reputation,
                "position": position,
                "missed_cut": not made_cut,
                "performance": round(percentile * 100, 2),
                "round_summary": round_summary,
                "round_scores": player_entry["display_rounds"],
                "total_strokes": player_entry["total_played"],
                "points": player_entry["points"],
                "message": base_message,
                "final_order": final_order,
            }
        else:
            base_message = f"{tournament.name} disputé sans vous. Victoire de {winner_name}."
            result = {
                "include_player": False,
                "message": base_message,
                "final_order": final_order,
                "winner": winner_name,
            }

        self._update_ai_stats(final_order)
        self.state.season_rankings = self._build_season_rankings()

        return result

    def _player_round_expectation(self, tournament: Tournament, par_per_round: int) -> float:
        skills = self.state.golfer.skills or {"generic": 50}
        values = list(skills.values())
        average_skill = sum(values) / len(values)
        peak_skill = max(values)
        floor_skill = min(values)

        skill_adjust = (average_skill - 50) * 0.07
        specialty_bonus = max(0.0, peak_skill - average_skill) * 0.03
        weakness_penalty = max(0.0, average_skill - floor_skill) * 0.015
        motivation_bonus = (self.state.golfer.motivation - 50) * 0.04
        form_bonus = (self.state.golfer.form - 50) * 0.03
        fatigue_penalty = (self.state.golfer.fatigue_physical * 0.025) + (
            self.state.golfer.fatigue_mental * 0.03
        )
        difficulty_penalty = (tournament.difficulty - 0.5) * 3.5

        expected = (
            par_per_round
            + difficulty_penalty
            - skill_adjust
            - specialty_bonus
            - motivation_bonus
            - form_bonus
            + weakness_penalty
            + fatigue_penalty
        )
        return max(64.0, min(85.0, expected))

    def _format_relative_score(self, delta: int) -> str:
        if delta > 0:
            return f"+{delta}"
        if delta < 0:
            return f"{delta}"
        return "E"

    def _format_round_summary(self, rounds: List[Optional[int]], par: int) -> str:
        segments = []
        for idx, score in enumerate(rounds, start=1):
            if score is None:
                segments.append(f"R{idx} --")
            else:
                delta = score - par
                delta_text = self._format_relative_score(delta)
                segments.append(f"R{idx} {score} ({delta_text})")
        return "Scores: " + ", ".join(segments) + "."

    def _generate_player_rounds(self, tournament: Tournament, par_per_round: int, rounds: int) -> List[int]:
        expectation = self._player_round_expectation(tournament, par_per_round)
        fatigue_drift = (self.state.golfer.fatigue_physical + self.state.golfer.fatigue_mental) / 220.0
        round_std = 1.6 + (self.state.golfer.fatigue_mental / 220.0)
        scores: List[int] = []
        for round_index in range(rounds):
            mean = expectation + round_index * fatigue_drift
            score = int(round(self._random.gauss(mean, round_std)))
            scores.append(max(60, min(95, score)))
        return scores

    def _build_ai_entry(
        self, season_player: SeasonPlayer, tournament: Tournament, par_per_round: int, rounds: int
    ) -> Dict:
        expectation = self._ai_round_expectation(season_player, tournament, par_per_round)
        drift = self._random.gauss(0.2 + tournament.difficulty * 0.3, 0.12)
        base_std = max(1.1, 2.5 - (season_player.base_skill / 35.0))
        rounds_scores: List[int] = []
        for round_index in range(rounds):
            mean = expectation + round_index * drift
            std = base_std + round_index * 0.05
            score = int(round(self._random.gauss(mean, std)))
            rounds_scores.append(max(60, min(96, score)))
        return {
            "raw_rounds": rounds_scores,
            "is_player": False,
            "season_player": season_player,
            "made_cut": False,
        }

    def _ai_round_expectation(self, season_player: SeasonPlayer, tournament: Tournament, par_per_round: int) -> float:
        skill_adjust = (season_player.base_skill - 55) * 0.08
        difficulty_penalty = (tournament.difficulty - 0.5) * 3.0
        form_variance = self._random.gauss(0, 0.6)
        expected = par_per_round + difficulty_penalty - skill_adjust + form_variance
        return max(65.0, min(88.0, expected))

    def _rank_outcome(
        self, rank: int, made_cut: bool, purse: int, base_rep: int, cut_count: int
    ) -> tuple[int, int, str, int]:
        prize = self._prize_for_rank(rank, purse)
        points = self._points_for_rank(rank)
        if rank == 1:
            return prize, base_rep + 2, "1er", points
        if rank == 2:
            return prize, base_rep + 1, "2e", points
        if rank <= 5:
            return prize, base_rep, "Top 5", points
        if rank <= 25:
            return prize, max(1, base_rep - 1), "Top 25", points
        if made_cut and rank <= cut_count:
            return prize, max(0, base_rep - 2), "Top 80", points
        return prize, -2, "MC", points

    def _prize_for_rank(self, rank: int, purse: int) -> int:
        distribution = {
            1: 0.18,
            2: 0.109,
            3: 0.069,
            4: 0.049,
            5: 0.041,
            6: 0.036,
            7: 0.033,
            8: 0.031,
            9: 0.029,
            10: 0.027,
        }
        if rank in distribution:
            share = distribution[rank]
        elif rank <= 30:
            share = max(0.015, 0.026 - 0.0006 * (rank - 10))
        elif rank <= 80:
            share = max(0.004, 0.014 - 0.00018 * (rank - 30))
        else:
            share = 0.0
        return int(purse * share)

    def _points_for_rank(self, rank: int) -> int:
        if rank == 1:
            return 500
        if rank == 2:
            return 320
        if rank == 3:
            return 230
        if rank == 4:
            return 180
        if rank == 5:
            return 160
        if rank <= 10:
            return 140 - (rank - 6) * 10
        if rank <= 25:
            return 90 - (rank - 11) * 4
        if rank <= 80:
            return max(5, 34 - (rank - 26))
        return 0

    def _update_player_stats(self, player_entry: Dict, position: str) -> None:
        stats = self._ensure_player_stats()
        stats.events_played += 1
        if player_entry["made_cut"]:
            stats.cuts_made += 1
        if position == "1er":
            stats.wins += 1
        stats.earnings += player_entry["prize"]
        stats.points += player_entry["points"]
        stats.last_result = position

    def _update_ai_stats(self, final_order: List[Dict]) -> None:
        for entry in final_order:
            season_player = entry.get("season_player")
            if not season_player:
                continue
            season_player.events_played += 1
            if entry["made_cut"]:
                season_player.cuts_made += 1
            if entry["rank"] == 1:
                season_player.wins += 1
            season_player.earnings += entry["prize"]
            season_player.points += entry["points"]
            season_player.last_result = entry["position_label"]

    def _ensure_season_players(self) -> List[SeasonPlayer]:
        target = 199
        if not self.state.season_players:
            avg_skill = self._user_average_skill()
            self.state.season_players = self._generate_season_players(target, avg_skill=avg_skill)
        elif len(self.state.season_players) < target:
            avg_skill = self._user_average_skill()
            needed = target - len(self.state.season_players)
            self.state.season_players.extend(
                self._generate_season_players(
                    needed, start=len(self.state.season_players) + 1, avg_skill=avg_skill
                )
            )
        return self.state.season_players

    def _generate_season_players(self, count: int, start: int = 1, avg_skill: float = 52.0) -> List[SeasonPlayer]:
        players: List[SeasonPlayer] = []
        for idx in range(start, start + count):
            player_id = f"P{idx:03d}"
            name = f"Pro {idx:03d}"
            base_skill = max(40.0, min(70.0, avg_skill + self._random.gauss(0, 4.0)))
            players.append(
                SeasonPlayer(
                    player_id=player_id,
                    name=name,
                    base_skill=base_skill,
                )
            )
        return players

    def _user_average_skill(self) -> float:
        skills = self.state.golfer.skills or {"generic": 52}
        return sum(skills.values()) / max(1, len(skills))

    def _ensure_player_stats(self) -> PlayerSeasonStats:
        if not self.state.player_stats:
            self.state.player_stats = PlayerSeasonStats(player_id="USER")
        return self.state.player_stats

    def _build_season_rankings(self) -> List[Dict]:
        rankings: List[Dict] = []
        stats = self._ensure_player_stats()
        rankings.append(
            {
                "player_id": stats.player_id,
                "name": self.state.golfer.name,
                "earnings": stats.earnings,
                "points": stats.points,
                "events": stats.events_played,
                "cuts": stats.cuts_made,
                "wins": stats.wins,
                "last_result": stats.last_result or "-",
                "is_user": True,
            }
        )
        for player in self._ensure_season_players():
            rankings.append(
                {
                    "player_id": player.player_id,
                    "name": player.name,
                    "earnings": player.earnings,
                    "points": player.points,
                    "events": player.events_played,
                    "cuts": player.cuts_made,
                    "wins": player.wins,
                    "last_result": player.last_result or "-",
                    "is_user": False,
                }
            )
        rankings.sort(key=lambda item: (item["points"], item["earnings"]), reverse=True)
        for idx, entry in enumerate(rankings, start=1):
            entry["rank"] = idx
        return rankings

    def _finalize_season_summary(self) -> None:
        if self.state.season_summary:
            return
        rankings = self._build_season_rankings()
        self.state.season_rankings = rankings
        tournaments = []
        for result in sorted(self.state.season_results, key=lambda r: r.week):
            total_strokes = sum(score for score in result.round_scores if score is not None)
            tournaments.append(
                {
                    "week": result.week,
                    "tournament_name": result.tournament_name,
                    "position": result.position,
                    "message": result.message,
                    "round_scores": result.round_scores,
                    "total_strokes": total_strokes,
                    "net_money": result.net_money,
                    "prize_money": result.prize_money,
                }
            )
        ledger_totals: Dict[str, Dict[str, int]] = {}
        total_gains = 0
        total_expenses = 0
        for entry in self.state.ledger:
            bucket = ledger_totals.setdefault(
                entry.action, {"gains": 0, "depenses": 0, "net": 0}
            )
            delta = entry.money_delta
            if delta >= 0:
                bucket["gains"] += delta
                total_gains += delta
            else:
                bucket["depenses"] += -delta
                total_expenses += -delta
            bucket["net"] += delta
        ledger_totals["TOTAL"] = {
            "gains": total_gains,
            "depenses": total_expenses,
            "net": total_gains - total_expenses,
        }
        player_stats = self._ensure_player_stats().to_dict()
        player_rank_entry = next((entry for entry in rankings if entry.get("is_user")), None)
        if player_rank_entry:
            player_stats["rank"] = player_rank_entry.get("rank")
        self.state.season_summary = {
            "rankings": rankings,
            "tournaments": tournaments,
            "ledger_totals": ledger_totals,
            "player": player_stats,
        }

    def _compute_motivation_from_tournament(
        self, net_money: int, reputation_gain: int, rules: Dict
    ) -> int:
        motivation_per_1000 = float(rules.get("motivation_per_1000", 0.6))
        loss_penalty = int(rules.get("motivation_loss_on_miss", 6))
        reputation_factor = float(rules.get("motivation_per_reputation", 0.5))

        if net_money > 0:
            motivation_from_money = int(net_money * motivation_per_1000 / 1000)
            motivation_from_reputation = int(max(reputation_gain, 0) * reputation_factor)
            return motivation_from_money + motivation_from_reputation
        return -loss_penalty

    def _augment_tournament_message(self, base: str, entry_fee: int, net_money: int) -> str:
        if entry_fee <= 0:
            return base
        net_text = f"Résultat net {net_money:+d} crédits."
        return f"{base} Frais d'inscription {entry_fee} crédits. {net_text}"

    def _add_result_to_message(self, base: str, position: str) -> str:
        if not position:
            return base
        suffix = f" Résultat: {position}."
        if base.endswith("."):
            return f"{base}{suffix}"
        return f"{base}.{' ' if not base.endswith(' ') else ''}Résultat: {position}."

    def _append_round_summary(self, base: str, summary: str) -> str:
        if not summary:
            return base
        separator = " " if base.endswith(".") else ". "
        return f"{base}{separator}{summary}"

    def _apply_tournament_skill_decay(self) -> Dict[str, int]:
        changes: Dict[str, int] = {}
        for skill, value in self.state.golfer.skills.items():
            if value <= 0:
                continue
            percent = self._random.randint(1, 3)
            reduction = max(1, int(round(value * percent / 100)))
            new_value = max(0, value - reduction)
            self.state.golfer.skills[skill] = new_value
            changes[skill] = new_value - value
        return changes

    def _adjust_motivation(self, delta: int) -> int:
        previous = self.state.golfer.motivation
        new_value = min(self._motivation_ceiling, max(self._motivation_floor, previous + delta))
        self.state.golfer.motivation = new_value
        return new_value - previous

    def _bounded_fatigue(self, value: int) -> int:
        return min(self._fatigue_ceiling, max(self._fatigue_floor, value))
