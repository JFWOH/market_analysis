"""Utilitario de download de dados reais com retry robusto e cache em disco.

Baixa dados historicos do Yahoo Finance com:
  - Retry exponencial (3 tentativas, 15/30/60 s de espera)
  - Cache em parquet (evita re-download em re-execucoes)
  - Fallback transparente para dados sinteticos se tudo falhar
  - Validacao de qualidade minima (N barras, sem NaN em Close)

Uso:
    python scripts/fetch_real_data.py          # so testa download
    python scripts/walk_forward_real.py        # WF completo
"""
from __future__ import annotations

import os
import sys
import time
import logging

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("fetch_real_data")

CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data_cache",
)
os.makedirs(CACHE_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _cache_path(ticker: str, start: str, end: str, interval: str) -> str:
    safe = ticker.replace("=", "_").replace("^", "").replace("/", "_")
    return os.path.join(CACHE_DIR, f"{safe}_{interval}_{start}_{end}.parquet")


def _normalize(data: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    """Normaliza MultiIndex, padroniza colunas OHLCV."""
    if data is None or data.empty:
        return None

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [col[0] if isinstance(col, tuple) else str(col)
                        for col in data.columns]

    required = ['Open', 'High', 'Low', 'Close', 'Volume']
    for col in required:
        if col not in data.columns:
            match = [c for c in data.columns if c.lower() == col.lower()]
            if match:
                data[col] = data[match[0]]

    if 'Close' not in data.columns:
        return None

    # Garantia de tipos
    for col in ['Open', 'High', 'Low', 'Close']:
        data[col] = pd.to_numeric(data[col], errors='coerce')
    if 'Volume' in data.columns:
        data['Volume'] = pd.to_numeric(data['Volume'], errors='coerce').fillna(0)
    else:
        data['Volume'] = 0.0

    # Remove linhas completamente sem Close
    data = data.dropna(subset=['Close'])

    # Filtra zeros espurios
    data = data[data['Close'] > 0]

    return data if not data.empty else None


def _make_synthetic(ticker: str, start: str, end: str,
                     interval: str) -> pd.DataFrame:
    """Gera dados sinteticos calibrados para o ativo."""
    import hashlib
    seed = int(hashlib.md5(f"{ticker}{start}{end}".encode()).hexdigest()[:8], 16) % (2**31)
    rng = np.random.default_rng(seed)

    vol_map = {'^BVSP': 0.012, 'USDBRL=X': 0.007}
    start_map = {'^BVSP': 120_000.0, 'USDBRL=X': 5.20}
    daily_vol = vol_map.get(ticker, 0.01)
    start_price = start_map.get(ticker, 100.0)

    # Calcula numero de barras
    try:
        n_days = len(pd.bdate_range(start, end))
    except Exception:
        n_days = 252

    if interval == '1d':
        n = n_days
        freq = 'B'
        idx = pd.bdate_range(start, periods=n)
    else:  # 1h
        n = n_days * 8
        freq = '1h'
        days = pd.bdate_range(start, periods=n_days)
        idx = pd.DatetimeIndex([
            pd.Timestamp(d) + pd.Timedelta(hours=h)
            for d in days for h in range(10, 18)
        ])
        n = len(idx)
        daily_vol /= 8**0.5

    log_ret = rng.normal(0, daily_vol, size=n)
    close = start_price * np.exp(np.cumsum(log_ret))
    intra = np.abs(rng.normal(0, daily_vol * 0.6, size=n))
    high  = close * (1 + intra)
    low   = close * (1 - intra)
    open_ = np.concatenate(([start_price], close[:-1]))

    return pd.DataFrame({
        'Open':   open_,
        'High':   np.maximum(high, np.maximum(open_, close)),
        'Low':    np.minimum(low,  np.minimum(open_, close)),
        'Close':  close,
        'Volume': rng.integers(1_000_000, 5_000_000, size=n).astype(float),
    }, index=idx[:n])


# ─────────────────────────────────────────────────────────────────────────────
# Download com retry + cache
# ─────────────────────────────────────────────────────────────────────────────

def download(
    ticker: str,
    start: str,
    end: str,
    interval: str = '1d',
    max_retries: int = 3,
    base_wait: float = 15.0,
    use_cache: bool = True,
    min_bars: int = 50,
) -> tuple[pd.DataFrame, str]:
    """Baixa dados com retry e cache. Retorna (df, source).

    source pode ser: 'cache', 'yfinance', 'synthetic'
    """
    cpath = _cache_path(ticker, start, end, interval)

    # 1. Tenta cache
    if use_cache and os.path.exists(cpath):
        try:
            df = pd.read_parquet(cpath)
            if len(df) >= min_bars:
                print(f"  [cache]  {ticker} {interval} {start}→{end}: "
                      f"{len(df)} barras")
                return df, 'cache'
        except Exception:
            pass

    # 2. Tenta Yahoo Finance v8 API (funciona mesmo com rate limit do yf.download)
    #    Usa session com headers de browser — evita bloqueio por User-Agent.

    import requests
    from datetime import datetime as _dt

    # Mapeamento de tickers para URL-encode correto da API v8
    _ticker_map = {
        '^BVSP': '%5EBVSP',
        'USDBRL=X': 'USDBRL%3DX',
    }
    ticker_url = _ticker_map.get(ticker, ticker)

    # Intervalo: API v8 aceita '1d', '1h', '5m', etc.
    _interval_map = {'1d': '1d', '1h': '1h', '30m': '30m', '15m': '15m'}
    iv = _interval_map.get(interval, '1d')

    # Range em timestamps UNIX
    try:
        ts1 = int(_dt.strptime(start, '%Y-%m-%d').timestamp())
        ts2 = int(_dt.strptime(end,   '%Y-%m-%d').timestamp())
    except Exception:
        ts1, ts2 = 1672531200, 1735689600  # 2023-01-01 a 2025-01-01

    session = requests.Session()
    session.headers.update({
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/120.0.0.0 Safari/537.36'),
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://finance.yahoo.com/',
        'Origin': 'https://finance.yahoo.com',
    })

    last_err = None
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                wait = base_wait * (2 ** (attempt - 1))
                print(f"  [yf-v8] tentativa {attempt+1}/{max_retries} "
                      f"para {ticker} (aguardando {wait:.0f}s)...")
                time.sleep(wait)
            else:
                time.sleep(1.5)   # pausa leve preventiva

            # Cookies da pagina principal (necessario para session valida)
            if attempt == 0:
                try:
                    session.get('https://finance.yahoo.com', timeout=10)
                    time.sleep(1.0)
                except Exception:
                    pass  # continua mesmo sem cookies

            url = (f'https://query1.finance.yahoo.com/v8/finance/chart/'
                   f'{ticker_url}?interval={iv}'
                   f'&period1={ts1}&period2={ts2}&events=history')

            resp = session.get(url, timeout=20)
            if resp.status_code == 429:
                last_err = "rate limited (429)"
                continue
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}"
                continue

            data = resp.json()
            result = data.get('chart', {}).get('result', [])
            if not result:
                last_err = "resposta vazia da API"
                continue

            r0 = result[0]
            timestamps = r0.get('timestamp', [])
            q = r0.get('indicators', {}).get('quote', [{}])[0]
            adj = r0.get('indicators', {}).get('adjclose', [{}])

            if len(timestamps) < min_bars:
                last_err = f"poucos dados ({len(timestamps)} barras)"
                continue

            closes = (adj[0].get('adjclose', q.get('close', [])) if adj
                      else q.get('close', []))
            df = pd.DataFrame({
                'Open':   q.get('open',   [None]*len(timestamps)),
                'High':   q.get('high',   [None]*len(timestamps)),
                'Low':    q.get('low',    [None]*len(timestamps)),
                'Close':  closes,
                'Volume': q.get('volume', [0]*len(timestamps)),
            }, index=pd.to_datetime(timestamps, unit='s', utc=True)
                             .tz_convert('America/Sao_Paulo')
                             .tz_localize(None))

            df = _normalize(df, ticker)
            if df is not None and len(df) >= min_bars:
                try:
                    df.to_parquet(cpath)
                except Exception:
                    pass
                print(f"  [yf-v8] {ticker} {interval} {start}->{end}: "
                      f"{len(df)} barras")
                return df, 'yfinance'
            else:
                last_err = f"poucos dados apos normalizacao"

        except Exception as e:
            last_err = str(e)[:120]

    # 3. Fallback sintetico
    print(f"  [synth] {ticker} — fallback sintetico "
          f"(yfinance falhou: {last_err})")
    df = _make_synthetic(ticker, start, end, interval)
    return df, 'synthetic'


# ─────────────────────────────────────────────────────────────────────────────
# Teste rapido de conectividade
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)
    print("=" * 60)
    print("  Teste de download — Yahoo Finance")
    print("=" * 60)

    tests = [
        ('^BVSP',    '2023-01-01', '2024-12-31', '1d'),
        ('USDBRL=X', '2023-01-01', '2024-12-31', '1d'),
        ('^BVSP',    '2024-10-01', '2024-12-31', '1h'),
        ('USDBRL=X', '2024-10-01', '2024-12-31', '1h'),
    ]

    results = []
    for ticker, start, end, iv in tests:
        df, src = download(ticker, start, end, interval=iv,
                           max_retries=2, base_wait=15.0)
        ok = len(df) > 50
        results.append((ticker, iv, len(df), src, ok))
        status = "OK" if ok else "FALHOU"
        print(f"  [{status}] {ticker:12s} {iv:3s}  {len(df):5d} barras  fonte={src}")

    real = sum(1 for *_, s, ok in results if s == 'yfinance' and ok)
    print(f"\n  {real}/{len(tests)} downloads reais OK")
    if real == 0:
        print("  AVISO: sem acesso ao Yahoo Finance — WF usara dados sinteticos.")
    elif real < len(tests):
        print("  AVISO: alguns downloads falharam — WF usara fallback sintetico para esses.")
    else:
        print("  Tudo OK — WF pode usar dados reais.")
