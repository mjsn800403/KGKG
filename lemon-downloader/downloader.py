#!/usr/bin/env python3
"""
LEMON Manuals Downloader
------------------------
Give it a Brand/Year page URL. It finds every vehicle listed on that page and
downloads each one's offline .zip manual into an output folder.

The site protects the .zip behind a tiny "human verification": the bundle URL
returns an HTML form, and the real .zip is only served when you POST the word
"human". This script does that automatically.

Usage:
    python3 downloader.py                         # asks for the link
    python3 downloader.py "<brand_year_url>"      # link as argument
    python3 downloader.py "<url>" --workers 3 --output-dir /root/downloads

Example URL:
    https://lemon-manuals.org.ua/Toyota/2025/
"""

import argparse
import os
import re
import sys
import time
import zipfile
import threading
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
    from bs4 import BeautifulSoup
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("[INFO] Installing required packages (requests, beautifulsoup4)...")
    pkgs = "requests beautifulsoup4"
    if os.system(f"{sys.executable} -m pip install --quiet {pkgs}") != 0:
        # Debian/Ubuntu PEP 668 "externally-managed-environment" fallback.
        os.system(f"{sys.executable} -m pip install --quiet --break-system-packages {pkgs}")
    import requests
    from bs4 import BeautifulSoup
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry


BASE_URL = "https://lemon-manuals.org.ua"
CAPTCHA_ANSWER = "human"   # the site asks you to literally type "human"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# One lock so concurrent workers don't interleave log lines into garbage.
_print_lock = threading.Lock()


class Throttle:
    """Ensure a minimum gap between request starts across all worker threads."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self):
        if self.min_interval <= 0:
            return
        with self._lock:
            gap = self.min_interval - (time.monotonic() - self._last)
            if gap > 0:
                time.sleep(gap)
            self._last = time.monotonic()


# Configured in main(); spaces out requests to avoid the site's 429 rate limit.
THROTTLE = Throttle(0.0)


def log(msg: str):
    with _print_lock:
        print(f"[INFO] {msg}", flush=True)


def err(msg: str):
    with _print_lock:
        print(f"[ERROR] {msg}", file=sys.stderr, flush=True)


def sanitize_filename(name: str) -> str:
    """Remove/replace characters invalid in filenames."""
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip()


def build_session(workers: int) -> requests.Session:
    """A session with retries/backoff and a connection pool sized to the workers."""
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(
        total=6,
        connect=5,
        read=5,
        status=6,
        backoff_factor=2.0,            # 0,2,4,8,16,32s between retries
        backoff_max=120,
        # 429 = rate limited -> retry (urllib3 honours the Retry-After header).
        status_forcelist=(429, 500, 502, 503, 504),
        respect_retry_after_header=True,
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=max(workers, 4))
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def correct_brand_case(session: requests.Session, url: str) -> str:
    """
    The site is case-sensitive (/Toyota/ works, /toyota/ 404s). Look up the
    brand's canonical spelling on the homepage and fix the first path segment,
    so the user can type the brand in any case.
    """
    raw_parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    if not raw_parts:
        return url
    brand_dec = unquote(raw_parts[0])
    try:
        resp = session.get(f"{BASE_URL}/", timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            h = a["href"].strip("/")
            if not h or "/" in h or "." in h:
                continue
            if unquote(h).lower() == brand_dec.lower() and h != raw_parts[0]:
                fixed = f"{BASE_URL}/" + "/".join([h] + raw_parts[1:]) + "/"
                log(f"Corrected brand case: '{raw_parts[0]}' -> '{h}'")
                return fixed
    except requests.RequestException:
        pass
    return url


def get_vehicles(session: requests.Session, year_url: str) -> list:
    """
    Parse a Brand/Year page and return the list of vehicles on it.
    Each item: {"name", "url", "bundle_url"}.
    """
    log(f"Fetching vehicle list from: {year_url}")
    resp = session.get(year_url, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    vehicles = []
    seen = set()

    # Real vehicle links are <a href="/Brand/Year/Model/"> (exactly 3 path parts).
    # The expandable model folders use href="javascript:void(0)" and are skipped.
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if not href.startswith("/") or href.startswith("//"):
            continue
        if href in ("/", "/about.html", "/nfo.html"):
            continue

        parts = href.strip("/").split("/")
        if len(parts) != 3:
            continue

        brand, year, model = parts
        bundle_url = f"{BASE_URL}/bundle/{brand}/{year}/{model}/"
        if bundle_url in seen:
            continue
        seen.add(bundle_url)

        vehicles.append({
            "name": unquote(model),
            "url": urljoin(BASE_URL, href),
            "bundle_url": bundle_url,
        })

    log(f"Found {len(vehicles)} vehicle(s)")
    return vehicles


def _filename_from_disposition(resp, fallback: str) -> str:
    """Use the server-suggested filename if present, else the model name."""
    cd = resp.headers.get("content-disposition", "")
    m = re.search(r'filename="?([^"]+)"?', cd)
    name = m.group(1) if m else f"{fallback}.zip"
    if not name.lower().endswith(".zip"):
        name += ".zip"
    return sanitize_filename(name)


def download_bundle(session: requests.Session, vehicle: dict, output_dir: Path) -> str:
    """
    Download one vehicle's .zip. Returns "ok", "skip", or "fail".

    Flow: POST captcha=human to the bundle URL -> stream the real .zip.
    Writes to a .part temp file and atomically renames on success, so an
    interrupted download never looks complete.
    """
    safe_name = sanitize_filename(vehicle["name"])
    zip_path = output_dir / f"{safe_name}.zip"

    # Already have a VALID zip? skip. A corrupt leftover (e.g. from the old
    # broken version) is not a valid zip -> fall through and re-download.
    if zip_path.exists() and zipfile.is_zipfile(zip_path):
        log(f"[skip] already downloaded: {zip_path.name}")
        return "skip"

    part_path = zip_path.with_suffix(".zip.part")
    THROTTLE.wait()
    log(f"[start] {vehicle['name']}")

    try:
        with session.post(
            vehicle["bundle_url"],
            data={"captcha": CAPTCHA_ANSWER},
            stream=True,
            timeout=180,
        ) as resp:
            if resp.status_code == 404:
                err(f"[404] bundle not found: {vehicle['name']}")
                return "fail"
            resp.raise_for_status()

            ctype = resp.headers.get("content-type", "")
            if "zip" not in ctype and "octet-stream" not in ctype:
                err(f"[fail] {vehicle['name']}: server returned '{ctype}', not a zip "
                    f"(captcha flow may have changed)")
                return "fail"

            final_name = _filename_from_disposition(resp, safe_name)
            zip_path = output_dir / final_name
            if zip_path.exists() and zipfile.is_zipfile(zip_path):
                log(f"[skip] already downloaded: {zip_path.name}")
                return "skip"

            downloaded = 0
            with open(part_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

        # Validate before committing the filename.
        if not zipfile.is_zipfile(part_path):
            err(f"[fail] {vehicle['name']}: downloaded data is not a valid zip")
            part_path.unlink(missing_ok=True)
            return "fail"

        os.replace(part_path, zip_path)
        log(f"[done] {zip_path.name} ({downloaded / 1024 / 1024:.1f} MB)")
        return "ok"

    except requests.RequestException as e:
        err(f"[fail] {vehicle['name']}: {e}")
        part_path.unlink(missing_ok=True)
        return "fail"


def resolve_output_dir(cli_value: str) -> Path:
    """Pick the output directory: CLI > env LEMON_OUTPUT_DIR > /root/downloads (root) > ~/Downloads/lemon."""
    if cli_value:
        return Path(cli_value).expanduser()
    env = os.environ.get("LEMON_OUTPUT_DIR")
    if env:
        return Path(env).expanduser()
    if os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() == 0:
        return Path("/root/downloads")
    return Path.home() / "Downloads" / "lemon"


def main():
    parser = argparse.ArgumentParser(
        description="Download offline .zip manuals from lemon-manuals.org.ua"
    )
    parser.add_argument("url", nargs="?", help="Brand/Year page URL (asked interactively if omitted)")
    parser.add_argument("--output-dir", default="", help="Where to save .zip files")
    parser.add_argument("--workers", type=int, default=2, help="Parallel downloads (default: 2)")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Minimum seconds between request starts, across all workers (default: 2.0)")
    parser.add_argument("--dry-run", action="store_true", help="List vehicles, download nothing")
    args = parser.parse_args()

    url = args.url or input("Enter Brand/Year URL (e.g. https://lemon-manuals.org.ua/Toyota/2025/): ").strip()
    if "lemon-manuals.org.ua" not in url:
        err("URL must be from lemon-manuals.org.ua")
        sys.exit(1)

    workers = max(1, args.workers)
    session = build_session(workers)

    global THROTTLE
    THROTTLE = Throttle(args.delay)   # space out requests to dodge 429 rate limits

    # Site is case-sensitive; fix the brand spelling so any case works.
    url = correct_brand_case(session, url)

    # Folder name from the URL path, e.g. .../Toyota/2025/ -> Toyota_2025
    path_parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    brand_year = "_".join(unquote(p) for p in path_parts[-2:]) if len(path_parts) >= 2 else "manuals"
    save_dir = resolve_output_dir(args.output_dir) / sanitize_filename(brand_year)
    save_dir.mkdir(parents=True, exist_ok=True)
    log(f"Output directory: {save_dir.resolve()}")

    vehicles = get_vehicles(session, url)
    if not vehicles:
        err("No vehicles found. Check the URL.")
        sys.exit(1)

    if args.dry_run:
        print("\n=== DRY RUN — vehicles found ===")
        for i, v in enumerate(vehicles, 1):
            print(f"  {i:3}. {v['name']}")
            print(f"       {v['bundle_url']}")
        print(f"\nTotal: {len(vehicles)} vehicles")
        return

    log(f"Downloading {len(vehicles)} vehicle(s) with {workers} worker(s)...\n")
    counts = {"ok": 0, "skip": 0, "fail": 0}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for v in vehicles:
            futures[pool.submit(download_bundle, session, v, save_dir)] = v
        for fut in as_completed(futures):
            counts[fut.result()] += 1

    print("\n" + "=" * 50)
    log(f"Done. ok={counts['ok']}  skipped={counts['skip']}  failed={counts['fail']}")
    log(f"Files saved in: {save_dir.resolve()}")
    if counts["fail"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
