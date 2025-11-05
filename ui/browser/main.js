const terminalContainer = document.getElementById("terminal");
const restartBtn = document.getElementById("restart-btn");
const statusTimeEl = document.getElementById("status-time");

const baseTheme = {
  fontFamily: "Fira Code, Menlo, monospace",
  fontSize: 14,
  convertEol: true,
  cursorBlink: true,
  theme: {
    background: "#000000",
    foreground: "#f0f6ff",
    cursor: "#4cff9c",
    selection: "rgba(76, 255, 156, 0.35)",
    green: "#4cff9c",
    brightGreen: "#7bffba",
    blue: "#3f88ff",
    brightBlue: "#6aa5ff",
  },
};

const tn3270Theme = {
  fontFamily: "'IBM3270', '3270 Narrow', 'DM Mono', 'Fira Code', monospace",
  fontSize: 16,
  convertEol: true,
  cursorBlink: true,
  theme: {
    background: "#01060f",
    foreground: "#63ff8d",
    cursor: "#63ff8d",
    selection: "rgba(99, 255, 141, 0.28)",
    black: "#000000",
    red: "#ff4d4d",
    green: "#63ff8d",
    yellow: "#f7f779",
    blue: "#1f4fff",
    magenta: "#ff6ad5",
    cyan: "#3fd7ff",
    white: "#f4f4f4",
    brightBlack: "#555555",
    brightRed: "#ff7373",
    brightGreen: "#8bffb2",
    brightYellow: "#ffff8f",
    brightBlue: "#4f6bff",
    brightMagenta: "#ff8df0",
    brightCyan: "#7ae8ff",
    brightWhite: "#ffffff",
  },
};

const term = new window.Terminal(baseTheme);

applyTheme(baseTheme);

const fitAddon = new window.FitAddon.FitAddon();
term.loadAddon(fitAddon);

let socket;
let reconnectTimer;
let usingMainframeTheme = false;
let resizeObserver;
let clockTimer;

function updateClock() {
  if (!statusTimeEl) {
    return;
  }
  const now = new Date();
  const datePart = now
    .toLocaleDateString("fr-FR", {
      year: "2-digit",
      month: "2-digit",
      day: "2-digit",
      timeZone: "UTC",
    })
    .replace(/\./g, "/");
  const timePart = now
    .toLocaleTimeString("fr-FR", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
      timeZone: "UTC",
    })
    .replace(/\./g, ":");

  statusTimeEl.textContent = `${datePart} ${timePart} UTC`;
}

function applyTheme(preset) {
  term.options.fontFamily = preset.fontFamily;
  term.options.fontSize = preset.fontSize;
  term.options.cursorBlink = preset.cursorBlink;
  term.options.convertEol = preset.convertEol;
  term.options.theme = preset.theme;
  document.body.classList.toggle("theme-mainframe", preset === tn3270Theme);
}

function fitTerminal() {
  fitAddon.fit();
  if (socket?.readyState === WebSocket.OPEN) {
    const { cols, rows } = term;
    socket.send(
      JSON.stringify({
        type: "resize",
        cols,
        rows,
      }),
    );
  }
}

function disposeSocket() {
  if (
    socket &&
    socket.readyState !== WebSocket.CLOSED &&
    socket.readyState !== WebSocket.CLOSING
  ) {
    socket.__manualClose = true;
    socket.close();
  }
  socket = undefined;
  if (clockTimer) {
    window.clearInterval(clockTimer);
    clockTimer = undefined;
  }
}

function scheduleReconnect(delay = 3000) {
  clearTimeout(reconnectTimer);
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = undefined;
    connect();
  }, delay);
}

function connect() {
  disposeSocket();
  clearTimeout(reconnectTimer);
  reconnectTimer = undefined;

  term.clear();
  term.write("\u001b[32mConnexion au terminal...\u001b[0m\r\n");

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${window.location.host}/terminal`);

  restartBtn.disabled = true;

  socket.addEventListener("open", () => {
    restartBtn.disabled = false;
    term.write("\u001b[32mSession démarrée. Initialisation de l'interface...\u001b[0m\r\n");
    fitTerminal();
    term.focus();
  });

  socket.addEventListener("message", (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch (err) {
      console.error("Invalid payload from server", err);
      return;
    }

    switch (payload.type) {
      case "output":
        term.write(payload.data);
        break;
      case "exit":
        term.write(
          `\r\n\u001b[31mSession terminée (code: ${payload.code ?? "?"}).\u001b[0m\r\n`,
        );
        restartBtn.disabled = false;
        scheduleReconnect();
        break;
      case "error":
        term.write(`\r\n\u001b[31m${payload.message}\u001b[0m\r\n`);
        restartBtn.disabled = false;
        break;
      default:
        console.warn("Unhandled message type", payload);
    }
  });

  socket.addEventListener("close", (event) => {
    restartBtn.disabled = false;
    if (event.target.__manualClose) {
      event.target.__manualClose = false;
      return;
    }
    if (!reconnectTimer) {
      term.write("\r\n\u001b[33mConnexion perdue. Nouvelle tentative dans 3s...\u001b[0m\r\n");
      scheduleReconnect();
    }
  });

  socket.addEventListener("error", (event) => {
    console.error("WebSocket error", event);
    restartBtn.disabled = false;
    scheduleReconnect();
  });
}

restartBtn.addEventListener("click", () => {
  disposeSocket();
  connect();
});

term.onData((data) => {
  if (data.toLowerCase() === "t") {
    usingMainframeTheme = !usingMainframeTheme;
    applyTheme(usingMainframeTheme ? tn3270Theme : baseTheme);
    term.write(
      `\r\n\u001b[94m[Affichage]\u001b[0m Thème ${
        usingMainframeTheme ? "mainframe 3270" : "moderne"
      } activé.\r\n`,
    );
    fitTerminal();
    return;
  }
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(
      JSON.stringify({
        type: "input",
        data,
      }),
    );
  }
});

term.onResize(({ cols, rows }) => {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(
      JSON.stringify({
        type: "resize",
        cols,
        rows,
      }),
    );
  }
});

window.addEventListener("resize", () => {
  fitTerminal();
});

term.open(terminalContainer);
if (window.ResizeObserver) {
  resizeObserver = new ResizeObserver(() => {
    fitTerminal();
  });
  resizeObserver.observe(terminalContainer);
}
fitTerminal();
connect();
updateClock();
clockTimer = window.setInterval(updateClock, 1000);
