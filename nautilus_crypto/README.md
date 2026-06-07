# nautilus_crypto — crypto accumulation engine (NautilusTrader)

The crypto half of the Nautilus migration. Per the project philosophy, **crypto is now
pure accumulation, not speculation**: accumulate BTC for the long run, buy harder when
the crowd panics (Fear & Greed + drawdown), and never sell. This is the buy-the-dip
discipline ("别人恐慌我加码") expressed on the same engine as the US-equity side.

Runs on **real local Binance data** (`user_data/data/binance/BTC_USDT-1d.feather`,
2017–2026) and the real Fear & Greed history (`data/fng_history.csv`) — no exchange
account needed. Uses the shared `nautilus_equity/.venv`.

## Run

```bash
P=nautilus_equity/.venv/bin/python
$P nautilus_crypto/run_accumulation.py                 # smart vs naive DCA comparison
$P -m pytest nautilus_crypto/test_crypto_accumulator.py -q   # 8 tests, real data
```

## Result (BTC 2017-2026, weekly base DCA $500)

| | invested | BTC | avg cost | final value | ROI |
|---|---|---|---|---|---|
| **SMART** (fear+dip boosted) | $479.5k | 36.78 | **$13,037** | $2.83M | **+491%** |
| NAIVE (fixed interval) | $226.5k | 15.68 | $14,443 | $1.21M | +434% |

Smart DCA's fear/dip boosts buy harder at lower prices → **cost basis 9.73% lower,
ROI +57.5 pts** over plain DCA. Same number of scheduled buys; smart just sizes up in fear.

## Files
| File | Role |
|---|---|
| `crypto_data.py` | freqtrade feather → Nautilus bars; `FngSeries` Fear&Greed loader |
| `accumulator.py` | `Accumulator` strategy (smart/naive modes) |
| `run_accumulation.py` | smart-vs-naive backtest runner |
| `test_crypto_accumulator.py` | 8 tests on real data |

## Tunables (`AccumulatorConfig`)
`base_buy_usd`, `interval_bars` (7 = weekly on daily), `fear_threshold`/`fear_multiplier`,
`deep_fear_threshold`/`deep_fear_multiplier`, `dip_lookback`/`dip_threshold`/`dip_multiplier`,
`mode` ('smart'|'naive').

## Relationship to the existing Event/Smart DCA daemon
This is the **Nautilus-engine** accumulation strategy — it does NOT yet replace the live
`strategies/event_dca_bot.py` daemon (still dry-run, `DCA_LIVE_ENABLED=false`). It unifies
crypto onto the same engine + dashboard as equities and lets the dip-buying edge be
backtested rigorously. Migrating the live daemon onto this is a later, separate decision.

## Note
Local data ends 2026-04-17; re-download (freqtrade `download-data`) to extend through the
recent dip before drawing live conclusions.
