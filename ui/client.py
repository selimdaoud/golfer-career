"""Curses based client for the golfer career simulator."""
from __future__ import annotations

import argparse
import curses
import textwrap
import time
from collections import Counter
from typing import Any, Dict, List, Tuple

import requests


def fetch_state(base_url: str) -> Dict:
    response = requests.get(f"{base_url}/state", timeout=5)
    response.raise_for_status()
    return response.json()


def post_action(base_url: str, action: str, payload: Dict | None = None) -> Dict:
    data = {"action": action}
    if payload:
        data.update(payload)
    response = requests.post(f"{base_url}/action", json=data, timeout=10)
    if response.status_code >= 400:
        raise RuntimeError(response.json().get("detail", "Erreur inconnue"))
    return response.json()


class ClientApp:
    def __init__(self, base_url: str, admin_mode: bool) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_mode = admin_mode
        self.state: Dict | None = None
        self._color_pairs: Dict[str, int] = {}
        self._leaderboard_offset: int = 0

    def run(self) -> None:
        curses.wrapper(self._mainloop)

    # ------------------------------------------------------------------
    def _mainloop(self, stdscr) -> None:
        curses.curs_set(False)
        stdscr.nodelay(False)
        stdscr.timeout(-1)
        self._setup_colors()

        self._auto_reset()
        self._show_intro_popup(stdscr)

        while True:
            self.state = fetch_state(self.base_url)
            self._render(stdscr)
            choice = stdscr.getkey()
            if choice.lower() == "q":
                break
            self._handle_choice(stdscr, choice)

    def _handle_choice(self, stdscr, choice: str) -> None:
        if choice == "KEY_UP":
            self._adjust_leaderboard(-1)
            return
        if choice == "KEY_DOWN":
            self._adjust_leaderboard(1)
            return
        if choice == "KEY_PPAGE":
            self._adjust_leaderboard(-10)
            return
        if choice == "KEY_NPAGE":
            self._adjust_leaderboard(10)
            return
        if choice in {"k", "K"}:
            self._adjust_leaderboard(-1)
            return
        if choice in {"j", "J"}:
            self._adjust_leaderboard(1)
            return
        if choice == "1":
            self._training_flow(stdscr)
        elif choice == "2":
            self._execute_action(stdscr, "tournament")
        elif choice == "3":
            self._execute_action(stdscr, "rest")
        elif choice == "4":
            self._execute_action(stdscr, "agent_chat")
        elif choice.lower() == "r":
            self._reset_state(stdscr)
        else:
            self._notify(stdscr, "Choix invalide. Utilisez 1/2/3/4 ou q.")

    def _training_flow(self, stdscr) -> None:
        assert self.state is not None
        executed: List[str] = []
        pending: str | None = None
        max_sessions = 5
        while True:
            remaining = max_sessions - (len(executed) + (1 if pending else 0))
            if remaining <= 0:
                break
            skills = self.state["golfer"]["skills"]
            options = list(skills.keys())
            choice = self._prompt_training_choice(
                stdscr,
                selections=len(executed) + (1 if pending else 0),
                max_sessions=max_sessions,
                options=options,
                skills=skills,
            )
            if choice is None:
                break
            selected = options[choice]
            if pending is not None:
                self._execute_training_session(stdscr, pending, skip_advance=True, silent=True)
                executed.append(pending)
            pending = selected
        if pending is not None:
            self._execute_training_session(stdscr, pending, skip_advance=False, silent=True)
            executed.append(pending)

    def _reset_state(self, stdscr) -> None:
        if not self._confirm(stdscr, "Confirmer le reset de la saison ?"):
            return
        response = requests.post(f"{self.base_url}/reset", timeout=10)
        if response.status_code == 200:
            self.state = response.json()
            self._notify(stdscr, "Saison réinitialisée.")
        else:
            self._notify(stdscr, "Impossible de réinitialiser l'état.")

    def _execute_action(self, stdscr, action: str, payload: Dict | None = None) -> None:
        previous_state = self.state
        payload = dict(payload) if payload else {}
        silent = bool(payload.pop("silent", False))
        try:
            self.state = post_action(self.base_url, action, payload)
        except RuntimeError as exc:
            self._notify(stdscr, str(exc))
        else:
            if action == "tournament" and self.state:
                prev_over = self._season_is_over(previous_state)
                curr_over = self._season_is_over(self.state)
                if curr_over and prev_over:
                    summary = self.state.get("season_summary")
                    if summary:
                        self._show_season_summary(stdscr, summary)
                    else:
                        if not silent:
                            self._notify(stdscr, self.state.get("last_message") or "Saison terminée.")
                    return
                result = self.state.get("last_tournament_result")
                tournament_name = (result or {}).get("tournament_name")
                if not tournament_name:
                    tournament_name = self._lookup_tournament_name(previous_state, post_action=False)
                if not tournament_name:
                    tournament_name = self._lookup_tournament_name(self.state, post_action=True)
                if not tournament_name:
                    tournament_name = "Tournoi en cours"
                self._show_tournament_animation(stdscr, tournament_name)
                if result:
                    self._show_tournament_popup(stdscr, result, self.state.get("last_message"))
                    if curr_over and (summary := self.state.get("season_summary")):
                        self._show_season_summary(stdscr, summary)
                    return
            if not silent and action not in {"rest", "agent_chat"}:
                self._notify(stdscr, self.state.get("last_message") or "Action effectuée.")

    def _notify(self, stdscr, message: str) -> None:
        height, width = stdscr.getmaxyx()
        lines = textwrap.wrap(message, width - 4)
        for idx, line in enumerate(lines[:3]):
            stdscr.addstr(height - 4 + idx, 2, line.ljust(width - 4))
        stdscr.refresh()
        stdscr.getch()

    def _auto_reset(self) -> None:
        """Reset season state when launching or relaunching the client."""
        try:
            response = requests.post(f"{self.base_url}/reset", timeout=10)
            response.raise_for_status()
        except requests.RequestException:
            return
        self.state = response.json()

    def _show_intro_popup(self, stdscr) -> None:
        """Display an introductory popup with controls and context."""
        intro_lines = [
            "Bienvenue dans GolfSim!",
            "",
            "Your name is Eric Miles, prodige impatient!",
            "36 semaines pour transformer un rookie en légende.",
            "Chaque action fait avancer le temps, alors planifiez malin!",
            "",
            "Contrôles:",
            " 1 - Entraînement (enchaînez jusqu'à 5 sessions)",
            " 2 - Jouer un tournoi (animation incluse!)",
            " 3 - Repos pour regagner de la forme",
            " 4 - Coach mental pour booster la motivation",
            " j/k ou flèches - Parcourir le classement",
            " r - Reset manuel (si vous insistez)",
            " q - Quitter la simulation",
            "",
            "Astuce: garder un peu d'énergie avant les gros tournois paye souvent!",
        ]
        height, width = stdscr.getmaxyx()
        content_width = min(70, width - 4)
        wrapped_lines = []
        for line in intro_lines:
            if line.strip():
                wrapped_lines.extend(textwrap.wrap(line, content_width))
            else:
                wrapped_lines.append("")
        box_height = len(wrapped_lines) + 4
        box_width = content_width + 4
        start_y = max(2, (height - box_height) // 2)
        start_x = max(2, (width - box_width) // 2)

        win = curses.newwin(box_height, box_width, start_y, start_x)
        win.border()
        title = " Saison fraîche, esprit frais! "
        if len(title) < box_width - 2:
            win.addstr(0, (box_width - len(title)) // 2, title)

        for idx, line in enumerate(wrapped_lines):
            win.addstr(1 + idx, 2, line.ljust(content_width))
        prompt = "Appuyez sur une touche pour lancer la saison!"
        win.addstr(box_height - 2, 2, prompt[: content_width])
        win.refresh()
        win.getch()
        win.clear()
        stdscr.touchwin()
        stdscr.refresh()

    def _write_segments(
        self,
        stdscr,
        row: int,
        col: int,
        segments: List[Tuple[str, Any]],
        width_limit: int | None = None,
    ) -> None:
        label_attr = self._color_pairs.get("label", curses.A_BOLD)
        value_attr = self._color_pairs.get("value", curses.A_NORMAL)
        max_width = stdscr.getmaxyx()[1]
        end_limit = col + (width_limit if width_limit is not None else max_width - col)
        cursor = col

        spacer = "  "
        for idx, (label, value) in enumerate(segments):
            if cursor >= end_limit:
                break
            label_text = f"{label}: "
            value_text = str(value)

            if cursor + len(label_text) > end_limit:
                break
            stdscr.addstr(row, cursor, label_text, label_attr)
            cursor += len(label_text)

            if cursor + len(value_text) > end_limit:
                truncated = value_text[: max(0, end_limit - cursor)]
                if truncated:
                    stdscr.addstr(row, cursor, truncated, value_attr)
                break
            stdscr.addstr(row, cursor, value_text, value_attr)
            cursor += len(value_text)

            if idx != len(segments) - 1:
                if cursor + len(spacer) > end_limit:
                    break
                stdscr.addstr(row, cursor, spacer)
                cursor += len(spacer)

    # Rendering ---------------------------------------------------------
    def _render(self, stdscr) -> None:
        assert self.state is not None
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        leaderboard_width = 32 if width >= 90 else 0
        main_width = width - (leaderboard_width + 1 if leaderboard_width else 0)
        content_limit = max(20, main_width - 4)

        header = "Simulateur de carrière - Mode Admin" if self.admin_mode else "Simulateur de carrière"
        stdscr.addstr(0, 2, header[: max(0, main_width - 4)])
        stdscr.hline(1, 0, ord("-"), min(width, max(1, main_width)))

        season = self.state["season"]
        golfer = self.state["golfer"]
        current_week = season["current_week"]
        total_weeks = season["total_weeks"]

        self._write_segments(
            stdscr,
            2,
            2,
            [
                ("Semaine", f"{min(current_week, total_weeks)}/{total_weeks}"),
            ],
            width_limit=main_width - 4,
        )
        self._write_segments(
            stdscr,
            3,
            2,
            [("Golfeur", f"{golfer['name']} (Âge {golfer['age']})")],
            width_limit=main_width - 4,
        )
        self._write_segments(
            stdscr,
            4,
            2,
            [
                ("Forme", golfer["form"]),
                ("Fatigue physique", golfer["fatigue_physical"]),
                ("Fatigue mentale", golfer["fatigue_mental"]),
            ],
            width_limit=main_width - 4,
        )
        self._write_segments(
            stdscr,
            5,
            2,
            [
                ("Réputation", golfer["reputation"]),
                ("Motivation", golfer["motivation"]),
            ],
            width_limit=main_width - 4,
        )
        self._render_money_line(stdscr, 6, 2, golfer, main_width)

        gauge_top = 7
        gauge_block = self._render_stat_gauges(stdscr, gauge_top, 2, main_width, golfer)
        skills_start = gauge_top + (gauge_block if gauge_block else 0) + 1
        stdscr.addstr(skills_start, 2, "Compétences:"[: max(0, main_width - 4)])
        for idx, (skill, value) in enumerate(golfer["skills"].items(), start=1):
            stdscr.addstr(skills_start + idx, 4, f"- {skill}: {value}"[: max(0, main_width - 6)])

        next_line = skills_start + len(golfer["skills"]) + 1
        result = self.state.get("last_tournament_result")
        if result:
            position = result.get("position", "")
            tournament_name = result.get("tournament_name", "Dernier tournoi")
            missed_cut = bool(result.get("missed_cut"))
            summary = f"Dernier tournoi: {tournament_name} - {position}"
            color = self._color_pairs.get("negative" if missed_cut else "positive", curses.A_NORMAL)
            stdscr.addstr(next_line, 2, summary[: max(0, main_width - 4)], color)
            next_line += 2

        last_message = self.state.get("last_message") or "Bienvenue dans la simulation."
        stdscr.addstr(next_line, 2, "Dernier événement:"[: max(0, main_width - 4)])
        wrap_width = max(10, main_width - 6)
        for idx, line in enumerate(textwrap.wrap(last_message, wrap_width)):
            stdscr.addstr(next_line + 1 + idx, 4, line[: max(0, main_width - 6)])
        next_line = next_line + 2 + idx if 'idx' in locals() else next_line + 2
        summary = self.state.get('season_summary')
        if summary and summary.get('rankings'):
            player_rank = next((entry['rank'] for entry in summary['rankings'] if entry.get('is_user')), None)
            if player_rank is not None:
                stdscr.addstr(next_line, 2, f"Classement final: {player_rank}e"[: max(0, main_width - 4)], curses.A_BOLD)
                next_line += 2

        actions_text = (
            "Actions: [1] Entraînement  [2] Tournoi  [3] Repos  "
            "[4] Discussion agent  [r] Reset  [q] Quitter"
        )
        stdscr.addstr(height - 6, 2, actions_text[: max(0, main_width - 4)])

        if self.admin_mode:
            ledger_start = max(next_line + 6, 22)
            self._render_ledger(stdscr, start_line=ledger_start, max_width=main_width)

        stdscr.refresh()
        if leaderboard_width:
            self._render_leaderboard(stdscr, leaderboard_width)

    def _render_ledger(self, stdscr, start_line: int, max_width: int) -> None:
        ledger = self.state.get("ledger", []) if self.state else []
        _, screen_width = stdscr.getmaxyx()
        width = max(0, min(max_width, screen_width - 2))
        if width <= 10:
            return
        stdscr.addstr(start_line, 2, "Historique récent:"[: width - 2])
        for idx, entry in enumerate(reversed(ledger[-5:])):
            week = entry["week"]
            action = entry["action"]
            money_delta = entry.get("money_delta", 0)
            fat_p = entry.get("fatigue_physical_delta", 0)
            fat_m = entry.get("fatigue_mental_delta", 0)
            mot = entry.get("motivation_delta", 0)

            y = start_line + idx + 1
            x = 4
            prefix = f"S{week} {action} | Δ€ "
            available = max(0, width - x - 2)
            prefix_fragment = prefix[:available]
            stdscr.addstr(y, x, prefix_fragment)
            x += len(prefix_fragment)
            delta_text = f"{money_delta:+d}"
            color_attr = self._color_for_money(money_delta)
            if x < width - 2:
                remaining = max(0, width - x - 2)
                delta_fragment = delta_text[:remaining]
                stdscr.addstr(y, x, delta_fragment, color_attr)
                x += len(delta_fragment)
            else:
                x += len(delta_text)
            suffix = f" | Δfatigue P {fat_p} / M {fat_m} | Δmot {mot}"
            if x < width - 2:
                remaining = max(0, width - x - 2)
                stdscr.addstr(y, x, suffix[:remaining])

    def _render_money_line(self, stdscr, row: int, col: int, golfer: Dict, width: int) -> None:
        money_line = f"Argent: {golfer['money']} crédits"
        available = max(0, width - col - 2)
        displayed = money_line[:available]
        stdscr.addstr(row, col, displayed)
        delta = self._last_money_delta()
        if delta == 0:
            return
        delta_text = f" ({delta:+d})"
        x = col + len(displayed)
        if x < width - 2:
            remaining = max(0, width - x - 2)
            stdscr.addstr(row, x, delta_text[:remaining], self._color_for_money(delta))

    def _execute_training_session(self, stdscr, skill: str, skip_advance: bool, silent: bool) -> None:
        payload: Dict[str, object] = {"skill": skill}
        if skip_advance:
            payload["skip_advance"] = True
        if silent:
            payload["silent"] = True
        self._execute_action(stdscr, "train", payload)

    def _format_training_summary(self, selections: List[str]) -> str:
        counter = Counter(selections)
        parts = []
        for skill, count in counter.items():
            parts.append(f"{skill} x{count}" if count > 1 else skill)
        return "Entraînement(s): " + ", ".join(parts)

    def _prompt_training_choice(
        self,
        stdscr,
        selections: int,
        max_sessions: int,
        options: List[str],
        skills: Dict[str, int],
    ) -> int | None:
        if not options:
            return None
        height, width = stdscr.getmaxyx()
        win_height = min(18, height - 4)
        win_width = min(width - 4, 64)
        win = curses.newwin(win_height, win_width, (height - win_height) // 2, (width - win_width) // 2)
        win.keypad(True)
        selected = 0
        instructions = "Utilisez ↑/↓ pour choisir, Entrée pour valider, q pour terminer"
        while True:
            win.erase()
            win.border()
            win.addstr(1, 2, f"Sélections: {selections}/{max_sessions}"[: win_width - 4], curses.A_BOLD)
            win.addstr(2, 2, instructions[: win_width - 4], curses.A_DIM)
            for idx, skill in enumerate(options):
                value = skills.get(skill, 0)
                label = f"[{idx + 1}] {skill} ({value})"
                attr = curses.A_REVERSE if idx == selected else curses.A_NORMAL
                win.addstr(4 + idx, 2, label[: win_width - 4], attr)
            win.refresh()
            key = win.getkey()
            if key.lower() == "q":
                return None
            if key in {"KEY_UP", "k"}:
                selected = (selected - 1) % len(options)
            elif key in {"KEY_DOWN", "j"}:
                selected = (selected + 1) % len(options)
            elif key in {"\n", "\r"}:
                return selected
            elif key.isdigit():
                value = int(key) - 1
                if 0 <= value < len(options):
                    return value
            else:
                curses.flash()

    def _prompt(self, stdscr, message: str, option_count: int) -> int | None:
        height, width = stdscr.getmaxyx()
        win_height = min(10, height - 4)
        win_width = min(width - 4, 60)
        win = curses.newwin(win_height, win_width, (height - win_height) // 2, (width - win_width) // 2)
        win.border()
        lines = message.split("\n")
        for idx, line in enumerate(lines[: win_height - 3]):
            win.addstr(1 + idx, 2, line[: win_width - 4])
        win.addstr(win_height - 2, 2, "Entrée: numéro ou q pour annuler")
        win.refresh()

        while True:
            key = win.getkey()
            if key.lower() == "q":
                return None
            if key.isdigit():
                value = int(key) - 1
                if 0 <= value < option_count:
                    return value
            curses.flash()

    def _setup_colors(self) -> None:
        if self._color_pairs or not curses.has_colors():
            return
        curses.start_color()
        background = -1
        try:
            curses.use_default_colors()
        except curses.error:
            background = curses.COLOR_BLACK
        for idx, (fg, key) in enumerate(
            ((curses.COLOR_RED, "negative"), (curses.COLOR_GREEN, "positive")), start=1
        ):
            try:
                curses.init_pair(idx, fg, background)
            except curses.error:
                curses.init_pair(idx, fg, curses.COLOR_BLACK)
            self._color_pairs[key] = curses.color_pair(idx)

        next_index = len(self._color_pairs) + 1
        gauge_pairs = [
            ("gauge_border", curses.COLOR_CYAN, background if background != -1 else curses.COLOR_BLACK),
            ("gauge_green", curses.COLOR_BLACK, curses.COLOR_GREEN),
            ("gauge_white", curses.COLOR_BLACK, curses.COLOR_WHITE),
            ("gauge_red", curses.COLOR_WHITE, curses.COLOR_RED),
        ]
        for key, fg, bg in gauge_pairs:
            try:
                curses.init_pair(next_index, fg, bg)
            except curses.error:
                fallback_bg = curses.COLOR_BLACK if bg != -1 else curses.COLOR_BLACK
                curses.init_pair(next_index, fg, fallback_bg)
            self._color_pairs[key] = curses.color_pair(next_index)
            next_index += 1

        label_value_pairs = [
            ("label", curses.COLOR_CYAN, background if background != -1 else curses.COLOR_BLACK),
            ("value", curses.COLOR_GREEN, background if background != -1 else curses.COLOR_BLACK),
        ]
        for key, fg, bg in label_value_pairs:
            try:
                curses.init_pair(next_index, fg, bg)
            except curses.error:
                curses.init_pair(next_index, fg, curses.COLOR_BLACK)
            self._color_pairs[key] = curses.color_pair(next_index)
            next_index += 1

    def _color_for_money(self, delta: int) -> int:
        if delta > 0:
            return self._color_pairs.get("positive", curses.A_NORMAL)
        if delta < 0:
            return self._color_pairs.get("negative", curses.A_NORMAL)
        return curses.A_NORMAL

    def _last_money_delta(self) -> int:
        if not self.state:
            return 0
        ledger = self.state.get("ledger") or []
        if not ledger:
            return 0
        return int(ledger[-1].get("money_delta", 0))

    def _adjust_leaderboard(self, delta: int) -> None:
        if not self.state:
            return
        rankings = self.state.get("season_rankings") or []
        if not rankings:
            return
        self._leaderboard_offset = max(0, self._leaderboard_offset + delta)

    def _render_stat_gauges(self, stdscr, top: int, left: int, width: int, golfer: Dict) -> int:
        metrics = [
            ("Forme", golfer.get("form", 0)),
            ("Fatigue physique", golfer.get("fatigue_physical", 0)),
            ("Fatigue mentale", golfer.get("fatigue_mental", 0)),
            ("Motivation", golfer.get("motivation", 0)),
            ("Réputation", min(100, golfer.get("reputation", 0))),
        ]
        if not metrics:
            return 0

        title = "Jauges du joueur"
        stdscr.addstr(top, left, title)
        line = top + 1
        label_width = max(len(label) for label, _ in metrics) + 2
        numeric_width = 4
        available_raw = width - left - label_width - numeric_width - 4
        gauge_width = min(40, max(0, available_raw))

        for label, value in metrics:
            self._draw_horizontal_gauge(
                stdscr,
                line,
                left,
                label,
                int(value),
                label_width,
                numeric_width,
                gauge_width,
            )
            line += 1
        return (line - top)

    def _draw_horizontal_gauge(
        self,
        stdscr,
        row: int,
        left: int,
        label: str,
        value: int,
        label_width: int,
        numeric_width: int,
        gauge_width: int,
    ) -> None:
        clamped = max(0, min(100, value))
        label_attr = self._color_pairs.get("label", curses.A_BOLD)
        value_attr = self._color_pairs.get("value", curses.A_NORMAL)
        stdscr.addstr(row, left, label.ljust(label_width), label_attr)
        stdscr.addstr(row, left + label_width, f"{clamped:>{numeric_width}d}", value_attr)
        gauge_start = left + label_width + numeric_width + 1
        if gauge_width >= 1:
            stdscr.addstr(row, gauge_start, "[")
            stdscr.addstr(row, gauge_start + gauge_width + 1, "]")

        filled = int(round((clamped / 100.0) * gauge_width)) if gauge_width else 0
        green_limit = int(round(gauge_width * 0.6))
        white_limit = int(round(gauge_width * 0.9))
        empty_attr = curses.A_DIM

        for idx in range(gauge_width):
            x = gauge_start + 1 + idx
            if idx < filled:
                if idx >= white_limit:
                    fill_key = "gauge_red"
                elif idx >= green_limit:
                    fill_key = "gauge_white"
                else:
                    fill_key = "gauge_green"
                attr = self._color_pairs.get(fill_key, curses.A_REVERSE)
            else:
                attr = empty_attr
            stdscr.addstr(row, x, " ", attr)

    def _render_leaderboard(self, stdscr, panel_width: int) -> None:
        if not self.state or panel_width <= 0:
            return
        rankings = self.state.get("season_rankings") or []
        if not rankings:
            return
        height, width = stdscr.getmaxyx()
        start_x = max(0, width - panel_width)
        win_height = max(5, height - 2)
        visible_rows = max(1, win_height - 2)
        max_offset = max(0, len(rankings) - visible_rows)
        if self._leaderboard_offset > max_offset:
            self._leaderboard_offset = max_offset
        if self._leaderboard_offset < 0:
            self._leaderboard_offset = 0
        win = curses.newwin(win_height, panel_width, 1, start_x)
        win.erase()
        win.border()
        title = "Classement Saison"
        win.addstr(0, 2, title[: max(0, panel_width - 4)])
        display_entries = rankings[self._leaderboard_offset : self._leaderboard_offset + visible_rows]
        for idx, entry in enumerate(display_entries, start=1):
            marker = "*" if entry.get("is_user") else " "
            name = entry.get("name", "")[:12]
            attr = curses.A_NORMAL
            if entry.get("is_user"):
                attr = self._color_pairs.get("negative", curses.A_NORMAL) | curses.A_BOLD
            text = (
                f"{entry.get('rank', 0):>3}{marker} "
                f"{name:<12} "
                f"{entry.get('points', 0):>4}p "
                f"{entry.get('earnings', 0):>7}"
            )
            win.addstr(idx, 1, text[: max(0, panel_width - 2)], attr)
        hint = "Use j/k to scroll"
        win.addstr(win_height - 1, 1, hint[: max(0, panel_width - 2)], curses.A_DIM)
        win.refresh()

    def _season_is_over(self, state: Dict | None) -> bool:
        if not state:
            return False
        season = state.get("season") or {}
        return int(season.get("current_week", 1)) > int(season.get("total_weeks", 0))

    def _show_season_summary(self, stdscr, summary: Dict) -> None:
        if not summary:
            self._notify(stdscr, "Résumé saison indisponible.")
            return
        lines: List[str] = []
        player = summary.get("player") or {}
        lines.append("Résumé de la saison")
        lines.append("")
        lines.append(
            f"Bilan joueur: points {player.get('points', 0)} | gains {self._format_amount(player.get('earnings', 0))} | victoires {player.get('wins', 0)} | Classement {player.get('rank', '-') }"
        )
        lines.append("")
        rankings = summary.get("rankings") or []
        lines.append("Classement final (Top 10):")
        for entry in rankings[:10]:
            line = (
                f" {entry.get('rank', 0):>2}. {entry.get('name', '-'):<18}"
                f" {self._format_amount(entry.get('points', 0))} pts | {self._format_amount(entry.get('earnings', 0))}"
            )
            lines.append(line)
        if len(rankings) > 10:
            lines.append(f" ... et {len(rankings) - 10} autres joueurs")
        lines.append("")
        lines.append("Tournois disputés:")
        tournaments = summary.get("tournaments") or []
        if not tournaments:
            lines.append(" Aucun tournoi enregistré.")
        else:
            header = " Semaine | Tournoi               | Scores               | Net        "
            lines.append(header)
            lines.append(" " + "-" * (len(header) - 1))
            for card in tournaments:
                scores = card.get("round_scores") or []
                score_text = " / ".join("--" if s is None else f"{s:>2}" for s in scores)
                net_text = self._format_amount(card.get("net_money", 0), show_sign=True)
                tournament_label = f"{card.get('tournament_name', '-')}, {card.get('position', '-')}"[:20]
                line = (
                    f" {card.get('week', 0):>2} | "
                    f"{tournament_label:<20}"
                    f" | {score_text:<21}"
                    f" | {net_text:>10}"
                )
                lines.append(line)
        lines.append("")
        lines.append("Gains / dépenses par catégorie:")
        ledger = summary.get("ledger_totals") or {}
        for key, totals in ledger.items():
            if key == "TOTAL":
                continue
            lines.append(
                f" - {key}: +{self._format_amount(totals.get('gains', 0))} / -{self._format_amount(totals.get('depenses', 0))} (net {self._format_amount(totals.get('net', 0), show_sign=True)})"
            )
        total_bucket = ledger.get("TOTAL")
        if total_bucket:
            lines.append("")
            lines.append(
                f"Total saison: +{self._format_amount(total_bucket.get('gains', 0))} / -{self._format_amount(total_bucket.get('depenses', 0))} (net {self._format_amount(total_bucket.get('net', 0), show_sign=True)})"
            )
        self._render_scrollable_popup(stdscr, "Résumé de saison", lines)

    def _render_scrollable_popup(self, stdscr, title: str, lines: List[str]) -> None:
        height, width = stdscr.getmaxyx()
        win_height = min(height - 2, max(10, len(lines) + 4))
        visible = max(1, win_height - 4)
        content_width = max((len(line) for line in lines), default=len(title))
        win_width = min(width - 4, max(40, content_width + 4))
        start_y = max(0, (height - win_height) // 2)
        start_x = max(0, (width - win_width) // 2)
        win = curses.newwin(win_height, win_width, start_y, start_x)
        offset = 0
        max_offset = max(0, len(lines) - visible)
        while True:
            win.erase()
            win.border()
            win.addstr(0, 2, title[: win_width - 4], curses.A_BOLD)
            for idx in range(visible):
                if offset + idx >= len(lines):
                    break
                win.addstr(2 + idx, 2, lines[offset + idx][: win_width - 4])
            footer = "Use j/k, q to close"
            win.addstr(win_height - 2, 2, footer[: win_width - 4], curses.A_DIM)
            win.refresh()
            key = win.getkey()
            if key.lower() in {"q", "\n", " "}:
                break
            if key in {"KEY_UP", "k"}:
                offset = max(0, offset - 1)
            elif key in {"KEY_DOWN", "j"}:
                offset = min(max_offset, offset + 1)
            elif key in {"KEY_PPAGE"}:
                offset = max(0, offset - visible)
            elif key in {"KEY_NPAGE"}:
                offset = min(max_offset, offset + visible)
        win.clear()
        win.refresh()
        stdscr.touchwin()
        stdscr.refresh()

    def _format_amount(self, value: int, show_sign: bool = False) -> str:
        formatted = f"{abs(value):,}".replace(",", " ")
        if not show_sign:
            return formatted
        if value > 0:
            return f"+{formatted}"
        if value < 0:
            return f"-{formatted}"
        return formatted

    def _confirm(self, stdscr, message: str) -> bool:
        height, width = stdscr.getmaxyx()
        win_height = 7
        win_width = min(60, width - 4)
        win = curses.newwin(win_height, win_width, (height - win_height) // 2, (width - win_width) // 2)
        win.border()
        lines = textwrap.wrap(message, win_width - 4)
        for idx, line in enumerate(lines[: win_height - 4]):
            win.addstr(1 + idx, 2, line)
        options = "Entrée pour confirmer, q pour annuler"
        win.addstr(win_height - 2, 2, options[: win_width - 4], curses.A_DIM)
        win.refresh()
        while True:
            key = win.getkey()
            if key.lower() == "q":
                return False
            if key in {"\n", "\r"}:
                return True

    def _lookup_tournament_name(self, state: Dict | None, post_action: bool) -> str | None:
        if not state:
            return None
        season = state.get("season") or {}
        tournaments = season.get("tournaments") or []
        if not tournaments:
            return None
        current_week = int(season.get("current_week", 1))
        if post_action and current_week > 1:
            target_week = current_week - 1
        else:
            target_week = current_week
        for tournament in tournaments:
            if int(tournament.get("week", -1)) == target_week:
                return tournament.get("name")
        return None

    def _show_tournament_animation(self, stdscr, tournament_name: str) -> None:
        height, width = stdscr.getmaxyx()
        win_width = min(width - 4, 60)
        win_height = 11
        start_y = max(0, (height - win_height) // 2)
        start_x = max(0, (width - win_width) // 2)
        win = curses.newwin(win_height, win_width, start_y, start_x)
        stages = [
            "Départ du premier tour...",
            "Les drives claquent sur le fairway...",
            "Approches tendues vers le drapeau...",
            "Passage au cut du vendredi...",
            "Vent de folie sur le moving day...",
            "Derniers putts sous pression...",
            "Playoff potentiel...",
            "Cartes signées, verdict imminent...",
        ]
        spinner = ["|", "/", "-", "\\"]
        total_duration = 8.0
        frame_duration = 0.5
        frames = max(1, int(total_duration / frame_duration))
        highlight = self._color_pairs.get("positive", curses.A_BOLD)
        info_attr = self._color_pairs.get("negative", curses.A_DIM)

        for frame in range(frames):
            win.erase()
            win.border()
            stage_text = stages[frame % len(stages)]
            spinner_char = spinner[frame % len(spinner)]
            win.addstr(1, 2, tournament_name[: win_width - 4], highlight)
            win.addstr(3, 2, f"{spinner_char} {stage_text}"[: win_width - 4])

            progress_ratio = (frame + 1) / frames
            bar_width = max(12, win_width - 6)
            filled = min(bar_width, int(bar_width * progress_ratio))
            bar = "#" * filled + "-" * (bar_width - filled)
            bar_text = f"[{bar}]"
            win.addstr(5, 2, bar_text[: win_width - 4], highlight)

            info_text = "Simulation du tournoi en cours..."
            win.addstr(7, 2, info_text[: win_width - 4], info_attr)
            win.refresh()
            time.sleep(frame_duration)

        win.clear()
        win.refresh()
        stdscr.touchwin()
        stdscr.refresh()

    def _show_tournament_popup(self, stdscr, result: Dict, message: str | None) -> None:
        height, width = stdscr.getmaxyx()
        entry_fee = int(result.get("entry_fee", 0))
        prize = int(result.get("prize_money", 0))
        net = int(result.get("net_money", 0))
        reputation = int(result.get("reputation_delta", 0))
        motivation = int(result.get("motivation_delta", 0))
        performance = float(result.get("performance", 0.0))
        tournament_name = result.get("tournament_name", "Tournoi")
        position = result.get("position", "?")
        missed_cut = bool(result.get("missed_cut"))

        header = f"{tournament_name}"
        lines = [
            f"Position: {position}",
            f"Indice de performance: {performance:.1f}%",
            f"Gains: {prize} crédits",
        ]
        if entry_fee:
            lines.append(f"Frais d'inscription: {entry_fee} crédits")
        lines.append(f"Résultat net: {net:+d} crédits")
        lines.append(f"Réputation: {reputation:+d}")
        lines.append(f"Motivation: {motivation:+d}")

        rounds = result.get("round_scores") or []
        if rounds:
            lines.append("Scores par tour:")
            par = 72
            for idx, score in enumerate(rounds, start=1):
                if score is None:
                    lines.append(f"  R{idx}: --")
                else:
                    delta = score - par
                    if delta > 0:
                        delta_text = f"+{delta}"
                    elif delta < 0:
                        delta_text = f"{delta}"
                    else:
                        delta_text = "E"
                    lines.append(f"  R{idx}: {score} ({delta_text})")

        detail_text = message or result.get("message") or ""
        if detail_text:
            wrapped = textwrap.wrap(detail_text, 50)
        else:
            wrapped = []
        lines.extend(wrapped)

        content_width = max(len(header), *(len(line) for line in lines)) if lines else len(header)
        win_width = min(max(40, content_width + 4), width - 4)
        win_height = min(len(lines) + 5, height - 4)
        start_y = (height - win_height) // 2
        start_x = (width - win_width) // 2
        win = curses.newwin(win_height, win_width, start_y, start_x)
        win.border()
        win.addstr(1, 2, header[: win_width - 4], curses.A_BOLD)

        money_attr = self._color_for_money(net)
        for idx, line in enumerate(lines[: win_height - 4], start=2):
            attr = curses.A_NORMAL
            if line.startswith("Résultat net"):
                attr = money_attr
            elif line.startswith("Position") and missed_cut:
                attr = self._color_pairs.get("negative", curses.A_NORMAL)
            win.addstr(idx, 2, line[: win_width - 4], attr)

        footer = "Appuyez sur une touche pour continuer"
        win.addstr(win_height - 2, 2, footer[: win_width - 4], curses.A_DIM)
        win.refresh()
        win.getch()


def parse_args() -> Tuple[str, bool]:
    parser = argparse.ArgumentParser(description="Client curses pour la simulation de carrière de golfeur")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="URL de base du serveur FastAPI")
    parser.add_argument("--admin", action="store_true", help="Afficher des informations supplémentaires (ledger)")
    args = parser.parse_args()
    return args.url, args.admin


def main() -> None:
    base_url, admin_mode = parse_args()
    app = ClientApp(base_url=base_url, admin_mode=admin_mode)
    app.run()


if __name__ == "__main__":
    main()
