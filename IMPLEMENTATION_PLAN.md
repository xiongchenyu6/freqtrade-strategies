# Chart Tooltips — Educational Hover/Click Layer

**Goal**: every chart gets a `ⓘ` button next to its title. Click opens a popover with **What / Why / How to read / Rules of thumb** so beginners learn metrics while reading the dashboard. Bilingual (zh / en).

**Architecture**:
- `src/lib/charts/glossary.ts` — single source of truth for metric copy (bilingual).
- `src/lib/components/chart-info.svelte` — reusable button + popover. Click-to-open, Esc closes, click-outside closes, ARIA `dialog`.
- Per-chart usage: `<ChartInfo metric="calmar" {lang} note="bars to the right = stronger" />` next to each `<h2>`.

---

## Stage 0: Infrastructure
**Goal**: ChartInfo component + glossary v1 ready to import on any page.
**Success Criteria**: Component evaluates in `vite build`; glossary covers the 15 most common metrics in zh + en.
**Tests**: Build passes; component renders a popover when clicked in dev.
**Status**: Complete (glossary 17 metrics, ChartInfo + popover, build clean)

## Stage 1: /archive (pilot)
**Goal**: Every chart `<h2>` on /archive has a ChartInfo button.
**Success Criteria**: ~25 chart cards have working tooltips; popover positioning OK on widescreen + mobile.
**Tests**: `pnpm exec vite build`; deploy; reload `/archive`; click 5 random tooltips.
**Status**: Complete (44 h2s wired, build clean, deployed)

## Stage 2: /strategies + /strategies/[name]
**Goal**: Strategy listing + detail pages.
**Status**: Complete (35 + 31 = 66 charts wired; glossary +11 entries: equityCurve, monteCarlo, expectancy, streak, exitReason, enterTag, holdingTime, calendar, rollingWinRate, portfolio)

## Stage 3: /factors
**Goal**: Factor attribution charts. May add factor-related glossary entries.
**Status**: Not Started

## Stage 4: /wf
**Goal**: Walk-forward analysis charts. Glossary entry: walk-forward window.
**Status**: Not Started

## Stage 5: /hyperopt
**Goal**: Hyperopt epoch-level charts. Glossary entries: epoch, loss function.
**Status**: Not Started

## Stage 6: /live
**Goal**: Live PnL / per-pair leaderboard / open trades.
**Status**: Not Started

## Stage 7: /dca
**Goal**: Smart DCA / event triggers. Glossary entries: Fear&Greed, severity, multiplier rules.
**Status**: Not Started

## Stage 8: / (home)
**Goal**: KPI grid + Market Regime block.
**Status**: Not Started

## Stage 9: /signals
**Goal**: Strategy freshness + sortino distribution.
**Status**: Not Started

---

## Done criteria for the whole effort
- All 9 pages have working ChartInfo on every chart card
- Glossary covers every metric referenced (no `metric not found` warnings in dev console)
- Build passes, deploy succeeds, mobile + desktop popover positions OK
- This file removed
