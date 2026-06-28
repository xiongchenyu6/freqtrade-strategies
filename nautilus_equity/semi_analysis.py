"""NVDA-centric semiconductor supply-chain analysis → quant.semi_universe.

Downloads real daily prices (Yahoo chart endpoint, keyless) for the semiconductor value
chain around NVIDIA — upstream picks-and-shovels, accelerator peers, downstream demand —
computes performance / relative-strength / correlation / momentum, and mines grounded alpha
signals (catch-up laggards, momentum leaders, diversifiers). Powers the dashboard /semis page.

Honest data only: every number is computed from real Yahoo daily closes, no synthetic fills.

Run (print):  .venv-bots/bin/python nautilus_equity/semi_analysis.py
Load to DB:   sops exec-env secrets.env '.venv-bots/bin/python nautilus_equity/semi_analysis.py --load'
"""

from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import pandas as pd
import requests

# (symbol, name, tier, role). DB tier (coarse): core | upstream | peer | downstream | benchmark.
# The fine 9-stage value chain (materials → demand) is laid out in the frontend.
UNIVERSE = [
    # (symbol, name, tier, role, stage, trends). tier = coarse DB bucket (legacy); stage = fine
    # value-chain step; trends = technology-trend tags (map to the /semis bottleneck matrix).
    # 1) Raw materials — wafers, gases, electronic chemicals (consumed in the fab).
    ("ENTG", "Entegris", "upstream", "Advanced materials & purity / filtration", "materials", ["materials", "advanced-packaging"]),
    ("DD", "DuPont", "upstream", "Electronic materials & chemicals", "materials", ["materials"]),
    ("LIN", "Linde", "upstream", "Industrial & specialty gases for fabs", "materials", ["materials"]),
    # 2) Equipment — the machines inside the fab.
    ("ASML", "ASML", "upstream", "EUV lithography — prints the chips", "equipment", ["EUV", "High-NA", "advanced-node"]),
    ("AMAT", "Applied Materials", "upstream", "Deposition / wafer-fab equipment", "equipment", ["advanced-node", "advanced-packaging"]),
    ("LRCX", "Lam Research", "upstream", "Etch & deposition equipment", "equipment", ["advanced-node", "3D-NAND"]),
    ("KLAC", "KLA", "upstream", "Process control / inspection", "equipment", ["advanced-node", "process-control"]),
    ("TER", "Teradyne", "upstream", "Automated test equipment", "equipment", ["test", "advanced-packaging"]),
    ("MKSI", "MKS Instruments", "upstream", "Process subsystems & control", "equipment", ["advanced-node"]),
    # 3) EDA / IP — design the chips before they exist.
    ("ARM", "Arm Holdings", "upstream", "CPU IP / architecture licensing", "eda-ip", ["cpu-ip", "edge-AI"]),
    ("SNPS", "Synopsys", "upstream", "EDA chip-design software", "eda-ip", ["EDA", "AI-design"]),
    ("CDNS", "Cadence", "upstream", "EDA chip-design software", "eda-ip", ["EDA", "AI-design"]),
    # 4) Foundry — manufacturing.
    ("TSM", "TSMC", "upstream", "Foundry — fabricates the GPUs", "foundry", ["advanced-node", "2nm", "CoWoS", "advanced-packaging"]),
    ("GFS", "GlobalFoundries", "upstream", "Specialty foundry", "foundry", ["mature-node", "specialty"]),
    ("UMC", "United Microelectronics", "upstream", "Foundry", "foundry", ["mature-node", "specialty"]),
    # 5) Memory — HBM is the AI bottleneck.
    ("MU", "Micron", "upstream", "HBM high-bandwidth memory for AI GPUs", "memory", ["HBM", "memory-wall", "DRAM-NAND"]),
    # 6) OSAT — packaging & test (advanced packaging is the AI bottleneck).
    ("AMKR", "Amkor", "upstream", "OSAT — assembly & test / advanced packaging", "osat", ["advanced-packaging", "CoWoS"]),
    ("ASX", "ASE Technology", "upstream", "OSAT — assembly & test", "osat", ["advanced-packaging", "CoWoS"]),
    # 7) Chip designers — the AI / compute silicon.
    ("NVDA", "NVIDIA", "core", "AI accelerator leader — the hub of the AI build-out", "accelerator", ["accelerator", "CoWoS", "HBM", "NVLink"]),
    ("AVGO", "Broadcom", "peer", "Custom AI ASICs + networking silicon", "accelerator", ["custom-ASIC", "optical", "networking"]),
    ("AMD", "AMD", "peer", "GPU competitor (MI300) + CPUs", "accelerator", ["accelerator", "chiplet", "HBM"]),
    ("MRVL", "Marvell", "peer", "Custom AI silicon / interconnect", "accelerator", ["custom-ASIC", "optical", "CXL"]),
    ("QCOM", "Qualcomm", "peer", "Mobile / edge-AI SoCs", "processor", ["edge-AI", "mobile"]),
    ("TXN", "Texas Instruments", "peer", "Analog & embedded", "analog", ["analog", "power-integrity"]),
    ("INTC", "Intel", "peer", "CPU + foundry challenger", "processor", ["advanced-node", "foundry", "CPU"]),
    # 8) Interconnect / networking — the AI-cluster fabric.
    ("ANET", "Arista Networks", "downstream", "AI-cluster Ethernet switching", "networking", ["networking", "800G-1.6T", "ethernet"]),
    ("CRDO", "Credo", "downstream", "High-speed connectivity (AECs)", "networking", ["optical", "AEC", "800G-1.6T"]),
    ("COHR", "Coherent", "downstream", "Optical interconnect / transceivers", "networking", ["optical", "CPO", "silicon-photonics"]),
    # 9) Systems — AI servers / integrators.
    ("DELL", "Dell", "downstream", "AI server systems", "systems", ["systems", "liquid-cooling"]),
    ("SMCI", "Supermicro", "downstream", "AI server systems integrator", "systems", ["systems", "liquid-cooling"]),
    ("HPE", "HPE", "downstream", "AI servers (incl. Cray)", "systems", ["systems"]),
    # 10) Demand — hyperscaler capex.
    ("MSFT", "Microsoft", "downstream", "Hyperscaler — Azure AI capex", "hyperscaler", ["capex", "datacenter-power"]),
    ("GOOGL", "Alphabet", "downstream", "Hyperscaler — TPU + GPU buyer", "hyperscaler", ["capex", "custom-ASIC"]),
    ("AMZN", "Amazon", "downstream", "Hyperscaler — AWS capex", "hyperscaler", ["capex", "custom-ASIC"]),
    ("META", "Meta", "downstream", "Hyperscaler — largest AI capex ramp", "hyperscaler", ["capex", "custom-ASIC"]),
    ("ORCL", "Oracle", "downstream", "Cloud / OCI AI capex", "hyperscaler", ["capex", "datacenter-power"]),
    # 11) System power & thermal — the "can the whole AI server ship" layer (bottleneck matrix:
    #     liquid cooling, VRM/VPD, datacenter power & grid). System-level, not chip-level.
    ("VRT", "Vertiv", "downstream", "Liquid cooling + datacenter power infrastructure", "power-thermal", ["liquid-cooling", "datacenter-power"]),
    ("MPWR", "Monolithic Power", "peer", "VRM / power-management silicon", "power", ["VRM", "power-integrity"]),
    ("VICR", "Vicor", "peer", "Vertical power delivery modules", "power", ["VRM", "vertical-power"]),
    ("LITE", "Lumentum", "downstream", "Optical components / lasers for transceivers", "networking", ["optical", "CPO"]),
    ("GEV", "GE Vernova", "downstream", "Grid + power equipment for datacenters", "power-grid", ["datacenter-power", "grid"]),
    ("ETN", "Eaton", "downstream", "Electrical / power management for datacenters", "power-grid", ["datacenter-power", "grid"]),
    # Benchmarks.
    ("SMH", "VanEck Semis ETF", "benchmark", "Semiconductor sector benchmark", "benchmark", []),
    ("SPY", "S&P 500", "benchmark", "Broad market benchmark", "benchmark", []),
]

_YF = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=2y&interval=1d"
_HDRS = {"User-Agent": "Mozilla/5.0"}


def fetch_market_caps(symbols: list[str]) -> dict[str, float]:
    """Real market caps via Yahoo's crumb-gated quote endpoint (cookie → getcrumb → quote)."""
    caps: dict[str, float] = {}
    try:
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                        "AppleWebKit/537.36"})
        try:
            s.get("https://fc.yahoo.com", timeout=10)
        except Exception:
            pass
        crumb = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=10).text
        if not crumb or "<" in crumb:
            return caps
        # batch in chunks to keep the URL sane
        for i in range(0, len(symbols), 10):
            chunk = symbols[i:i + 10]
            r = s.get("https://query1.finance.yahoo.com/v7/finance/quote",
                      params={"symbols": ",".join(chunk), "crumb": crumb}, timeout=12)
            for q in r.json().get("quoteResponse", {}).get("result", []):
                if q.get("marketCap"):
                    caps[q["symbol"]] = float(q["marketCap"])
            time.sleep(0.2)
    except Exception as e:
        print(f"  ! market caps fetch failed ({e})", file=sys.stderr)
    return caps


def fetch_closes(symbol: str) -> pd.Series | None:
    try:
        r = requests.get(_YF.format(sym=symbol), headers=_HDRS, timeout=15)
        res = r.json()["chart"]["result"][0]
        ts = res["timestamp"]
        close = res["indicators"]["quote"][0]["close"]
        s = pd.Series(close, index=pd.to_datetime(ts, unit="s")).dropna()
        s.name = symbol
        return s
    except Exception as e:
        print(f"  ! {symbol}: fetch failed ({e})", file=sys.stderr)
        return None


def _ret(series: pd.Series, days: int) -> float | None:
    if len(series) < 2:
        return None
    ref_idx = max(0, len(series) - 1 - days)
    ref = series.iloc[ref_idx]
    return round(float(series.iloc[-1] / ref - 1) * 100, 2) if ref else None


def _ret_ytd(series: pd.Series) -> float | None:
    yr = series.index[-1].year
    ytd = series[series.index >= pd.Timestamp(year=yr, month=1, day=1)]
    if len(ytd) < 2 or not ytd.iloc[0]:
        return None
    return round(float(series.iloc[-1] / ytd.iloc[0] - 1) * 100, 2)


def analyze() -> list[dict]:
    caps = fetch_market_caps([sym for sym, *_ in UNIVERSE])
    closes: dict[str, pd.Series] = {}
    for sym, *_ in UNIVERSE:
        s = fetch_closes(sym)
        if s is not None and len(s) > 60:
            closes[sym] = s
        time.sleep(0.25)  # be polite to Yahoo

    nvda = closes.get("NVDA")
    smh = closes.get("SMH")
    nvda_ret = nvda.pct_change().dropna() if nvda is not None else None
    nvda_3m = _ret(nvda, 63) if nvda is not None else None
    smh_3m = _ret(smh, 63) if smh is not None else None

    rows = []
    for sym, name, tier, role, stage, trends in UNIVERSE:
        s = closes.get(sym)
        if s is None:
            continue
        r3 = _ret(s, 63)
        # correlation + beta vs NVDA on overlapping daily returns (~6m window)
        corr = beta = None
        if nvda_ret is not None and sym != "NVDA":
            rr = s.pct_change().dropna()
            j = pd.concat([rr, nvda_ret], axis=1, join="inner").tail(126).dropna()
            if len(j) > 30:
                a, b = j.iloc[:, 0], j.iloc[:, 1]
                corr = round(float(a.corr(b)), 2)
                var = float(b.var())
                beta = round(float(a.cov(b) / var), 2) if var else None
        vol = s.pct_change().dropna().tail(126)
        vol_ann = round(float(vol.std() * np.sqrt(252)) * 100, 1) if len(vol) > 20 else None
        peak = float(s.tail(252).max())
        from_high = round(float(s.iloc[-1] / peak - 1) * 100, 1) if peak else None
        rows.append({
            "symbol": sym, "name": name, "tier": tier, "role": role,
            "stage": stage, "trends": trends,
            "market_cap": caps.get(sym),
            "last_price": round(float(s.iloc[-1]), 2),
            "ret_1w": _ret(s, 5), "ret_1m": _ret(s, 21), "ret_3m": r3,
            "ret_6m": _ret(s, 126), "ret_1y": _ret(s, 252), "ret_ytd": _ret_ytd(s),
            "rs_vs_nvda": round(r3 - nvda_3m, 2) if (r3 is not None and nvda_3m is not None) else None,
            "rs_vs_smh": round(r3 - smh_3m, 2) if (r3 is not None and smh_3m is not None) else None,
            "corr_nvda": corr, "beta_nvda": beta, "vol_annual": vol_ann,
            "from_52w_high": from_high,
        })

    _score_and_annotate(rows)
    return rows


def _score_and_annotate(rows: list[dict]) -> None:
    """Composite momentum z-score + a grounded alpha rationale per name."""
    tradeable = [r for r in rows if r["tier"] != "benchmark"]
    mom = np.array([
        (0.6 * (r["ret_3m"] or 0) + 0.4 * (r["ret_6m"] or 0)) for r in tradeable
    ], dtype=float)
    mu, sd = mom.mean(), (mom.std() or 1.0)
    for r, m in zip(tradeable, mom):
        r["mom_score"] = round(float((m - mu) / sd), 2)

    # alpha_score blends momentum with a "catch-up" tilt: names tightly coupled to NVDA
    # (high corr/beta) but LAGGING it (negative rs_vs_nvda) are catch-up candidates.
    for r in tradeable:
        catchup = 0.0
        if r["corr_nvda"] and r["rs_vs_nvda"] is not None and r["corr_nvda"] >= 0.5 and r["rs_vs_nvda"] < 0:
            catchup = min(20.0, -r["rs_vs_nvda"]) * (r["corr_nvda"]) / 10.0
        r["alpha_score"] = round(float((r["mom_score"] or 0) + catchup), 2)
        r["alpha_note"] = _note(r)
    for r in rows:
        r.setdefault("mom_score", None)
        r.setdefault("alpha_score", None)
        r.setdefault("alpha_note", None)


def _note(r: dict) -> str:
    bits = []
    rs = r["rs_vs_nvda"]
    if r["tier"] == "core":
        return "Sector hub — every other name is measured against it."
    if r["corr_nvda"] and r["corr_nvda"] >= 0.55 and rs is not None and rs < -8:
        bits.append(f"Tightly coupled to NVDA (ρ={r['corr_nvda']}) but lagging {rs:+.0f}pp over 3m — catch-up candidate")
    elif (r["mom_score"] or 0) > 0.8:
        bits.append("Strong relative momentum — sector leader")
    elif (r["mom_score"] or 0) < -0.8:
        bits.append("Lagging momentum — avoid or mean-reversion only")
    if r["corr_nvda"] is not None and r["corr_nvda"] < 0.4:
        bits.append(f"Low NVDA correlation (ρ={r['corr_nvda']}) — diversifier")
    if r["from_52w_high"] is not None and r["from_52w_high"] > -5:
        bits.append("near 52w high (breakout)")
    elif r["from_52w_high"] is not None and r["from_52w_high"] < -25:
        bits.append(f"{r['from_52w_high']:.0f}% off highs (deep pullback)")
    return "; ".join(bits) or "neutral"


def load_rows(rows: list[dict]) -> int:
    import psycopg2
    url = os.environ.get("TIMESCALE_URL")
    if not url:
        sys.exit("TIMESCALE_URL not set (run via sops exec-env secrets.env '... --load')")
    conn = psycopg2.connect(url)
    conn.autocommit = True
    cols = ["symbol", "name", "tier", "role", "stage", "trends", "market_cap", "last_price",
            "ret_1w", "ret_1m", "ret_3m", "ret_6m", "ret_1y", "ret_ytd", "rs_vs_nvda", "rs_vs_smh",
            "corr_nvda", "beta_nvda", "vol_annual", "from_52w_high", "mom_score", "alpha_score", "alpha_note"]
    with conn.cursor() as cur:
        for r in rows:
            vals = {c: r.get(c) for c in cols}
            cur.execute(
                f"INSERT INTO quant.semi_universe ({', '.join(cols)}, updated_at) "
                f"VALUES ({', '.join('%(' + c + ')s' for c in cols)}, now()) "
                f"ON CONFLICT (symbol) DO UPDATE SET "
                + ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "symbol")
                + ", updated_at=now()",
                vals,
            )
    conn.close()
    return len(rows)


def main() -> int:
    rows = analyze()
    order = {"core": 0, "upstream": 1, "peer": 2, "downstream": 3, "benchmark": 4}
    rows_sorted = sorted(rows, key=lambda r: (order.get(r["tier"], 9), -(r.get("alpha_score") or -99)))
    print(f"{'sym':<6}{'tier':<11}{'price':>9}{'3m%':>7}{'1y%':>7}{'RSvsNVDA':>9}{'ρNVDA':>7}{'alpha':>7}  note")
    print("-" * 120)
    for r in rows_sorted:
        print(f"{r['symbol']:<6}{r['tier']:<11}{r['last_price']:>9}"
              f"{str(r['ret_3m']):>7}{str(r['ret_1y']):>7}{str(r['rs_vs_nvda']):>9}"
              f"{str(r['corr_nvda']):>7}{str(r.get('alpha_score')):>7}  {(r.get('alpha_note') or '')[:60]}")
    if "--load" in sys.argv:
        n = load_rows(rows)
        print(f"\n  loaded {n} rows → quant.semi_universe")
    else:
        print("\n  (dry run — pass --load with TIMESCALE_URL to write to DB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
