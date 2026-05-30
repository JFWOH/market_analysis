# Sprint 26 — Containerização e CI

**Bloco**: II (Hardening)
**Duração estimada**: 3-5 dias úteis
**Pré-requisito**: Sprint 25 fechado (`v0.25.0`)
**Status**: pending
**Tag ao fechar**: `v0.26.0`

---

## 1. Contexto

O sistema tem 519+ testes, mas não há automação que garanta que **toda mudança** os execute. Estado atual:

- Sem CI/CD — testes rodam localmente quando o desenvolvedor lembra.
- Sem containerização — setup em máquina nova é frágil, dependente de instalação manual de Python + dependências.
- Sem pre-commit hooks — formatação e lint só rodam manualmente.
- Sem matriz de versões Python — funciona em 3.10 e 3.13 hoje, mas pode quebrar silenciosamente.

Para um sistema que aspira a uso operacional, isso é dívida técnica que precisa ser paga **antes** da UI ser construída (Bloco III). Se a UI quebrar uma feature do motor, queremos saber em segundos via CI, não em horas via debugging manual.

---

## 2. Objetivo

Configurar CI completo no GitHub Actions, containerizar via Docker, e adicionar pre-commit hooks. Foco em **velocidade do feedback loop** — push → resultado em < 5 minutos.

---

## 3. Entregáveis

### E1 — `Dockerfile` multi-stage

```dockerfile
# ============================================================================
# Stage 1: Builder
# ============================================================================
FROM python:3.12-slim AS builder

WORKDIR /build

# System deps para compilação de wheels (numpy, pandas)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copia metadata de dependências primeiro (cache layer)
COPY pyproject.toml requirements*.txt ./

RUN pip install --no-cache-dir --upgrade pip wheel && \
    pip wheel --no-cache-dir --wheel-dir=/wheels -r requirements.txt

# ============================================================================
# Stage 2: Runtime
# ============================================================================
FROM python:3.12-slim

LABEL maintainer="Jeferson Wohanka"
LABEL description="market_analysis quantitative trading system"
LABEL version="0.26.0"

WORKDIR /app

# Usuário não-root
RUN groupadd --gid 1000 marketuser && \
    useradd --uid 1000 --gid marketuser --shell /bin/bash --create-home marketuser

# Instala wheels pré-compiladas
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/* && \
    rm -rf /wheels

# Copia código
COPY --chown=marketuser:marketuser . .

USER marketuser

# Healthcheck (Sprint 27+ terá endpoint /health no Flask)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import strategy; print("ok")" || exit 1

# Default: roda testes
CMD ["pytest", "tests/unit", "-q"]
```

### E2 — `docker-compose.yml` para desenvolvimento

```yaml
version: '3.8'

services:
  market_analysis:
    build: 
      context: .
      dockerfile: Dockerfile
    image: market_analysis:dev
    container_name: market_analysis_dev
    volumes:
      - .:/app
      - market_data:/app/data
      - market_logs:/app/logs
    environment:
      - PYTHONUNBUFFERED=1
      - PYTHONDONTWRITEBYTECODE=1
    command: tail -f /dev/null  # mantém vivo para exec
  
  test_runner:
    extends: market_analysis
    container_name: market_analysis_test
    command: pytest tests/ -q --cov=market_analysis

volumes:
  market_data:
  market_logs:
```

### E3 — `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main, 'sprint-*']
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install ruff and mypy
        run: pip install ruff mypy
      - name: Ruff check
        run: ruff check .
      - name: Ruff format check
        run: ruff format --check .
      - name: Mypy
        run: mypy market_analysis/ --ignore-missing-imports
        continue-on-error: true  # tipagem progressiva
  
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
        python-version: ['3.10', '3.11', '3.12', '3.13']
    
    steps:
      - uses: actions/checkout@v4
      
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: 'pip'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"
      
      - name: Run unit tests
        run: pytest tests/unit -q --cov=market_analysis --cov-report=xml
      
      - name: Run integration tests
        if: matrix.os == 'ubuntu-latest' && matrix.python-version == '3.12'
        run: pytest tests/integration -q
      
      - name: Upload coverage
        if: matrix.os == 'ubuntu-latest' && matrix.python-version == '3.12'
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml
          fail_ci_if_error: false
  
  docker:
    runs-on: ubuntu-latest
    needs: [lint, test]
    steps:
      - uses: actions/checkout@v4
      - name: Build Docker image
        run: docker build -t market_analysis:ci .
      - name: Run tests in container
        run: docker run --rm market_analysis:ci pytest tests/unit -q
```

### E4 — `.github/workflows/release.yml`

```yaml
name: Release

on:
  push:
    tags:
      - 'v*'

jobs:
  build_image:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      
      - name: Login to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      
      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: |
            ghcr.io/${{ github.repository }}:${{ github.ref_name }}
            ghcr.io/${{ github.repository }}:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

### E5 — `.pre-commit-config.yaml`

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
        args: ['--maxkb=1000']
      - id: check-merge-conflict
      - id: detect-private-key
  
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  
  - repo: local
    hooks:
      - id: pytest-fast
        name: pytest (unit tests fast subset)
        entry: pytest tests/unit -q -x --timeout=10
        language: system
        pass_filenames: false
        stages: [push]
```

### E6 — `pyproject.toml` consolidado

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "market_analysis"
version = "0.26.0"
description = "Quantitative trading research and simulation system"
authors = [{name = "Jeferson Wohanka"}]
readme = "README.md"
requires-python = ">=3.10"
license = {text = "Proprietary"}

dependencies = [
    "pandas>=2.0",
    "numpy>=1.24",
    "scipy>=1.10",
    "yfinance>=0.2.40",
    "matplotlib>=3.7",
    "plotly>=5.18",
    "flask>=3.0",
    "flask-socketio>=5.3",
    "tqdm>=4.66",
    "pyyaml>=6.0",
    "portalocker>=2.8",
    "statsmodels>=0.14",
    "scikit-learn>=1.3",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "pytest-timeout>=2.3",
    "pytest-xdist>=3.5",
    "ruff>=0.5",
    "mypy>=1.10",
    "pre-commit>=3.7",
]

api = [
    "fastapi>=0.110",
    "pydantic>=2.7",
    "uvicorn>=0.27",
]

gui = [
    "pywebview>=5.0",
    "playwright>=1.40",
    "weasyprint>=60",
]

optuna = [
    "optuna>=3.6",
]

all = [
    "market_analysis[dev,api,gui,optuna]",
]

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "B", "A", "UP", "PIE", "T20", "RET", "SIM"]
ignore = ["E501"]

[tool.mypy]
python_version = "3.10"
warn_return_any = true
warn_unused_configs = true
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-ra --strict-markers"
markers = [
    "slow: marks tests as slow",
    "integration: marks integration tests",
    "e2e: marks end-to-end tests",
]

[tool.coverage.run]
source = ["market_analysis"]
omit = ["*/tests/*", "*/scripts/*"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
]
```

### E7 — Documentação `docs/DEVELOPMENT.md`

Setup local completo:

```markdown
# Development Setup

## Pré-requisitos
- Python 3.10+ (recomendado 3.12)
- Git
- Docker Desktop (opcional, para containerização)

## Setup local

```bash
git clone <repo>
cd market_analysis

python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

pip install -e ".[dev]"

# Habilitar pre-commit hooks
pre-commit install
pre-commit install --hook-type pre-push
```

## Rodando testes

```bash
# Rápido (45s)
pytest tests/unit -q

# Completo
pytest tests/ -q

# Com coverage
pytest --cov=market_analysis --cov-report=html

# Apenas um arquivo
pytest tests/unit/test_strategy.py -v
```

## Lint e formatação

```bash
ruff check .          # análise
ruff check --fix .    # auto-fix
ruff format .         # formatação
mypy market_analysis/ # tipagem
```

## Docker

```bash
# Build
docker build -t market_analysis:dev .

# Rodar testes em container
docker run --rm market_analysis:dev

# Shell interativo
docker run -it --rm -v $(pwd):/app market_analysis:dev bash
```

## Troubleshooting

[Seção com problemas comuns e soluções]
```

### E8 — `start_control_center.bat` (placeholder)

Para uso futuro (Sprint 33), criar placeholder:

```batch
@echo off
REM market_analysis Control Center launcher
REM Será usado a partir do Sprint 33 (UI completa)
REM No Sprint 26: placeholder que apenas valida ambiente

call venv\Scripts\activate.bat
python -c "import strategy; print('Environment OK')"
pause
```

---

## 4. Critério de Aceitação

- [ ] CI roda em push e PR
- [ ] Matriz Python 3.10-3.13 × Ubuntu+Windows passa
- [ ] Tempo total de CI < 5 minutos
- [ ] Docker build < 3 minutos
- [ ] Imagem Docker < 500 MB
- [ ] Pre-commit hooks instalados e funcionando
- [ ] `pyproject.toml` consolida todas as dependências (sem `requirements.txt` divergente)
- [ ] `docs/DEVELOPMENT.md` documenta setup completo
- [ ] Release workflow constrói e publica imagem em tag

---

## 5. Riscos

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Testes que passam local quebram em CI (paths, env) | Alta | Investigar diferenças OS; usar `pathlib` em vez de strings |
| Imagem Docker muito grande | Média | Multi-stage build; slim base; cache de wheels |
| Pre-commit causa atrito | Média | Configurar apenas hooks rápidos (< 5s); pytest no pre-push, não pre-commit |
| GitHub Actions minutes esgotam | Baixa | Cache agressivo de pip; jobs paralelos em matrix |
| Windows-specific bugs | Alta | Matriz inclui windows-latest; testar localmente |

---

## 6. Notas para o Claude Code

- **Repositório**: este sprint pressupõe que o projeto está em GitHub. Se ainda não está, criar repo privado primeiro.
- **Secrets**: nenhum necessário neste sprint (Docker push usa GITHUB_TOKEN automaticamente).
- **Cache de pip**: usar `actions/setup-python` com `cache: 'pip'` reduz cold start de ~2min para ~30s.
- **Matriz mínima viável**: se créditos de CI forem limite, reduzir para `[ubuntu-latest, windows-latest]` × `[3.10, 3.12]` (4 jobs em vez de 8).
- **`continue-on-error: true` em mypy**: tipagem é progressiva; não bloquear merge por erros de tipagem.
- **Coverage threshold**: definir mínimo de 70% no Codecov config; falhar se cair abaixo.
- **Pre-commit no pre-push (não pre-commit)**: pytest é lento demais para rodar em cada commit. No pre-push é aceitável.

---

## 7. Comandos de validação

```bash
# Lint local (mimicar CI)
ruff check .
ruff format --check .
mypy market_analysis/ --ignore-missing-imports

# Testes em container
docker build -t market_analysis:test .
docker run --rm market_analysis:test pytest tests/unit -q

# Pre-commit
pre-commit run --all-files

# Validar workflow YAML
# (GitHub validates on push, mas pode testar localmente com `act`)
act -j lint
```

---

## 8. Estimativa detalhada

| Tarefa | Estimativa |
|---|---|
| E1 — Dockerfile | 0.5 dia |
| E2 — docker-compose | 0.25 dia |
| E3 — ci.yml | 0.5-1 dia |
| E4 — release.yml | 0.25 dia |
| E5 — pre-commit | 0.25 dia |
| E6 — pyproject.toml consolidado | 0.25-0.5 dia |
| E7 — DEVELOPMENT.md | 0.5 dia |
| Buffer (debugging CI failures) | 0.5-1 dia |
| **Total** | **3-5 dias** |
