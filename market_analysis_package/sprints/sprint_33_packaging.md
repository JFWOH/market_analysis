# Sprint 33 — Empacotamento Desktop (.exe via pywebview + PyInstaller)

**Bloco**: III (Interface Gráfica)
**Duração estimada**: 5-7 dias úteis
**Pré-requisito**: Sprint 32 fechado (`v0.32.0`)
**Status**: pending
**Tag ao fechar**: `v1.0.0` (release final do programa)

---

## 1. Contexto

Os Sprints 27-32 entregam o Control Center completo, mas atualmente requer:

```bash
python -m gui.server  # terminal aberto
# abrir browser em http://127.0.0.1:5000
```

Para o usuário final (mesmo sendo o próprio desenvolvedor), isso é fricção desnecessária. Este sprint elimina:

- Necessidade de terminal aberto
- Necessidade de digitar URL no browser
- Necessidade de Python instalado no sistema
- Necessidade de gerenciar ambiente virtual

A solução: empacotar tudo em um `.exe` que sobe Flask em porta livre, abre janela nativa pywebview apontando para `http://127.0.0.1:PORT`, e ao fechar a janela encerra todo o processo. Ícone na taskbar, atalho no desktop, double-click para iniciar.

Este é o último sprint do programa. A entrega é a tag **v1.0.0** — sistema completo, auditado, testado, e instalável.

---

## 2. Objetivo

Criar `start_control_center.bat` (rápido) e `market_analysis.exe` (single-file via PyInstaller) que abrem o Control Center como aplicação desktop nativa.

---

## 3. Entregáveis

### E1 — `gui/desktop.py` (pywebview wrapper)

```python
"""
Desktop launcher — wraps Flask + pywebview.

Roda Flask em thread separada, abre janela pywebview apontando para localhost.
Fecha janela = encerra processo.
"""
import sys
import socket
import threading
import time
from pathlib import Path


def find_free_port(start: int = 5000, end: int = 5100) -> int:
    """Encontra porta livre no range."""
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"Nenhuma porta livre em {start}-{end}")


def start_flask_in_background(port: int) -> threading.Thread:
    """Inicia Flask + SocketIO em thread."""
    from gui.server import create_app
    
    app, socketio = create_app(debug=False)
    
    def run():
        socketio.run(
            app,
            host="127.0.0.1",
            port=port,
            debug=False,
            use_reloader=False,
            log_output=False,
        )
    
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def wait_for_server(port: int, timeout: int = 10) -> bool:
    """Verifica se servidor está pronto via /health."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            return True
        except (urllib.error.URLError, ConnectionRefusedError):
            time.sleep(0.2)
    return False


def main():
    print("market_analysis Control Center")
    print("=" * 40)
    
    # Verifica que diretórios essenciais existem
    Path("data").mkdir(exist_ok=True)
    Path("logs/audit").mkdir(parents=True, exist_ok=True)
    Path("data/cache").mkdir(parents=True, exist_ok=True)
    
    # Encontra porta
    port = find_free_port()
    print(f"Iniciando servidor na porta {port}...")
    
    # Inicia Flask
    server_thread = start_flask_in_background(port)
    
    # Aguarda
    if not wait_for_server(port):
        print("ERRO: servidor não iniciou em 10s")
        sys.exit(1)
    
    print(f"Servidor pronto em http://127.0.0.1:{port}")
    
    # Abre janela pywebview
    import webview
    
    window = webview.create_window(
        title="market_analysis — Control Center",
        url=f"http://127.0.0.1:{port}",
        width=1400,
        height=900,
        min_size=(1000, 700),
        resizable=True,
        text_select=True,
        confirm_close=True,
    )
    
    webview.start(debug=False, gui="edgechromium")  # Windows nativo
    
    # webview.start bloqueia. Quando janela fecha, prossegue.
    print("Janela fechada. Encerrando.")


if __name__ == "__main__":
    main()
```

### E2 — `start_control_center.bat` (Windows)

```batch
@echo off
setlocal

REM Caminho do diretório do projeto (resolve relativo ao .bat)
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

REM Verifica virtualenv
if not exist "venv\Scripts\python.exe" (
    echo ERRO: virtualenv nao encontrado em %PROJECT_DIR%venv
    echo Execute o setup primeiro: python -m venv venv && venv\Scripts\activate && pip install -e ".[gui]"
    pause
    exit /b 1
)

REM Ativa venv e roda
call venv\Scripts\activate.bat

echo Iniciando market_analysis Control Center...
echo (Feche a janela para encerrar)
echo.

python -m gui.desktop

REM Se chegou aqui, app encerrou
echo.
echo Control Center encerrado.
endlocal
```

### E3 — `start_control_center.sh` (Linux/Mac, opcional)

```bash
#!/bin/bash
set -e
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

if [ ! -f "venv/bin/python" ]; then
    echo "ERRO: virtualenv não encontrado"
    exit 1
fi

source venv/bin/activate
python -m gui.desktop
```

### E4 — `market_analysis.spec` (PyInstaller)

```python
# market_analysis.spec
# Build: pyinstaller market_analysis.spec

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Coletar templates, static, schema
datas = [
    ("gui/templates", "gui/templates"),
    ("gui/static", "gui/static"),
    ("db/schema.sql", "db"),
    ("configs/presets", "configs/presets"),
    ("scenarios", "scenarios"),
]

# yfinance precisa de seus data files
datas += collect_data_files("yfinance")

# Hidden imports
hiddenimports = [
    "engineio.async_drivers.threading",
    "flask_socketio",
    "socketio",
    "engineio",
    # SQLite drivers
    "sqlite3",
    # Statsmodels
    "statsmodels.tsa.stattools",
]
hiddenimports += collect_submodules("market_analysis")
hiddenimports += collect_submodules("gui")

a = Analysis(
    ["gui/desktop.py"],
    pathex=[os.path.abspath(".")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Reduz tamanho do binary
        "matplotlib.tests",
        "numpy.tests",
        "pandas.tests",
        "scipy.tests",
        "test",
        "tests",
        "tkinter",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "notebook",
        "jupyter",
        "IPython",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="market_analysis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,    # sem console
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico" if os.path.exists("assets/icon.ico") else None,
)
```

### E5 — Atalho desktop e icon

`assets/`:
- `icon.ico` — ícone Windows (32×32, 64×64, 128×128)
- `icon.png` — fonte para conversões
- `splash.png` — opcional, splash screen

`scripts/create_shortcut.py`:

```python
"""
Cria atalho do Control Center na Desktop do usuário.
Windows only.
"""
import os
from pathlib import Path

def create_shortcut():
    try:
        import win32com.client
    except ImportError:
        print("pywin32 não instalado; instale com: pip install pywin32")
        return False
    
    shell = win32com.client.Dispatch("WScript.Shell")
    desktop = Path(shell.SpecialFolders("Desktop"))
    shortcut_path = desktop / "market_analysis.lnk"
    
    project_dir = Path(__file__).resolve().parent.parent
    bat_path = project_dir / "start_control_center.bat"
    
    shortcut = shell.CreateShortcut(str(shortcut_path))
    shortcut.TargetPath = str(bat_path)
    shortcut.WorkingDirectory = str(project_dir)
    shortcut.IconLocation = str(project_dir / "assets" / "icon.ico")
    shortcut.Description = "market_analysis Control Center"
    shortcut.save()
    
    print(f"Atalho criado em {shortcut_path}")
    return True


if __name__ == "__main__":
    create_shortcut()
```

### E6 — Testes Playwright E2E

`tests/e2e/test_full_flow.py`:

```python
"""
End-to-end test do fluxo completo do usuário.
"""
import pytest
from playwright.sync_api import Page, expect


def test_complete_user_journey(page: Page, control_center_url):
    """
    1. Abre Control Center
    2. Configura replay
    3. Inicia simulação
    4. Aguarda eventos
    5. Vai para histórico
    6. Abre relatório
    7. Exporta HTML
    """
    page.goto(control_center_url)
    
    # 1. Config page carregou
    expect(page).to_have_title(...)
    
    # 2. Preencher form
    page.fill("input[name='ticker']", "MOCK")
    page.fill("input[name='n_bars']", "50")
    page.select_option("select[name='speed']", "instant")
    page.select_option("select[name='mode']", "mock")
    
    # 3. Submeter
    page.click("button[type='submit']")
    
    # 4. Aguardar redirecionamento para /live/<id>
    page.wait_for_url("**/live/**", timeout=10000)
    
    # 5. Aguardar finalização (status mostra completed)
    page.wait_for_selector("#status-text:has-text('completed')", timeout=60000)
    
    # 6. Ir para histórico
    page.click("a:has-text('Sessões')")
    page.wait_for_url("**/sessions")
    
    # 7. Verificar que a sessão aparece
    expect(page.locator(".sessions-table tbody tr")).to_have_count_greater_than(0)
    
    # 8. Abrir relatório da primeira
    page.click(".sessions-table tbody tr:first-child a[title='Relatório']")
    page.wait_for_selector("#sec-performance")
    
    # 9. Verificar 9 seções presentes
    for sec_id in ["sec-performance", "sec-equity", "sec-trades",
                    "sec-filters", "sec-bnh", "sec-log", "sec-disclaimers"]:
        expect(page.locator(f"#{sec_id}")).to_be_visible()
    
    # 10. Exportar HTML
    with page.expect_download() as download_info:
        page.click("a[href*='/export/html']")
    download = download_info.value
    assert download.suggested_filename.endswith(".html")


def test_compare_sessions(page: Page, control_center_url):
    """Testa fluxo de comparação A/B."""
    # ... rodar 2 sessões, selecionar ambas, clicar Compare
    ...
```

### E7 — Build script `scripts/build_exe.bat`

```batch
@echo off
echo Building market_analysis.exe...

call venv\Scripts\activate.bat

REM Limpar builds anteriores
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

REM Instalar PyInstaller se necessário
pip install --quiet pyinstaller

REM Build
pyinstaller market_analysis.spec --clean

if exist "dist\market_analysis.exe" (
    echo.
    echo SUCESSO: dist\market_analysis.exe criado
    for %%I in (dist\market_analysis.exe) do echo Tamanho: %%~zI bytes
) else (
    echo ERRO: build falhou
    exit /b 1
)

REM Copiar arquivos auxiliares
copy README.md dist\
xcopy assets dist\assets /E /I /Q

echo.
echo Distribuicao pronta em dist\
```

### E8 — `USER_GUIDE.md`

Manual do usuário final (não desenvolvedor):

```markdown
# market_analysis — Manual do Usuário

## Instalação

### Opção A: Versão portátil (single-file .exe)
1. Baixe `market_analysis.exe` 
2. Coloque em uma pasta da sua escolha
3. Duplo-clique para iniciar

### Opção B: Instalação via Python (recomendada para desenvolvimento)
1. Instale Python 3.10 ou superior
2. Clone o repositório
3. Execute: `python -m venv venv`
4. Ative: `venv\Scripts\activate` (Windows) ou `source venv/bin/activate` (Linux/Mac)
5. Instale: `pip install -e ".[gui]"`
6. Inicie: `start_control_center.bat` (Windows) ou `./start_control_center.sh`

## Primeira execução

[... screenshots e walkthrough ...]

## Modos de operação

### Replay Histórico
[explicação detalhada]

### Paper Trading Live
[explicação + limitações: latência yfinance, paper-only]

## Como interpretar os relatórios

[seção 9 do relatório explicada em prosa]

## Solução de problemas

| Problema | Causa provável | Solução |
|---|---|---|
| "Servidor não iniciou em 10s" | Porta ocupada | Reinicie o computador |
| yfinance retorna dados vazios | Ticker incorreto ou rate limit | Verifique ticker; aguarde alguns minutos |
| Relatório PDF vazio | Playwright sem Chromium | Execute `playwright install chromium` |
| Janela abre branca | Edge WebView2 desatualizado | Atualize via Windows Update |

## Limitações conhecidas

- **Latência yfinance**: dados intraday no Brasil têm delay de 15-20 minutos
- **Sem execução real**: sistema é paper trading; não envia ordens a corretoras
- **Single-user**: não há autenticação ou multi-usuário
- **Sem cloud sync**: dados locais; backup manual recomendado

## Backup

Para preservar suas sessões, copie:
- `data/market_analysis.db` (dados de todas as sessões)
- `logs/audit/` (log de auditoria imutável)
- `findings/` (relatórios da auditoria do Bloco I)

Restauração: copiar os arquivos de volta. SQLite é portável entre Windows/Linux/Mac.

## FAQ

[10-15 perguntas frequentes]
```

### E9 — Versionamento e release

`__init__.py`:

```python
__version__ = "1.0.0"
__release_date__ = "2026-XX-XX"  # preencher na release
__codename__ = "Foundation"

# Documenta os 3 cenários possíveis do Marco do Bloco I
# usado pelo report_banner
```

Tag git:
```bash
git tag -a v1.0.0 -m "Release v1.0.0 — Programa completo (Sprints 18-33)"
git push origin v1.0.0
```

GitHub release com:
- `market_analysis.exe` (binary)
- `market_analysis-1.0.0-source.zip`
- Release notes detalhadas
- Checksum SHA-256

---

## 4. Critério de Aceitação

- [ ] Suite completa passa
- [ ] `start_control_center.bat` em Windows: duplo-clique abre janela em < 10s
- [ ] `gui/desktop.py` encontra porta livre, sobe servidor, abre janela
- [ ] Fechar janela encerra processo completamente (sem zombies)
- [ ] `market_analysis.exe` builda sem erros
- [ ] `market_analysis.exe` rodando em máquina Windows limpa (sem Python instalado) funciona
- [ ] Tamanho do .exe < 200 MB
- [ ] Playwright E2E test passa do início ao fim
- [ ] `USER_GUIDE.md` cobre instalação e troubleshooting
- [ ] Tag `v1.0.0` criada com release notes

---

## 5. Riscos

| Risco | Probabilidade | Mitigação |
|---|---|---|
| PyInstaller binary > 300 MB | Alta | Excludes agressivos no .spec; UPX compression |
| WebView2 ausente em Windows antigos | Média | Documentar requisito; pywebview tem fallback |
| Antivirus marca .exe como ameaça | Alta | Code-sign certificate (futuro); documentar exceção manual |
| Multiprocessing em PyInstaller binary | Alta | Usar `multiprocessing.freeze_support()` no entrypoint; testar exaustivamente |
| yfinance + PyInstaller falha em algumas instalações | Média | Coletar data files explicitamente no spec |
| Janela pywebview branca em algumas máquinas | Baixa | `gui="edgechromium"` explícito; fallback gui="cef" |

---

## 6. Notas para o Claude Code

- **`multiprocessing.freeze_support()`** na primeiríssima linha de `gui/desktop.py` — sem isso, multiprocessing quebra em executáveis PyInstaller no Windows.
- **`use_reloader=False`** sempre em modo packaged.
- **`debug=False`** em produção (ativa muitos prints e Werkzeug devserver).
- **`log_output=False`** no socketio.run para não poluir console.
- **`gui="edgechromium"`** no pywebview.start: usa Edge WebView2 (nativo Windows 10+).
- **Ícone .ico**: usar ferramenta externa para gerar a partir de PNG (ImageMagick: `convert icon.png -resize 256x256 icon.ico`).
- **Teste em VM limpa**: máquina Windows fresh sem Python; .exe deve funcionar.
- **Não usar `--onefile` do PyInstaller** para projetos grandes — extração toma tempo a cada inicialização. Usar `--onedir` (folder) ou inspecionar spec.
- **Antivirus**: avisar no README que primeira execução pode demorar (Windows Defender inspecionando).

---

## 7. Comandos de validação

```bash
# Modo dev
python -m gui.desktop
# Esperado: janela abre em < 5s

# Build
scripts\build_exe.bat
# Esperado: dist\market_analysis.exe criado

# Teste em máquina limpa
# 1. Copiar dist\market_analysis.exe para outra máquina sem Python
# 2. Duplo-clique
# 3. Esperar abertura (~10s primeira vez por antivirus)
# 4. Configurar e rodar mock session
# 5. Verificar relatório

# E2E test
pytest tests/e2e/test_full_flow.py -v --headed

# Verificar versão
python -c "import strategy; print('ok')"
# Esperado: 1.0.0

# Release tag
git tag -a v1.0.0 -m "Release"
```

---

## 8. Estimativa detalhada

| Tarefa | Estimativa |
|---|---|
| E1 — desktop.py | 0.5-1 dia |
| E2 — start_control_center.bat | 0.25 dia |
| E3 — versão Linux/Mac (opcional) | 0.25 dia |
| E4 — PyInstaller spec | 1-1.5 dias |
| E5 — atalho + icon | 0.5 dia |
| E6 — Playwright E2E | 1 dia |
| E7 — build script | 0.25 dia |
| E8 — USER_GUIDE | 1 dia |
| E9 — versionamento + release | 0.5 dia |
| Buffer (PyInstaller é traiçoeiro) | 1-2 dias |
| **Total** | **5-7 dias** |

---

## 9. Pós-encerramento

Após `v1.0.0`:

1. **Retrospectiva do programa** (Sprints 18-33):
   - O que funcionou
   - O que demoraria mais que o estimado
   - O que mudaria em hindsight
   - Documentar em `findings/RETROSPECTIVE.md`

2. **Decisões para o roadmap v2**:
   - HMM regime classifier — agora vale o experimento?
   - Features macro (VIX, yield curve) — entram?
   - Risk parity portfolio?
   - Integração FIX com corretora?
   - Frontend React/Vue?

3. **Manutenção contínua**:
   - Dependências (pip-audit semanal)
   - Backup de findings (não regenerável)
   - Releases bugfix conforme necessário

O programa está **fechado**. O sistema está **vivo**.
