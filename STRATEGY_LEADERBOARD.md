# Strategy Leaderboard — Nautilus, all markets

Auto-updated by the `/loop … find best strategy` run. Each iteration tests a config/asset
on real data via the event-driven Nautilus ports and records the result here.
Metric notes: returns are single-asset, full available history, simple sizing (no leverage).
Risk-adjusted (Calmar) matters more than raw return.

## Crypto — trend (HonestTrend EMA72/144, FNG<80 gate) — asset × timeframe
| Asset | TF | entries | return (full hist) | notes |
|---|---|---|---|---|
| **ETH/USDT** | **1h** | 92 | **+119.1%** | 🏆 leader: ema72/144 adx25 (robust across adx15-25) |
| ETH/USDT | 1h | 39 | +110.4% | ema120/240 — also solid; slower=fewer trades |
| ETH/USDT | 15m | 343 | +70.5% | |
| **BTC/USDT** | **1h** | 25 | +48.2% | 1h beats 15m for BTC too |
| BTC/USDT | 15m | 121 | +27.8% | deployed to testnet prod (15m) |
| ETH/USDT | 4h | 15 | +27.5% | too few signals |
| BTC/USDT | 4h | 5 | −2.3% | too few signals |

**Finding:** 1h > 15m > 4h for BOTH BTC and ETH — the 1h timeframe (EMA72/144 ≈ 3d/6d
trend) is the generalizable sweet spot. The deployed testnet trend uses 15m → consider
switching to 1h.

**Leader risk-adjusted (ETH 1h ema72/144 adx25):** Sharpe **1.80**, Sortino 5.37, Profit
Factor 1.47, win rate 31.5% with ~6.4x payoff (avg win $6.2k vs avg loss $0.96k). Genuine
trend-following edge — not inflated raw return. Strong deploy candidate.

## Crypto — breakout (Donchian channel, ETH 1h) — VALIDATED at matched 10% sizing
| entry/exit lookback | entries | return @10% | Sharpe | notes |
|---|---|---|---|---|
| 168 / 72 | 167 | +46.9% | **2.71** | smoothest; single entry (no pyramid) |
| 96 / 48 | 262 | +49.7% | 2.24 | |

**Honest verdict (iter6's +2187% was a 95%-sizing illusion):** at MATCHED 10% sizing,
Donchian makes +47-50% vs EMA-cross's +119%. So:
- **Raw return: EMA-cross wins** (+119% > +47%) — its pyramid-on-winners compounds trends harder.
- **Risk-adjusted: Donchian wins** (Sharpe 2.71 > 1.80) — single-entry, smoother.
Different profiles. A higher-Sharpe engine can be sized up; best-of-both = Donchian + pyramid (next).

**Donchian + pyramid (iter8) — REJECTED:** +134.9% return but Sharpe **0.12** (collapsed).
Pyramiding stacks ~2.6x into one asset → return up, variance explodes. Pyramid is a
return↔smoothness tradeoff, not a free lunch. Notably EMA+pyramid keeps Sharpe 1.80 while
breakout+pyramid craters to 0.12 → EMA's entry timing pairs with pyramiding far better.

## Crypto — multi-asset trend portfolio (1h EMA72/144 adx25, shared account)
| portfolio | sizing | return | Sharpe | notes |
|---|---|---|---|---|
| **ETH + BTC** | 10% each | **+210.9%** | **2.41** | 🏆 BEST OVERALL — beats single-asset on BOTH dims |
| ETH only | 10% | +119.1% | 1.80 | |
| ETH+BTC+SOL+BNB | 5% each (~20% tot) | +291.6% | 2.20 | +return vs 2-asset, Sharpe plateaus |
| ETH+BTC+SOL+BNB | 7.5% each (~30%) | +679.0% | 2.16 | |
| ETH + BTC | 20% each | +676.6% | 1.70 | over-deployed → return↑ Sharpe↓ |

**Finding:** ETH+BTC diversification lifts BOTH return and Sharpe (2.41). Adding SOL+BNB at
the same ~20% total adds RETURN (+292%) but Sharpe plateaus/dips to ~2.20 — crypto majors
are all ~0.8 correlated + SOL adds vol, so marginal diversification fades. ~20% total is the
sweet spot. Best Sharpe = ETH+BTC (2.41); best return-at-risk = 4-asset (+292%/2.20).

## TRUE maxDD (iter13) — measured via an equity-curve Actor (USDT + position MTM per bar)
**ETH+BTC 1h @10% each: +210.9% / Sharpe 2.41 / TRUE maxDD = −13.2%** ✅ validated.

The iter11 −60%/−85% figures were a measurement bug (an.returns() cumprod). The honest maxDD
is only **−13%** — because the portfolio deploys just ~20% of equity and the trend exits cut
losers. Calmar ≈ 1.1 (vs BTC buy&hold's 0.64 with −76% DD). This is a genuinely strong,
low-drawdown strategy. Method: a lightweight Actor records total equity (USDT + Σ balance×close)
every bar → real drawdown. Use this Actor for all future DD numbers.

## Current best by objective (with the honest DD caveat)
- **OVERALL ✅:** ETH+BTC 1h multi-asset trend, 10% each → **+211% / Sharpe 2.41 / −13.2% maxDD** (validated)
- **Return-focused single:** ETH 1h EMA+pyramid → +119% / Sharpe 1.80
- **Smoothness single:** ETH 1h Donchian 168/72 → +47% / Sharpe 2.71

## Crypto — accumulation (fear-driven DCA)
| Variant | avg cost vs naive | ROI | notes |
|---|---|---|---|
| smart fear+dip DCA | −9.6% cost basis | +360% (through 2026-06 dip) | deployed testnet prod |

## Crypto — options (put-selling, free Tardis Deribit data 2019-2026)
| Variant | CAGR | maxDD | Calmar | notes |
|---|---|---|---|---|
| short-DTE (5-12d) put-sell | +7.4% | 7.6% | **0.97** | best risk-adj; synergy w/ accumulator cash |
| deepOTM put-sell | +10.0% | 19.5% | 0.51 | |
| naked CSP | +6.0% | 32.5% | 0.19 | |
| BTC buy&hold (benchmark) | +49.4% | 76.6% | 0.64 | nothing beats holding on raw return |

## Benchmarks to beat
- BTC buy&hold: +49% CAGR / 76.6% DD / Calmar 0.64
- Risk-adjusted bar: Calmar ~1.0 (short-DTE puts)

## Queue / ideas to test next
- [x] trend timeframe sweep on ETH → 1h wins (+116%)
- [x] BTC trend on 1h → yes, +48% > 15m's +28%; 1h generalizes
- [x] ETH 1h param sweep → ema72/144 adx25 best (+119%); 48/96 overtrades (cliff to 28%)
- [x] risk-adjusted for leader → Sharpe 1.80 / Sortino 5.37 (via engine.get_result)
- [x] Donchian breakout vs EMA → breakout Sharpe 2.71 > 1.80 (but sizing-inflated %)
- [x] Donchian @ matched 10% → +47% Sharpe 2.71 vs EMA +119% Sharpe 1.80 (sizing illusion debunked)
- [x] Donchian + pyramid → REJECTED (+135% but Sharpe 0.12; variance explodes)
- [x] multi-asset ETH+BTC → +211%/Sharpe 2.41, beats single on BOTH (best overall)
- [x] SOL/BNB added (4-asset) → +292%/Sharpe 2.20: more return, Sharpe plateaus (majors correlated)
- [x] maxDD attempt → RETRACTED (an.returns() cumprod is not true equity DD; stop-insensitive)
- [x] equity-curve Actor → TRUE maxDD −13.2% (iter11's −60% was a bug); strategy validated
- [ ] commit the leaderboard + equity Actor as reusable tooling  ← next
- [ ] DEPLOY: ETH+BTC 1h multi-asset trend (+211%/2.41/−13%) is the clear winner
- [ ] DEPLOY: multi-asset ETH+BTC 1h trend is the validated winner — switch testnet trend to it
- [ ] ETH/BNB/SOL accumulation (vs BTC) — need BNB/SOL data
- [ ] short-DTE put-sell on ETH (vs BTC)
- [ ] US equities (semis) trend — pending IB Mon
- [ ] DEPLOY CANDIDATE: ETH 1h trend to testnet prod (after a few more validations)
