#!/usr/bin/env python3
"""
KGTV Source Downloader
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
    <Brand/Year URL>
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


BASE_URL = os.environ.get("KGTV_SOURCE_URL", "https://source-manuals.example.com")
CAPTCHA_ANSWER = "human"   # the site asks you to literally type "human"

# Rate-limit handling. On 429 / error, wait min(RL_WAIT*attempt, RL_WAIT_MAX)
# seconds and retry the same file, up to RL_RETRIES times (persistent enough to
# ride out the nginx block, which clears after ~60-90s of quiet).
RL_WAIT = 20
RL_WAIT_MAX = 120
RL_RETRIES = 20

# Seconds to wait before EVERY request, to pace requests and avoid bursts that
# trigger 429 in the first place. Set from --delay in main().
PACE_DELAY = 3.0

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
        total=3,
        connect=3,
        read=3,
        backoff_factor=1.0,            # 0s, 1s, 2s between retries
        status_forcelist=(500, 502, 503, 504),
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


def download_bundle(session: requests.Session, vehicle: dict, output_dir: Path) -> str:
    """
    Download one vehicle's .zip. Returns "ok", "skip", or "fail".

    Flow: POST captcha=human to the bundle URL -> stream the real .zip.
    Writes to a .part temp file and atomically renames on success, so an
    interrupted download never looks complete.
    """
    safe_name = sanitize_filename(vehicle["name"])

    # Name downloads with the ingestion convention the parser expects
    # ("KGTV <year> <brand> <model>.zip" — brand/year taken from the bundle
    # URL). Model-only names from earlier versions are still recognized for
    # skipping, but never written anymore.
    bp = [unquote(p) for p in urlparse(vehicle["bundle_url"]).path.strip("/").split("/")]
    if len(bp) == 4:   # ['bundle', brand, year, model]
        zip_path = output_dir / sanitize_filename(f"KGTV {bp[2]} {bp[1]} {bp[3]}.zip")
        candidates = [zip_path, output_dir / f"{safe_name}.zip"]
    else:
        zip_path = output_dir / f"{safe_name}.zip"
        candidates = [zip_path]

    # Already have a VALID zip? skip — WITHOUT hitting the server (avoids
    # needless 429s on re-runs).
    for c in candidates:
        if c.exists() and zipfile.is_zipfile(c):
            log(f"[skip] already downloaded: {c.name}")
            return "skip"

    part_path = zip_path.with_suffix(".zip.part")
    log(f"[start] {vehicle['name']}")

    # Persistent loop: the site (nginx) rate-limits bursts with 429 (no
    # Retry-After) and clears after ~60-90s of quiet. We pace every request and,
    # on any 429 / network hiccup / partial download, back off and retry the SAME
    # file with an escalating wait until it succeeds. Slower, but it always
    # finishes. Only a genuine 404 gives up.
    for attempt in range(1, RL_RETRIES + 1):
        if PACE_DELAY:
            time.sleep(PACE_DELAY)          # space requests so we don't trigger 429
        wait = min(RL_WAIT * attempt, RL_WAIT_MAX)
        try:
            with session.post(
                vehicle["bundle_url"],
                data={"captcha": CAPTCHA_ANSWER},
                stream=True,
                timeout=(30, 300),
            ) as resp:
                if resp.status_code == 404:
                    err(f"[404] bundle not found (giving up): {vehicle['name']}")
                    return "fail"
                if resp.status_code == 429:
                    log(f"[wait] {vehicle['name']}: server busy (429), pausing {wait}s "
                        f"then retrying (attempt {attempt}/{RL_RETRIES})")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()

                ctype = resp.headers.get("content-type", "")
                if "zip" not in ctype and "octet-stream" not in ctype:
                    log(f"[wait] {vehicle['name']}: got '{ctype or 'no type'}', "
                        f"pausing {wait}s then retrying (attempt {attempt}/{RL_RETRIES})")
                    time.sleep(wait)
                    continue

                downloaded = 0
                with open(part_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 64):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)

            # Validate the full file before committing it.
            if not zipfile.is_zipfile(part_path):
                log(f"[wait] {vehicle['name']}: incomplete download, pausing {wait}s "
                    f"then retrying (attempt {attempt}/{RL_RETRIES})")
                part_path.unlink(missing_ok=True)
                time.sleep(wait)
                continue

            os.replace(part_path, zip_path)
            log(f"[done] {zip_path.name} ({downloaded / 1024 / 1024:.1f} MB)")
            return "ok"

        except requests.RequestException as e:
            log(f"[wait] {vehicle['name']}: connection issue ({e.__class__.__name__}), "
                f"pausing {wait}s then retrying (attempt {attempt}/{RL_RETRIES})")
            part_path.unlink(missing_ok=True)
            time.sleep(wait)
            continue

    err(f"[fail] {vehicle['name']}: gave up after {RL_RETRIES} attempts")
    part_path.unlink(missing_ok=True)
    return "fail"


def resolve_output_dir(cli_value: str) -> Path:
    """Pick the output directory: CLI > env KGTV_OUTPUT_DIR > /root/downloads (root) > ~/Downloads/kgtv."""
    if cli_value:
        return Path(cli_value).expanduser()
    env = os.environ.get("KGTV_OUTPUT_DIR")
    if env:
        return Path(env).expanduser()
    if os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() == 0:
        return Path("/root/downloads")
    return Path.home() / "Downloads" / "kgtv"


def main():
    parser = argparse.ArgumentParser(
        description="Download offline .zip manuals from upstream source"
    )
    parser.add_argument("url", nargs="?", help="Brand/Year page URL (asked interactively if omitted)")
    parser.add_argument("--output-dir", default="", help="Where to save .zip files")
    parser.add_argument("--workers", type=int, default=1,
                        help="Parallel downloads (default: 1 = safest, no bursts)")
    parser.add_argument("--delay", type=float, default=3.0,
                        help="Seconds to wait before every request, to avoid 429 bursts (default: 3.0)")
    parser.add_argument("--dry-run", action="store_true", help="List vehicles, download nothing")
    parser.add_argument("--filter", default="", dest="name_filter", metavar="TEXT",
                        help="Only vehicles whose name contains TEXT (case-insensitive), "
                             "e.g. --filter 'corolla cross'")
    args = parser.parse_args()

    url = args.url or input("Enter Brand/Year URL: ").strip()
    if BASE_URL.split("//")[1].split("/")[0] not in url:
        err("Invalid source URL")
        sys.exit(1)

    workers = max(1, args.workers)
    session = build_session(workers)

    global PACE_DELAY
    PACE_DELAY = max(0.0, args.delay)   # pace every request to avoid 429 bursts

    # Site is case-sensitive; fix the brand spelling so any case works.
    url = correct_brand_case(session, url)

    # Folder name from the URL path, e.g. .../Toyota/2025/ -> Toyota_2025
    path_parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    brand_year = "_".join(unquote(p) for p in path_parts[-2:]) if len(path_parts) >= 2 else "manuals"
    save_dir = resolve_output_dir(args.output_dir) / sanitize_filename(brand_year)
    save_dir.mkdir(parents=True, exist_ok=True)
    log(f"Output directory: {save_dir.resolve()}")

    vehicles = get_vehicles(session, url)
    if args.name_filter:
        needle = args.name_filter.lower()
        vehicles = [v for v in vehicles if needle in v["name"].lower()]
        log(f"Filter '{args.name_filter}': {len(vehicles)} vehicle(s) match")
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
