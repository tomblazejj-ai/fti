"""FTI LIVE DATA ENGINE (9. 11. 2026, test version — OFF unless settings live.enabled).

Provider adapters turn a stream into normalised ticks (bid, ask, quote time, receive time, provider, product);
the engine keeps for every instrument its state (LIVE / DELAYED / HISTORICAL / UNAVAILABLE), switches to a backup
provider only after the prices of both were proven compatible on simultaneous quotes, builds candles M1 … D1 on the
broker's grid (each provider its own history), stores ticks in one-minute blocks, measures every provider (connection,
latency, age, outages) and serves the app (SSE) and the AI gate (no LIVE price → no valid trade signal).

  instruments.py  the instruments, their products and feeds — one line per new market or provider
  providers.py    adapters (Deriv public WebSocket, Kraken WebSocket v2)
  engine.py       state, failover, candles, metrics
  storage.py      candles → market_bars, ticks → live_tick_blocks (own table, created only when the engine runs)
  runner.py       the engine in its own thread (FastAPI app or `python -m app.live.runner`)
"""
