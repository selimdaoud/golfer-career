"""Domain models for the golfer career simulation."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


@dataclass
class Tournament:
    """Representation of a tournament in the season calendar."""

    name: str
    week: int
    difficulty: float
    purse: int
    reputation_reward: int
    entry_fee: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict) -> "Tournament":
        return cls(
            name=data["name"],
            week=data["week"],
            difficulty=float(data["difficulty"]),
            purse=int(data["purse"]),
            reputation_reward=int(data.get("reputation_reward", 0)),
            entry_fee=(None if "entry_fee" not in data else int(data.get("entry_fee"))),
        )

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class LedgerEntry:
    """A single entry in the financial ledger."""

    week: int
    action: str
    description: str
    money_delta: int
    fatigue_physical_delta: int
    fatigue_mental_delta: int
    reputation_delta: int
    motivation_delta: int = 0
    skill_changes: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "LedgerEntry":
        # Legacy states may persist a single "fatigue_delta" field. When present,
        # we interpret it as a physical fatigue delta and assume no mental change.
        fatigue_physical_delta = int(data.get("fatigue_physical_delta", data.get("fatigue_delta", 0)))
        fatigue_mental_delta = int(data.get("fatigue_mental_delta", 0))
        return cls(
            week=int(data["week"]),
            action=data["action"],
            description=data["description"],
            money_delta=int(data.get("money_delta", 0)),
            fatigue_physical_delta=fatigue_physical_delta,
            fatigue_mental_delta=fatigue_mental_delta,
            reputation_delta=int(data.get("reputation_delta", 0)),
            motivation_delta=int(data.get("motivation_delta", 0)),
            skill_changes={k: int(v) for k, v in data.get("skill_changes", {}).items()},
        )


@dataclass
class TournamentResult:
    """Summary of the player's latest tournament outcome."""

    week: int
    tournament_name: str
    position: str
    missed_cut: bool
    performance: float
    entry_fee: int
    prize_money: int
    net_money: int
    reputation_delta: int
    motivation_delta: int
    message: str
    round_scores: List[Optional[int]] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "TournamentResult":
        return cls(
            week=int(data.get("week", 0)),
            tournament_name=data["tournament_name"],
            position=data["position"],
            missed_cut=bool(data.get("missed_cut", False)),
            performance=float(data.get("performance", 0.0)),
            entry_fee=int(data.get("entry_fee", 0)),
            prize_money=int(data.get("prize_money", 0)),
            net_money=int(data.get("net_money", 0)),
            reputation_delta=int(data.get("reputation_delta", 0)),
            motivation_delta=int(data.get("motivation_delta", 0)),
            message=data.get("message", ""),
            round_scores=[None if score is None else int(score) for score in data.get("round_scores", [])],
        )


@dataclass
class SeasonPlayer:
    """Represents an AI competitor tracked across the season."""

    player_id: str
    name: str
    base_skill: float
    earnings: int = 0
    points: int = 0
    events_played: int = 0
    cuts_made: int = 0
    wins: int = 0
    last_result: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "base_skill": self.base_skill,
            "earnings": self.earnings,
            "points": self.points,
            "events_played": self.events_played,
            "cuts_made": self.cuts_made,
            "wins": self.wins,
            "last_result": self.last_result,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "SeasonPlayer":
        return cls(
            player_id=data["player_id"],
            name=data["name"],
            base_skill=float(data.get("base_skill", 50)),
            earnings=int(data.get("earnings", 0)),
            points=int(data.get("points", 0)),
            events_played=int(data.get("events_played", 0)),
            cuts_made=int(data.get("cuts_made", 0)),
            wins=int(data.get("wins", 0)),
            last_result=data.get("last_result"),
        )


@dataclass
class PlayerSeasonStats:
    """Season tracking for the user-controlled golfer."""

    player_id: str
    earnings: int = 0
    points: int = 0
    events_played: int = 0
    cuts_made: int = 0
    wins: int = 0
    last_result: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "PlayerSeasonStats":
        return cls(
            player_id=data.get("player_id", "USER"),
            earnings=int(data.get("earnings", 0)),
            points=int(data.get("points", 0)),
            events_played=int(data.get("events_played", 0)),
            cuts_made=int(data.get("cuts_made", 0)),
            wins=int(data.get("wins", 0)),
            last_result=data.get("last_result"),
        )


@dataclass
class Golfer:
    """Main actor of the simulation."""

    name: str
    age: int
    skills: Dict[str, int]
    fatigue_physical: int
    fatigue_mental: int
    form: int
    money: int
    reputation: int
    motivation: int

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "Golfer":
        return cls(
            name=data["name"],
            age=int(data["age"]),
            skills={k: int(v) for k, v in data["skills"].items()},
            fatigue_physical=int(data.get("fatigue_physical", data.get("fatigue", 0))),
            fatigue_mental=int(data.get("fatigue_mental", 0)),
            form=int(data.get("form", 0)),
            money=int(data.get("money", 0)),
            reputation=int(data.get("reputation", 0)),
            motivation=int(data.get("motivation", 50)),
        )


@dataclass
class Season:
    """Holds progression information for the current season."""

    current_week: int
    total_weeks: int
    tournaments: List[Tournament]

    def to_dict(self) -> Dict:
        return {
            "current_week": self.current_week,
            "total_weeks": self.total_weeks,
            "tournaments": [t.to_dict() for t in self.tournaments],
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Season":
        return cls(
            current_week=int(data.get("current_week", 1)),
            total_weeks=int(data["total_weeks"]),
            tournaments=[Tournament.from_dict(t) for t in data.get("tournaments", [])],
        )

    def lookup_tournament(self, week: int) -> Optional[Tournament]:
        return next((t for t in self.tournaments if t.week == week), None)


@dataclass
class SimulationState:
    """Aggregated state persisted by the simulation."""

    golfer: Golfer
    season: Season
    ledger: List[LedgerEntry] = field(default_factory=list)
    last_tournament_result: Optional[TournamentResult] = None
    season_players: List[SeasonPlayer] = field(default_factory=list)
    player_stats: Optional[PlayerSeasonStats] = None
    season_rankings: List[Dict] = field(default_factory=list)
    season_results: List[TournamentResult] = field(default_factory=list)
    season_summary: Optional[Dict] = None
    last_message: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "golfer": self.golfer.to_dict(),
            "season": self.season.to_dict(),
            "ledger": [entry.to_dict() for entry in self.ledger],
            "last_tournament_result": (
                self.last_tournament_result.to_dict() if self.last_tournament_result else None
            ),
            "season_players": [player.to_dict() for player in self.season_players],
            "player_stats": self.player_stats.to_dict() if self.player_stats else None,
            "season_rankings": self.season_rankings,
            "season_results": [result.to_dict() for result in self.season_results],
            "season_summary": self.season_summary,
            "last_message": self.last_message,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "SimulationState":
        return cls(
            golfer=Golfer.from_dict(data["golfer"]),
            season=Season.from_dict(data["season"]),
            ledger=[LedgerEntry.from_dict(entry) for entry in data.get("ledger", [])],
            last_tournament_result=(
                TournamentResult.from_dict(data["last_tournament_result"])
                if data.get("last_tournament_result")
                else None
            ),
            season_players=[SeasonPlayer.from_dict(item) for item in data.get("season_players", [])],
            player_stats=(
                PlayerSeasonStats.from_dict(data["player_stats"])
                if data.get("player_stats")
                else None
            ),
            season_rankings=list(data.get("season_rankings", [])),
            season_results=[
                TournamentResult.from_dict(item) for item in data.get("season_results", [])
            ],
            season_summary=data.get("season_summary"),
            last_message=data.get("last_message"),
        )
