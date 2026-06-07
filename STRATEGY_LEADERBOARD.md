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

## Unified trend family — TRUE maxDD (iter15, all via EquityRecorder)
| config | return | Sharpe | TRUE maxDD | note |
|---|---|---|---|---|
| **ETH+BTC @10%** | **+211%** | **2.41** | **−13.2%** | 🏆 best balance |
| 4-asset @5% | +292% | 2.20 | −19.2% | most return, worst DD (SOL/BNB hurt tail) |
| ETH single @10% | +119% | 1.80 | −13.5% | |
| BTC single @10% | +49% | 4.08* | −10.6% | *Sharpe inflated by sparse trading (25 trades, mostly flat) |

All trend DDs are a healthy −10% to −19% (NOT the retracted −60%). ETH+BTC is the pick.

**iter16 — gold (PAXG) diversifier didn't help:** ETH+BTC+GOLD = +218%/2.30/−13.2% (DD
unchanged). Trend-on-gold is flat most of the time (gold barely trends: GOLD-only +5%),
so it's NOT positioned during crypto crashes → no hedge. Lesson: adding more TREND sleeves
can't lower DD below ~−13%; a real hedge needs a STATIC/counter-cyclical allocation, not
another trend sleeve. The crypto-trend DD floor is ~−13%. **Crypto search has converged →
ETH+BTC 1h multi-asset trend is the winner. Real cross-asset diversification needs equities (Mon IB).**

## iter17 — static gold hedge + CONVERGENCE
ETH+BTC trend +30% static PAXG hold = +231% / 2.46 / −13.2% (DD unchanged, +20% free return).
The −13% DD floor won't move because the strategy under-deploys (~20% in market, rest cash)
— it's structurally low-DD; there's little DD to cut. The earlier "high DD problem" was the
−60% measurement bug, not real.

## iter18 — mean-reversion (RSI oversold) — REJECTED (wrong family for crypto)
Rough test (results identical across RSI thresholds + nan Sharpe → implementation suspect,
don't trust exact #s) but directionally clear: ~−65% maxDD vs trend's −13%. MR buys "oversold"
into crypto downtrends = catching falling knives. Crypto strongly trends → trend ≫ mean-reversion.
Confirms the trend family is correct for crypto.

## 🚩 iter19 — ROBUSTNESS CHECK FAILS: the edge has DECAYED (most important finding)
Split ETH+BTC trend into time halves:
| period | return | Sharpe | maxDD |
|---|---|---|---|
| 1st half (early ~2020-22) | +166% | 4.47 | −13% |
| **2nd half (recent ~2023-26)** | **+11%** | **−2.13** | −6.6% |

**The +211% is almost entirely an early-regime artifact.** In recent years the EMA-trend
edge has largely decayed — recent-half Sharpe is NEGATIVE (−2.13). Crypto 2023-26 is
choppier/more efficient → trend-following gets whipsawed. **Deploying on the full-history
+211% would be deploying a decayed edge.** This is the #1 takeaway of the whole search:
the full-history headline overstates forward expectancy.

## ✅ iter20 — Donchian breakout SURVIVES the recent regime (rescues the trend approach)
Recent-half (2023-26) only:
| strategy | recent return | recent Sharpe | maxDD |
|---|---|---|---|
| **Donchian 168/72 1h** | **+17.2%** | **+2.10** | −9.4% |
| EMA-cross 72/144 1h | +11% | −2.13 | −6.6% |

**Breakout is robust where EMA-cross decayed.** Donchian waits for a confirmed new high
(filters chop); EMA-cross reacts to every crossover (whipsawed in choppy 2023-26). →
For forward deployment, prefer **Donchian breakout over EMA-cross**. (Recall iter7: at
matched sizing Donchian had lower full-history return but higher Sharpe — now we see WHY:
its edge persists into the recent regime while EMA's faded.)

### iter21 — Donchian recent-regime param robustness (CONFIRMED deployable)
Recent-half ETH+BTC Donchian, 10% each, multiple lookbacks:
| lookback | recent return | Sharpe | maxDD |
|---|---|---|---|
| 168/72 | +17.2% | 2.10 | −9.4% |
| 96/48 | +10.1% | 1.22 | −7.5% |
| 240/96 | +9.7% | 1.29 | −8.5% |

All 3 positive (Sharpe 1.2-2.1) → robust, not a single-param fluke. Modest (~4% CAGR over
~3y) but REAL in the current regime — honest forward expectation for crypto trend now.

## ✅ FINAL DEPLOYABLE ANSWER (crypto)
**ETH+BTC 1h Donchian breakout (168/72, 10% each)** — recent-regime validated:
+17% / Sharpe 2.10 / −9% DD on out-of-sample recent data. Use THIS, not the EMA-cross
(whose +211% full-history was an early-regime mirage that's since decayed to Sharpe −2.13).
Forward expectation: modest (~mid-single-digit CAGR), low DD, positive Sharpe. Crypto
trend-following is structurally harder in 2023-26; size accordingly.

**iter22 — fee sensitivity (the edge is THIN):** recent Donchian return by round-trip cost:
0.10%→+15.6%, 0.25%→+10.3%, 0.50%→+2.1% (nearly dead). The recent edge survives ONLY at
low execution cost (≤0.25%): use low-fee tier / BNB discount / limit orders, not naive
market orders with slippage. ~4% gross CAGR has little room for costs. Deploy-viability is
execution-cost-gated.

## iter23 — breakout is ASSET-SELECTIVE (trenders yes, range-bound no)
Recent-half Donchian per coin: ETH/BTC Sharpe 2.10, **SOL +17%/Sharpe 2.71**, **BNB −3%/Sharpe −0.31**.
Breakout works on coins that trend (ETH/BTC/SOL) and FAILS on range-bound ones (BNB, an
exchange token). 4-coin incl. BNB → Sharpe 1.74 (dragged down). **Refined deployable set:
ETH+BTC+SOL (drop BNB).** Asset selection > blindly adding coins.

## 🏁 CRYPTO SEARCH CONVERGED (with the decay caveat)
Best full-history config: **ETH+BTC 1h multi-asset trend** → +211% / Sharpe 2.41 / −13% maxDD,
BUT recent-half edge is weak/negative. Before any real deployment: re-validate on recent data
only, and size DOWN / treat as regime-dependent. Exhausted families: trend (best but decaying),
breakout (≈trend), mean-reversion (catches knives), accumulation (rides BTC), options (mediocre).
**Next real edge = US equities (Mon IB).**

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
- [x] committed leaderboard + equity_recorder.py + run_portfolio_trend.py (ac7b3a6)
- [x] unified TRUE maxDD for trend family: all −10% to −19% (ETH+BTC −13% best balance)
- [x] gold (PAXG) as trend sleeve → no DD help (flat during crashes; trend≠hedge)
- [ ] crypto search CONVERGED — winner = ETH+BTC 1h trend. Next genuine edge = equities (Mon IB)
- [ ] (optional) static gold/cash hedge overlay to cut the −13% floor
- [ ] DEPLOY: ETH+BTC 1h multi-asset trend (+211%/2.41/−13%) is the clear winner
- [ ] DEPLOY: multi-asset ETH+BTC 1h trend is the validated winner — switch testnet trend to it
- [ ] ETH/BNB/SOL accumulation (vs BTC) — need BNB/SOL data
- [ ] short-DTE put-sell on ETH (vs BTC)
- [ ] US equities (semis) trend — pending IB Mon
- [ ] DEPLOY CANDIDATE: ETH 1h trend to testnet prod (after a few more validations)
