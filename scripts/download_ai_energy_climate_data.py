#!/usr/bin/env python3
"""Download public AI energy/climate data and official-news snapshots."""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "docs/research/data/ai-energy-climate/manifest.csv"
USER_AGENT = "Mozilla/5.0 (compatible; quant-ai-energy-data-downloader/1.0)"


def fetch(url: str, dest: Path, timeout: int = 30) -> tuple[bool, str]:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            content_type = resp.headers.get("content-type", "")
    except (HTTPError, URLError, TimeoutError) as exc:
        return False, f"{type(exc).__name__}: {exc}"

    if len(data) < 512:
        return False, f"too_small:{len(data)}"

    tmp.write_bytes(data)
    tmp.replace(dest)
    return True, f"{len(data)} bytes {content_type}"


def main() -> int:
    manifest = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_MANIFEST
    out_dir = manifest.parent / "snapshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = manifest.parent / "download_log.csv"

    rows = list(csv.DictReader(manifest.open(newline="", encoding="utf-8")))
    results: list[dict[str, str]] = []

    for row in rows:
        policy = row["download_policy"].strip()
        filename = row["filename"].strip()
        url = (row["download_url"].strip() or row["url"].strip())
        dest = out_dir / filename

        if policy != "download_public_html":
            status, detail = "skipped", policy
        elif dest.exists() and dest.stat().st_size > 512:
            status, detail = "exists", f"{dest.stat().st_size} bytes"
        else:
            ok, detail = fetch(url, dest)
            status = "downloaded" if ok else "failed"
            time.sleep(0.35)

        results.append(
            {
                "id": row["id"],
                "type": row["type"],
                "filename": filename,
                "url": url,
                "status": status,
                "detail": detail,
            }
        )
        print(f"{status:10s} {filename} {detail}")

    with log_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "type", "filename", "url", "status", "detail"])
        writer.writeheader()
        writer.writerows(results)

    failed = [r for r in results if r["status"] == "failed"]
    downloaded = [r for r in results if r["status"] in {"downloaded", "exists"}]
    skipped = [r for r in results if r["status"] == "skipped"]
    print(f"summary downloaded_or_existing={len(downloaded)} skipped={len(skipped)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
