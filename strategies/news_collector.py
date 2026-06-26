"""Curated market-news collector → quant.news_items (the real "news-driven" layer).

Pattern learned from World Monitor's aggregation architecture (our own implementation —
their code is AGPL, untouched): fetch a small CURATED list of market-relevant RSS feeds
server-side, dedupe by link, prune old rows; the web reads our API (works on Cloudflare
and for mainland users — same relay principle as market_collector).

Honesty rules: headlines verbatim with source attribution + outbound links. No rewriting,
no fabricated summaries. Curation IS the editorial act — sources are official (Fed/SEC/ECB)
or established desks, crypto + macro + equity only.

Runs via quant-news-collector.timer (every 20 min). Env: TIMESCALE_URL.
"""

from __future__ import annotations

import email.utils
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import psycopg2
import requests

FEEDS = [
    # (source, category, url) — every entry tested working before inclusion.
    # Source names must match SOURCE_HQ in web/.../lib/globe-data.ts for the globe pins.
    ("CoinDesk", "crypto", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "crypto", "https://cointelegraph.com/rss"),
    ("Decrypt", "crypto", "https://decrypt.co/feed"),
    ("The Block", "crypto", "https://www.theblock.co/rss.xml"),
    ("Bitcoin Magazine", "crypto", "https://bitcoinmagazine.com/.rss/full/"),
    ("Fed", "macro", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("SEC", "macro", "https://www.sec.gov/news/pressreleases.rss"),
    ("ECB", "macro", "https://www.ecb.europa.eu/rss/press.html"),
    ("Bank of England", "macro", "https://www.bankofengland.co.uk/rss/news"),
    ("MarketWatch", "equity", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("CNBC", "equity", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10001147"),
    # Global business desks — one per financial hub so the /globe map reflects
    # the real geography of market news, not just the US east coast.
    ("BBC Business", "global", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("Guardian Business", "global", "https://www.theguardian.com/uk/business/rss"),
    ("FT", "global", "https://www.ft.com/rss/home"),
    ("Nikkei Asia", "global", "https://asia.nikkei.com/rss/feed/nar"),
    ("SCMP", "global", "https://www.scmp.com/rss/12/feed"),
    ("Straits Times", "global", "https://www.straitstimes.com/news/business/rss.xml"),
    ("Economic Times", "global", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("ABC Business", "global", "https://www.abc.net.au/news/feed/51892/rss.xml"),
    ("France 24", "global", "https://www.france24.com/en/business/rss"),
    ("Al Jazeera", "global", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("DW", "global", "https://rss.dw.com/rdf/rss-en-bus"),
]
_HDRS = {"User-Agent": "Mozilla/5.0 (quant news collector; +https://quant.panda.qzz.io)"}
KEEP_DAYS = 14
PER_FEED_CAP = 30


def log(m: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {m}", flush=True)


def _text(el) -> str:
    return re.sub(r"\s+", " ", (el.text or "").strip()) if el is not None else ""


def parse_feed(xml_text: str) -> list[dict]:
    """RSS 2.0 + Atom tolerant item extraction (title/link/pubDate)."""
    out = []
    if isinstance(xml_text, str):
        xml_text = xml_text.lstrip("\ufeff")
        start = xml_text.find("<?xml")
        if start > 0:
            xml_text = xml_text[start:]
    try:
        root = ET.fromstring(xml_text.encode() if isinstance(xml_text, str) else xml_text)
    except ET.ParseError:
        # Some feeds ship stray control chars — strip and retry once.
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", xml_text)
        start = cleaned.find("<?xml")
        if start > 0:
            cleaned = cleaned[start:]
        try:
            root = ET.fromstring(cleaned.encode())
        except ET.ParseError:
            return out
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for item in root.iter("item"):  # RSS 2.0
        title = _text(item.find("title"))
        link = _text(item.find("link"))
        pub = _text(item.find("pubDate"))
        if title and link:
            out.append({"title": title, "link": link, "pub": pub})
    if not out:  # RSS 1.0 / RDF (namespaced items; date lives in dc:date) — Nikkei, DW
        rss1 = "{http://purl.org/rss/1.0/}"
        dc = "{http://purl.org/dc/elements/1.1/}"
        for item in root.iter(f"{rss1}item"):
            title = _text(item.find(f"{rss1}title"))
            link = _text(item.find(f"{rss1}link"))
            pub = _text(item.find(f"{dc}date"))
            if title and link:
                out.append({"title": title, "link": link, "pub": pub})
    if not out:  # Atom
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            title = _text(entry.find("atom:title", ns))
            le = entry.find("atom:link", ns)
            link = le.get("href", "") if le is not None else ""
            pub = _text(entry.find("atom:updated", ns))
            if title and link:
                out.append({"title": title, "link": link, "pub": pub})
    return out


def parse_date(s: str):
    if not s:
        return None
    try:
        return email.utils.parsedate_to_datetime(s)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def main() -> int:
    dsn = os.environ.get("TIMESCALE_URL", "")
    if not dsn:
        print("TIMESCALE_URL required", file=sys.stderr)
        return 2
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    total = 0
    for source, category, url in FEEDS:
        try:
            r = requests.get(url, timeout=15, headers=_HDRS)
            r.raise_for_status()
            items = parse_feed(r.text)[:PER_FEED_CAP]
        except Exception as e:
            log(f"{source} fetch failed: {e!r}")
            continue
        n = 0
        with conn.cursor() as cur:
            for it in items:
                # Feeds without per-item dates (e.g. Nikkei's RSS 1.0) get first-seen
                # time, otherwise they'd sort NULLS-LAST forever and never surface.
                pub = parse_date(it["pub"]) or datetime.now(timezone.utc)
                cur.execute(
                    """INSERT INTO quant.news_items (published_at, source, category, title, link)
                       VALUES (%s, %s, %s, %s, %s) ON CONFLICT (link) DO NOTHING""",
                    (pub, source, category, it["title"][:500], it["link"][:1000]),
                )
                n += cur.rowcount
        total += n
        if n:
            log(f"{source}: +{n} new")
    with conn.cursor() as cur:
        cur.execute("DELETE FROM quant.news_items WHERE fetched_at < now() - interval '%s days'" % KEEP_DAYS)
        if cur.rowcount:
            log(f"pruned {cur.rowcount} old rows")
    conn.close()
    log(f"done: {total} new items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
