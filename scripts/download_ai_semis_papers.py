#!/usr/bin/env python3
"""Download open AI-semiconductor papers from the research manifest."""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "docs/research/papers/ai-semiconductors/manifest.csv"
USER_AGENT = "Mozilla/5.0 (compatible; quant-research-paper-downloader/1.0)"


def download(url: str, dest: Path, timeout: int = 45) -> tuple[bool, str]:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            content_type = resp.headers.get("content-type", "")
    except (HTTPError, URLError, TimeoutError) as exc:
        return False, f"{type(exc).__name__}: {exc}"

    if len(data) < 1024:
        return False, f"too_small:{len(data)}"

    if not data.startswith(b"%PDF") and "pdf" not in content_type.lower():
        return False, f"not_pdf:{content_type or 'unknown'}"

    tmp.write_bytes(data)
    tmp.replace(dest)
    return True, f"{len(data)} bytes"


def main() -> int:
    manifest = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_MANIFEST
    out_dir = manifest.parent
    log_path = out_dir / "download_log.csv"

    rows = list(csv.DictReader(manifest.open(newline="", encoding="utf-8")))
    results: list[dict[str, str]] = []

    for row in rows:
        filename = row["filename"].strip()
        pdf_url = row["pdf_url"].strip()
        dest = out_dir / filename

        if not pdf_url:
            status, detail = "skipped", "no_pdf_url"
        elif dest.exists() and dest.stat().st_size > 1024:
            status, detail = "exists", f"{dest.stat().st_size} bytes"
        else:
            ok, detail = download(pdf_url, dest)
            status = "downloaded" if ok else "failed"
            time.sleep(0.35)

        results.append(
            {
                "id": row["id"],
                "topic": row["topic"],
                "filename": filename,
                "pdf_url": pdf_url,
                "status": status,
                "detail": detail,
            }
        )
        print(f"{status:10s} {filename} {detail}")

    with log_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "topic", "filename", "pdf_url", "status", "detail"])
        writer.writeheader()
        writer.writerows(results)

    failed = [r for r in results if r["status"] == "failed"]
    skipped = [r for r in results if r["status"] == "skipped"]
    downloaded = [r for r in results if r["status"] in {"downloaded", "exists"}]
    print(f"summary downloaded_or_existing={len(downloaded)} skipped={len(skipped)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
