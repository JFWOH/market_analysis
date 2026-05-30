# Sprint 27 — Fundação da UI

**Bloco**: III (Interface Gráfica)
**Duração estimada**: 6-8 dias úteis
**Pré-requisito**: Sprint 26 fechado (`v0.26.0`)
**Status**: pending
**Tag ao fechar**: `v0.27.0`

---

## 1. Contexto

Inicia o Bloco III. Antes de qualquer visualização rica, é necessário estabelecer a **fundação arquitetural** da UI:

- Estrutura de diretórios isolada (`gui/`)
- `SessionManager` que orquestra processos de simulação
- Comunicação via `multiprocessing.Queue` entre simulador e backend
- Backend Flask com rotas básicas e SocketIO
- Persistência via Repository do Sprint 25
- Adapter pattern para isolar UI do motor

Este sprint **não** entrega visualização bonita. Entrega arquitetura validada com simulação **mock** (estratégia trivial que gera eventos a cada N segundos). Razão: armadilhas de `multiprocessing` + SocketIO em Windows são reais; descobrir cedo, sem ruído de UI complexa, é mais barato.

---

## 2. Objetivo

Ter o esqueleto completo funcionando: usuário acessa `/config` no browser, configura uma simulação mock, clica iniciar, é redirecionado para `/live/<session_id>`, e vê eventos chegando em tempo real via SocketIO. Tudo persistido em SQLite.

---

## 3. Entregáveis

### E1 — Estrutura de diretórios `gui/`

```
gui/
├── __init__.py
├── server.py                  # Flask app + SocketIO setup
├── session_manager.py         # spawn/track/kill de processos
├── adapter.py                 # ÚNICA porta de entrada para o motor
├── sockets.py                 # SocketIO event handlers
├── desktop.py                 # pywebview wrapper (placeholder, Sprint 33)
│
├── routes/
│   ├── __init__.py
│   ├── config.py              # GET /config, POST /sessions
│   ├── sessions.py            # GET /sessions, GET /sessions/<id>
│   └── live.py                # GET /live/<id>
│
├── runners/
│   ├── __init__.py
│   ├── base.py                # BaseRunner abstract class
│   └── mock.py                # MockRunner (este sprint)
│
├── static/
│   ├── css/
│   │   └── base.css
│   ├── js/
│   │   ├── socket_client.js
│   │   └── live.js
│   └── vendor/                # placeholder
│
└── templates/
    ├── base.html.j2
    ├── config.html.j2
    ├── live.html.j2
    └── sessions.html.j2
```

### E2 — `gui/server.py`

```python
from flask import Flask
from flask_socketio import SocketIO
from pathlib import Path
from db.repository import Repository
from gui.session_manager import SessionManager
from gui.routes import config, sessions, live
from gui.sockets import register_socket_handlers


def create_app(
    repository: Repository = None,
    debug: bool = False,
) -> tuple[Flask, SocketIO]:
    """Application factory."""
    app = Flask(
        __name__,
        static_folder="static",
        template_folder="templates",
    )
    app.config["SECRET_KEY"] = "dev-key-replace-in-production"  # OK para local-only
    app.config["DEBUG"] = debug
    
    repo = repository or Repository()
    app.config["REPOSITORY"] = repo
    
    socketio = SocketIO(
        app,
        async_mode="threading",  # mais simples que eventlet em Windows
        cors_allowed_origins="*",  # local-only, OK
        logger=debug,
        engineio_logger=debug,
    )
    
    # Session manager: spawn de processos
    session_mgr = SessionManager(repository=repo, socketio=socketio)
    app.config["SESSION_MANAGER"] = session_mgr
    
    # Registrar rotas
    app.register_blueprint(config.bp)
    app.register_blueprint(sessions.bp)
    app.register_blueprint(live.bp)
    
    # Registrar SocketIO handlers
    register_socket_handlers(socketio, session_mgr)
    
    # Healthcheck
    @app.route("/health")
    def health():
        return {"status": "ok", "version": "0.27.0"}
    
    return app, socketio


def main():
    app, socketio = create_app(debug=True)
    print("Control Center starting on http://127.0.0.1:5000")
    socketio.run(app, host="127.0.0.1", port=5000, debug=True, use_reloader=False)


if __name__ == "__main__":
    main()
```

### E3 — `gui/session_manager.py`

```python
import multiprocessing as mp
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Callable
from flask_socketio import SocketIO
from db.repository import Repository


@dataclass
class ActiveSession:
    session_id: str
    process: mp.Process
    event_queue: mp.Queue
    command_queue: mp.Queue
    started_at: datetime
    consumer_thread: threading.Thread


class SessionManager:
    """
    Orquestra processos de simulação.
    
    Responsabilidades:
    - Spawn de processos via multiprocessing
    - Roteamento de eventos para SocketIO via consumer thread
    - Comandos para processos (pause, resume, abort)
    - Cleanup de processos terminados
    """
    
    def __init__(self, repository: Repository, socketio: SocketIO):
        self.repo = repository
        self.socketio = socketio
        self._sessions: dict[str, ActiveSession] = {}
        self._lock = threading.Lock()
    
    def start_session(
        self,
        mode: str,
        config: dict,
        runner_cls: type,
    ) -> str:
        """
        Cria sessão no DB, spawns processo, inicia consumer thread.
        Retorna session_id UUID.
        """
        session_id = self.repo.create_session(mode=mode, config=config)
        
        event_queue = mp.Queue()
        command_queue = mp.Queue()
        
        process = mp.Process(
            target=_run_simulator,
            args=(session_id, mode, config, runner_cls, event_queue, command_queue),
            name=f"sim_{session_id[:8]}",
        )
        process.start()
        
        consumer = threading.Thread(
            target=self._consume_events,
            args=(session_id, event_queue),
            daemon=True,
            name=f"consumer_{session_id[:8]}",
        )
        consumer.start()
        
        with self._lock:
            self._sessions[session_id] = ActiveSession(
                session_id=session_id,
                process=process,
                event_queue=event_queue,
                command_queue=command_queue,
                started_at=datetime.utcnow(),
                consumer_thread=consumer,
            )
        
        return session_id
    
    def send_command(self, session_id: str, command: dict) -> bool:
        """Envia comando (pause, resume, abort) ao processo."""
        with self._lock:
            sess = self._sessions.get(session_id)
        if not sess:
            return False
        sess.command_queue.put(command)
        return True
    
    def abort_session(self, session_id: str) -> bool: ...
    
    def get_active_sessions(self) -> list[str]: ...
    
    def is_alive(self, session_id: str) -> bool: ...
    
    def cleanup_finished(self) -> None: ...
    
    def _consume_events(self, session_id: str, queue: mp.Queue) -> None:
        """
        Thread consumer: lê queue do processo, emite via SocketIO.
        Persiste eventos críticos no repository.
        """
        while True:
            try:
                event = queue.get(timeout=1.0)
            except mp.queues.Empty:
                if not self.is_alive(session_id):
                    break
                continue
            
            if event["type"] == "SESSION_ENDED":
                self.repo.end_session(
                    session_id,
                    status=event["payload"]["status"],
                    summary=event["payload"]["summary"],
                )
                self.socketio.emit("session_ended", event, room=f"session_{session_id}")
                break
            
            # Persistir tipos críticos
            if event["type"] in ("SIGNAL_GENERATED", "TRADE_OPENED", "TRADE_CLOSED"):
                self._persist_event(session_id, event)
            
            # Broadcast via SocketIO
            self.socketio.emit(event["type"], event, room=f"session_{session_id}")


def _run_simulator(
    session_id: str,
    mode: str,
    config: dict,
    runner_cls: type,
    event_queue: mp.Queue,
    command_queue: mp.Queue,
) -> None:
    """
    Entry point do processo simulador.
    
    Importa motor APENAS aqui — não no escopo do session_manager
    (evita problemas com spawn em Windows).
    """
    try:
        runner = runner_cls(
            session_id=session_id,
            config=config,
            event_queue=event_queue,
            command_queue=command_queue,
        )
        runner.run()
    except Exception as e:
        event_queue.put({
            "type": "SESSION_ENDED",
            "payload": {
                "status": "error",
                "summary": {"error": str(e), "error_type": type(e).__name__},
            },
        })
```

### E4 — `gui/runners/base.py`

```python
from abc import ABC, abstractmethod
import multiprocessing as mp


class BaseRunner(ABC):
    """
    Base class para runners (Mock, Replay, Live).
    
    Subclasses implementam apenas `run()`.
    Helpers para emit, handle_command etc. estão aqui.
    """
    
    def __init__(
        self,
        session_id: str,
        config: dict,
        event_queue: mp.Queue,
        command_queue: mp.Queue,
    ):
        self.session_id = session_id
        self.config = config
        self.event_queue = event_queue
        self.command_queue = command_queue
        self._paused = False
        self._aborted = False
    
    def emit(self, event_type: str, payload: dict) -> None:
        """Push event para queue."""
        from datetime import datetime
        self.event_queue.put({
            "type": event_type,
            "session_id": self.session_id,
            "timestamp": datetime.utcnow().isoformat(),
            "payload": payload,
        })
    
    def check_commands(self) -> None:
        """Verifica command_queue não-bloqueante."""
        try:
            while True:
                cmd = self.command_queue.get_nowait()
                self._handle_command(cmd)
        except mp.queues.Empty:
            pass
    
    def _handle_command(self, cmd: dict) -> None:
        if cmd["action"] == "pause":
            self._paused = True
        elif cmd["action"] == "resume":
            self._paused = False
        elif cmd["action"] == "abort":
            self._aborted = True
    
    @abstractmethod
    def run(self) -> None: ...
```

### E5 — `gui/runners/mock.py`

```python
import time
import random
from gui.runners.base import BaseRunner


class MockRunner(BaseRunner):
    """
    Runner trivial para validar arquitetura.
    
    Gera eventos aleatórios a cada N segundos.
    NÃO usa o motor de verdade.
    """
    
    def run(self) -> None:
        n_bars = self.config.get("n_bars", 100)
        interval_seconds = self.config.get("interval_seconds", 0.5)
        ticker = self.config.get("ticker", "MOCK")
        
        self.emit("SESSION_STARTED", {
            "n_bars_planned": n_bars,
            "config": self.config,
        })
        
        for i in range(n_bars):
            self.check_commands()
            
            if self._aborted:
                self.emit("SESSION_ENDED", {
                    "status": "aborted",
                    "summary": {"bars_processed": i},
                })
                return
            
            while self._paused:
                time.sleep(0.1)
                self.check_commands()
                if self._aborted:
                    return
            
            # Simula barra processada
            self.emit("BAR_PROCESSED", {
                "bar_index": i,
                "ticker": ticker,
                "close": 100.0 + random.uniform(-5, 5),
            })
            
            # 20% das barras geram sinal
            if random.random() < 0.20:
                signal_type = random.choice(["Compra", "Venda"])
                self.emit("SIGNAL_GENERATED", {
                    "ticker": ticker,
                    "tipo": signal_type,
                    "preco": 100.0,
                    "stop_loss": 98.0,
                    "context": {"ADX": round(random.uniform(15, 40), 1)},
                })
            
            # 5% disparam trade
            if random.random() < 0.05:
                self.emit("TRADE_OPENED", {
                    "ticker": ticker,
                    "side": "long",
                    "price": 100.0,
                    "size": 100,
                })
            
            time.sleep(interval_seconds)
        
        self.emit("SESSION_ENDED", {
            "status": "completed",
            "summary": {"bars_processed": n_bars, "n_trades": "mock"},
        })
```

### E6 — Rotas

**`gui/routes/config.py`**:

```python
from flask import Blueprint, render_template, request, redirect, url_for, current_app
from gui.runners.mock import MockRunner

bp = Blueprint("config", __name__)


@bp.route("/")
@bp.route("/config")
def config_page():
    repo = current_app.config["REPOSITORY"]
    presets = repo.list_presets()
    return render_template("config.html.j2", presets=presets)


@bp.route("/sessions", methods=["POST"])
def start_session():
    data = request.form.to_dict()
    
    config = {
        "ticker": data.get("ticker", "MOCK"),
        "n_bars": int(data.get("n_bars", 100)),
        "interval_seconds": float(data.get("speed", 0.5)),
        "mode": data.get("mode", "mock"),
    }
    
    mgr = current_app.config["SESSION_MANAGER"]
    session_id = mgr.start_session(
        mode="replay",  # neste sprint, tudo é "mock" mas registramos como replay
        config=config,
        runner_cls=MockRunner,
    )
    
    return redirect(url_for("live.live_page", session_id=session_id))
```

**`gui/routes/live.py`**:

```python
from flask import Blueprint, render_template, current_app, abort

bp = Blueprint("live", __name__, url_prefix="/live")


@bp.route("/<session_id>")
def live_page(session_id: str):
    repo = current_app.config["REPOSITORY"]
    session = repo.get_session(session_id)
    if not session:
        abort(404)
    return render_template("live.html.j2", session=session)
```

**`gui/routes/sessions.py`** (placeholder simples; Sprint 30 expande):

```python
from flask import Blueprint, render_template, current_app

bp = Blueprint("sessions", __name__, url_prefix="/sessions")


@bp.route("/")
def list_sessions():
    repo = current_app.config["REPOSITORY"]
    sessions = repo.list_sessions(limit=50)
    return render_template("sessions.html.j2", sessions=sessions)
```

### E7 — `gui/sockets.py`

```python
from flask_socketio import SocketIO, join_room, leave_room, emit


def register_socket_handlers(socketio: SocketIO, session_mgr) -> None:
    
    @socketio.on("connect")
    def on_connect():
        emit("connected", {"status": "ok"})
    
    @socketio.on("join_session")
    def on_join(data):
        session_id = data["session_id"]
        join_room(f"session_{session_id}")
        emit("joined", {"session_id": session_id})
    
    @socketio.on("leave_session")
    def on_leave(data):
        session_id = data["session_id"]
        leave_room(f"session_{session_id}")
    
    @socketio.on("session_command")
    def on_command(data):
        session_id = data["session_id"]
        command = data["command"]
        success = session_mgr.send_command(session_id, command)
        emit("command_ack", {"success": success})
```

### E8 — Templates Jinja2 (mínimos)

**`gui/templates/base.html.j2`**:

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>{% block title %}market_analysis Control Center{% endblock %}</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/base.css') }}">
</head>
<body>
    <nav>
        <a href="{{ url_for('config.config_page') }}">Configurar</a>
        <a href="{{ url_for('sessions.list_sessions') }}">Sessões</a>
    </nav>
    <main>
        {% block content %}{% endblock %}
    </main>
    {% block scripts %}{% endblock %}
</body>
</html>
```

**`gui/templates/config.html.j2`**:

```html
{% extends "base.html.j2" %}
{% block content %}
<h1>Nova Simulação</h1>
<form method="post" action="{{ url_for('config.start_session') }}">
    <label>Ticker:
        <input name="ticker" value="MOCK" required>
    </label>
    <label>Número de barras:
        <input name="n_bars" type="number" value="100" min="10" max="10000">
    </label>
    <label>Velocidade (segundos por barra):
        <input name="speed" type="number" value="0.5" step="0.1" min="0.01">
    </label>
    <label>Modo:
        <select name="mode">
            <option value="mock" selected>Mock (Sprint 27)</option>
            <option value="replay" disabled>Replay Histórico (Sprint 28)</option>
            <option value="live" disabled>Paper Trading Live (Sprint 32)</option>
        </select>
    </label>
    <button type="submit">Iniciar Simulação</button>
</form>
{% endblock %}
```

**`gui/templates/live.html.j2`**:

```html
{% extends "base.html.j2" %}
{% block content %}
<h1>Sessão {{ session.id[:8] }}</h1>
<div id="status">Status: <span id="status-text">connecting...</span></div>
<div id="controls">
    <button onclick="sendCommand('pause')">Pausar</button>
    <button onclick="sendCommand('resume')">Retomar</button>
    <button onclick="sendCommand('abort')">Abortar</button>
</div>
<div id="event-log" style="height: 60vh; overflow-y: scroll; font-family: monospace; border: 1px solid #ccc; padding: 10px;"></div>
{% endblock %}

{% block scripts %}
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
<script>
    const sessionId = "{{ session.id }}";
    const socket = io();
    const log = document.getElementById("event-log");
    const status = document.getElementById("status-text");
    
    socket.on("connect", () => {
        status.textContent = "connected";
        socket.emit("join_session", { session_id: sessionId });
    });
    
    function appendEvent(type, payload) {
        const div = document.createElement("div");
        div.textContent = `[${new Date().toISOString()}] ${type}: ${JSON.stringify(payload)}`;
        log.appendChild(div);
        log.scrollTop = log.scrollHeight;
    }
    
    ["BAR_PROCESSED", "SIGNAL_GENERATED", "TRADE_OPENED", "TRADE_CLOSED", "SESSION_ENDED"]
        .forEach(t => socket.on(t, e => appendEvent(t, e.payload)));
    
    function sendCommand(action) {
        socket.emit("session_command", {
            session_id: sessionId,
            command: { action: action },
        });
    }
</script>
{% endblock %}
```

### E9 — Testes `tests/integration/test_session_manager.py`

Mínimo 8 casos:

1. **Spawn + observação**: iniciar mock session, esperar 5 segundos, verificar 5+ eventos no DB.
2. **Pause + resume**: pausar reduz eventos a zero; resume retoma.
3. **Abort**: aborto graceful encerra processo em < 2 segundos.
4. **Múltiplas sessões simultâneas**: 3 sessões em paralelo, eventos isolados por session_id.
5. **Crash do simulador**: exception no runner gera `SESSION_ENDED` com `status=error`.
6. **Cleanup**: processo terminado é removido de `_sessions` após cleanup_finished.
7. **Reconexão de cliente**: cliente desconecta e reconecta, sessão continua, recebe novos eventos.
8. **Estado persistido**: sessão é encontrável via `repo.get_session` após terminar.

### E10 — Testes `tests/e2e/test_basic_flow.py` (Playwright)

Mínimo 3 casos:

1. **Configurar e iniciar**: abrir `/config`, preencher form, submeter, verificar redirect para `/live/<id>`.
2. **Receber eventos**: na página live, esperar 3 eventos aparecerem no log.
3. **Healthcheck**: GET `/health` retorna `{"status": "ok"}`.

---

## 4. Critério de Aceitação

- [ ] Suite completa passa (incluindo 11 novos testes)
- [ ] `python -m gui.server` sobe Flask em `127.0.0.1:5000` sem erros
- [ ] Browser em `/config` mostra formulário funcional
- [ ] Submeter form cria sessão no DB e redireciona
- [ ] `/live/<id>` mostra eventos chegando em tempo real
- [ ] Comandos pause/resume/abort funcionam
- [ ] Múltiplas sessões simultâneas funcionam
- [ ] Sessões persistem no SQLite (verificar com sqlite3 CLI)
- [ ] Healthcheck `/health` responde
- [ ] **NO HARDCODED PATHS** — tudo via config ou env

---

## 5. Riscos

| Risco | Probabilidade | Mitigação |
|---|---|---|
| `multiprocessing.spawn` em Windows quebra imports | Alta | `_run_simulator` importa motor dentro da função; teste em Windows desde dia 1 |
| SocketIO `threading` vs `eventlet` em Windows | Média | Usar `threading` (mais simples); aceitar performance menor |
| Race conditions consumer thread + lifecycle | Média | Locks explícitos; testes de concorrência |
| Memory leak em sessões longas | Baixa-Média | Cleanup de queues; testar com sessão de 10k+ eventos |
| Browser desconecta mas processo continua | Baixa | Esperado e desejado (persistência forte) |

---

## 6. Notas para o Claude Code

- **Imports dentro de funções**: em `_run_simulator`, importar motor (`from strategy import ...`) APENAS dentro da função, não no topo do arquivo. Em Windows com `spawn`, imports no topo são re-executados em cada processo filho.
- **Adapter pattern**: já no Sprint 27 estabelecer disciplina — `gui/routes/*.py` nunca importa dos módulos do motor (`strategy`, `backtester`, etc.) diretamente. Sempre via `gui/adapter.py` (mesmo que adapter neste sprint seja vazio).
- **Mock primeiro**: tentação será pular para Replay real. Não pular. Validar arquitetura com mock economiza dias de debugging.
- **CSS mínimo**: este sprint é arquitetural. CSS rico vem no Sprint 29.
- **Não usar `eventlet`**: causa muitos problemas em Windows. `threading` é suficiente para single-user.
- **Logs**: usar `logging` Python, não print. Configurar formato útil em `gui/server.py`.

---

## 7. Comandos de validação

```bash
# Setup
pip install -e ".[dev,gui]"

# Iniciar server
python -m gui.server
# Browser: http://127.0.0.1:5000

# Testes
pytest tests/integration/test_session_manager.py -v
pytest tests/e2e/test_basic_flow.py -v --headed

# Inspecionar DB
sqlite3 data/market_analysis.db "SELECT id, status, started_at FROM sessions ORDER BY started_at DESC LIMIT 5"

# Sanity check: 2 sessões simultâneas
# Abrir 2 abas de browser, iniciar mock em cada uma, verificar isolamento
```

---

## 8. Estimativa detalhada

| Tarefa | Estimativa |
|---|---|
| E1 — estrutura de diretórios | 0.25 dia |
| E2 — server.py | 0.5 dia |
| E3 — SessionManager | 1.5-2 dias |
| E4 + E5 — runners (base + mock) | 0.5-1 dia |
| E6 — rotas | 0.5 dia |
| E7 — sockets | 0.25 dia |
| E8 — templates | 0.5 dia |
| E9 + E10 — testes | 1.5-2 dias |
| Buffer (Windows multiprocessing debug) | 1 dia |
| **Total** | **6-8 dias** |
