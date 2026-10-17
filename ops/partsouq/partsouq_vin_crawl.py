"""Polite partsouq crawl of ONE vehicle (VIN catalog, new /catalog/toyota/ layout).

Saves the groups page, the category pages and every diagram page (HTML), the
diagram images, and parts.json / parts.csv parsed from each diagram's hotspots.
One tab, randomised 4-8 s between pages, resumable (skips pages on disk), and it
STOPS on a persistent Cloudflare challenge instead of hammering.

usage: ps_vin_crawl.py <groups-url> <out-dir>
"""
import asyncio, base64, csv, html as H, json, os, random, re, sys, time
from urllib.parse import urljoin, urlparse
import nodriver as nd

START, OUT = sys.argv[1].split("?")[0], sys.argv[2]
BASE = "https://partsouq.com"
DELAY = (4.0, 8.0)
MAX_BLOCKED = 3          # consecutive challenge pages -> stop for today

os.makedirs(os.path.join(OUT, "pages"), exist_ok=True)
os.makedirs(os.path.join(OUT, "images"), exist_ok=True)
LOG = open(os.path.join(OUT, "crawl.log"), "a", encoding="utf-8")

def log(m):
    line = time.strftime("[%H:%M:%S] ") + m
    print(line, flush=True); LOG.write(line + "\n"); LOG.flush()

def fname(url):
    p = urlparse(url).path
    m = re.search(r"/category/(\d+)/diagram/(\w+)", p)
    if m: return f"diagram_c{m.group(1)}_{m.group(2)}.html"
    m = re.search(r"/category/(\d+)/vin/", p)
    if m: return f"category_{m.group(1)}.html"
    return "groups.html"

async def fetch(tab, url):
    await tab.get(url)
    for _ in range(20):
        await asyncio.sleep(1.5)
        h = await tab.get_content()
        if "Just a moment" not in h and "</html>" in h.lower() and len(h) > 20000:
            return h
    return None

def hotspots(h):
    out = []
    for tag in re.findall(r'<div[^>]+class="hotspot"[^>]*>', h):
        d = {k: H.unescape(v) for k, v in re.findall(r'data-([a-z-]+)="([^"]*)"', tag)}
        out.append(d)
    return out

async def main():
    browser = await nd.start(host="127.0.0.1", port=9222)
    tab = await browser.get("about:blank", new_tab=True)
    queue, seen, blocked = [START], {START}, 0
    parts, n = [], 0
    try:
        while queue:
            url = queue.pop(0)
            path = os.path.join(OUT, "pages", fname(url))
            if os.path.exists(path):
                h = open(path, encoding="utf-8").read()
            else:
                await asyncio.sleep(random.uniform(*DELAY))
                h = await fetch(tab, url)
                if h is None:
                    blocked += 1
                    log(f"!! blocked/empty ({blocked}/{MAX_BLOCKED}): {url}")
                    if blocked >= MAX_BLOCKED:
                        log("!! STOPPING: Cloudflare keeps challenging; rerun later (resumes).")
                        break
                    queue.append(url)
                    await asyncio.sleep(30)
                    continue
                blocked = 0
                open(path, "w", encoding="utf-8").write(h)
                n += 1
                log(f"saved {fname(url)}  ({n} new, {len(queue)} queued)")
            for href in re.findall(r'href="(/en/catalog/toyota/(?:vehicle|diagram)/[^"]+)"', h):
                u = urljoin(BASE, H.unescape(href)).split("?")[0]
                if "/vin/" in u and u not in seen:
                    seen.add(u); queue.append(u)
            if "diagram_" in fname(url):
                title = re.search(r"<title>([^<]*)", h)
                img = re.search(r'id="diagramImage"[^>]*src="([^"]+)"', h) or \
                      re.search(r'<img[^>]+src="([^"]+)"[^>]*id="diagramImage"', h)
                img_url = urljoin(BASE, img.group(1)) if img else ""
                if img_url:
                    ip = os.path.join(OUT, "images", os.path.basename(urlparse(img_url).path))
                    if not os.path.exists(ip):
                        try:
                            b64 = await tab.evaluate(
                                "fetch(%s).then(r=>r.arrayBuffer()).then(b=>{let s='',u=new Uint8Array(b);"
                                "for(let i=0;i<u.length;i+=32768)s+=String.fromCharCode.apply(null,u.subarray(i,i+32768));"
                                "return btoa(s)})" % json.dumps(img_url), await_promise=True)
                            if isinstance(b64, str) and b64:
                                open(ip, "wb").write(base64.b64decode(b64))
                            else:
                                log(f"   image not fetched: {img_url}")
                        except Exception as e:
                            log(f"   image error {img_url}: {e}")
                for d in hotspots(h):
                    d.update(diagram=fname(url)[:-5], page_title=H.unescape(title.group(1)) if title else "",
                             image=os.path.basename(urlparse(img_url).path), url=url)
                    parts.append(d)
    finally:
        await tab.close()
    json.dump(parts, open(os.path.join(OUT, "parts.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    keys = sorted({k for d in parts for k in d})
    with open(os.path.join(OUT, "parts.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(parts)
    diags = len([x for x in os.listdir(os.path.join(OUT, "pages")) if x.startswith("diagram_")])
    log(f"DONE: {diags} diagram pages, {len(os.listdir(os.path.join(OUT,'images')))} images, "
        f"{len(parts)} hotspot rows, {len({d.get('number') for d in parts})} distinct part numbers")

asyncio.run(main())
