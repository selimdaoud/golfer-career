"""FastAPI routes exposing the simulation engine."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import pty
import signal
import struct
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Optional

import fcntl
import termios
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.simulation import SimulationEngine
from persistence.storage import StateRepository


class ActionRequest(BaseModel):
    action: str
    skill: Optional[str] = None
    motivation_delta: Optional[int] = None
    mental_recovery: Optional[int] = None
    skip_advance: Optional[bool] = None


config_path = Path("data/config.json")
state_path = Path("data/state.json")
repository = StateRepository(config_path=config_path, state_path=state_path)
engine = SimulationEngine(repository=repository)

app = FastAPI(
    title="Golfer Career Simulation",
    description=(
        "API REST minimaliste permettant de piloter la simulation de carrière "
        "d'un golfeur amateur dans sa première saison professionnelle."
    ),
    version="0.1.0",
)

app.mount("/browser", StaticFiles(directory="ui/browser", html=True), name="browser")


class SessionManager:
    """Manage isolated simulation engines for concurrent browser sessions."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self._sessions: dict[str, tuple[SimulationEngine, Path]] = {}
        self._lock = threading.RLock()

    def create_session(self) -> str:
        session_id = uuid.uuid4().hex
        state_path = Path(tempfile.gettempdir()) / f"golfer-career-{session_id}.json"
        repository = StateRepository(config_path=self.config_path, state_path=state_path)
        engine = SimulationEngine(repository=repository)
        with self._lock:
            self._sessions[session_id] = (engine, state_path)
        return session_id

    def get_engine(self, session_id: str) -> SimulationEngine:
        with self._lock:
            try:
                return self._sessions[session_id][0]
            except KeyError as exc:
                raise KeyError(f"Unknown session {session_id}") from exc

    def dispose_session(self, session_id: str) -> None:
        with self._lock:
            engine, state_path = self._sessions.pop(session_id, (None, None))
        if state_path and state_path.exists():
            with contextlib.suppress(OSError):
                state_path.unlink()
        # Allow engine reference to be garbage collected.
        del engine


session_manager = SessionManager(config_path=config_path)

def _engine_for_session(session_id: str) -> SimulationEngine:
    try:
        return session_manager.get_engine(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc


class TerminalSession:
    """Manage a curses client subprocess bridged to a WebSocket terminal."""

    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.master_fd: int | None = None
        self.child_pid: int | None = None
        self.reader_task: asyncio.Task[None] | None = None
        self.session_id: str | None = None

    async def start(self) -> None:
        """Spawn the curses UI under a pseudo-terminal and stream output."""
        env = os.environ.copy()
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("COLORTERM", "truecolor")

        self.session_id = session_manager.create_session()
        session_url = f"http://127.0.0.1:8000/session/{self.session_id}"

        command = [
            sys.executable,
            "-m",
            "ui.client",
            "--url",
            session_url,
            "--admin",
        ]

        try:
            pid, master_fd = pty.fork()
        except Exception:
            if self.session_id:
                session_manager.dispose_session(self.session_id)
                self.session_id = None
            raise
        if pid == 0:  # Child process.
            try:
                os.execvpe(command[0], command, env)
            finally:
                os._exit(1)

        self.child_pid = pid
        self.master_fd = master_fd
        os.set_blocking(self.master_fd, False)
        self.reader_task = asyncio.create_task(self._pump_output())

    async def _pump_output(self) -> None:
        """Continuously read from the subprocess and forward to the websocket."""
        while True:
            if self.master_fd is None:
                break
            try:
                data = os.read(self.master_fd, 4096)
            except BlockingIOError:
                data = b""
            except OSError:
                break

            if data:
                await self.websocket.send_text(
                    json.dumps(
                        {
                            "type": "output",
                            "data": data.decode("utf-8", errors="ignore"),
                        }
                    )
                )
                continue

            # No data available, yield control briefly.
            await asyncio.sleep(0.02)

            # Check if child has exited.
            if self.child_pid is not None:
                finished_pid, status = os.waitpid(self.child_pid, os.WNOHANG)
                if finished_pid == self.child_pid:
                    self.child_pid = None
                    await self._send_exit(status)
                    break

    async def _send_exit(self, status: int) -> None:
        """Send exit notification to the websocket client."""
        code: int | None
        if os.WIFEXITED(status):
            code = os.WEXITSTATUS(status)
        elif os.WIFSIGNALED(status):
            code = -os.WTERMSIG(status)
        else:
            code = None

        await self.websocket.send_text(
            json.dumps(
                {
                    "type": "exit",
                    "code": code,
                }
            )
        )

    def write(self, data: str) -> None:
        """Forward user input to the subprocess."""
        if self.master_fd is None:
            return
        os.write(self.master_fd, data.encode("utf-8", errors="ignore"))

    def resize(self, cols: int, rows: int) -> None:
        """Apply terminal size changes to the subprocess."""
        if self.master_fd is None:
            return
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
        # Notify process about resize.
        if self.child_pid is not None:
            os.kill(self.child_pid, signal.SIGWINCH)

    async def close(self) -> None:
        """Terminate the subprocess and cleanup resources."""
        if self.reader_task:
            self.reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.reader_task
            self.reader_task = None

        if self.master_fd is not None:
            os.close(self.master_fd)
            self.master_fd = None

        if self.child_pid is not None:
            try:
                os.kill(self.child_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            with contextlib.suppress(ChildProcessError):
                os.waitpid(self.child_pid, 0)
            self.child_pid = None
        if self.session_id:
            session_manager.dispose_session(self.session_id)
            self.session_id = None


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Redirect vers l'interface navigateur."""
    return RedirectResponse(url="/browser/", status_code=307)


@app.get("/state")
def get_state() -> dict:
    """Return the current simulation state."""
    return engine.get_state().to_dict()


@app.post("/action")
def post_action(request: ActionRequest) -> dict:
    """Apply an action chosen by the player and return the new state."""
    payload = request.dict(exclude_none=True)
    action = payload.pop("action")
    try:
        state = engine.perform_action(action, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return state.to_dict()


@app.post("/reset")
def reset_state() -> dict:
    """Reset the season to its initial state."""
    state = engine.reset()
    return state.to_dict()


@app.get("/session/{session_id}/state")
def get_session_state(session_id: str) -> dict:
    """Return the current simulation state for a specific session."""
    return _engine_for_session(session_id).get_state().to_dict()


@app.post("/session/{session_id}/action")
def post_session_action(session_id: str, request: ActionRequest) -> dict:
    """Apply an action for a dedicated session."""
    payload = request.dict(exclude_none=True)
    action = payload.pop("action")
    engine_for_session = _engine_for_session(session_id)
    try:
        state = engine_for_session.perform_action(action, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return state.to_dict()


@app.post("/session/{session_id}/reset")
def reset_session_state(session_id: str) -> dict:
    """Reset the simulation state for a specific session."""
    engine_for_session = _engine_for_session(session_id)
    state = engine_for_session.reset()
    return state.to_dict()


@app.websocket("/terminal")
async def terminal_endpoint(websocket: WebSocket) -> None:
    """Expose the curses client inside a WebSocket-powered terminal."""
    await websocket.accept()
    session = TerminalSession(websocket)

    try:
        await session.start()
    except Exception as exc:  # pylint: disable=broad-except
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "message": f"Impossible de démarrer le terminal: {exc}",
                }
            )
        )
        await websocket.close()
        return

    try:
        while True:
            message = await websocket.receive_text()
            payload = json.loads(message)
            msg_type = payload.get("type")

            if msg_type == "input":
                session.write(payload.get("data", ""))
            elif msg_type == "resize":
                cols = int(payload.get("cols", 80))
                rows = int(payload.get("rows", 24))
                session.resize(cols, rows)
    except WebSocketDisconnect:
        pass
    finally:
        await session.close()
