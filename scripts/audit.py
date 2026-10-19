#!/usr/bin/env python3
"""
Automated website audit for the Innsbruck Tourist-Friendliness Index.

For every venue in data/venues_seed.csv this script:
  1. loads the venue's own homepage
  2. detects which languages the website offers (hreflang tags, language
     switchers, /en/ /it/ ... paths)
  3. finds menu links (Speisekarte, menu, carta, PDF menus) and downloads them
  4. reads each menu (HTML or PDF), flags scanned image-only PDFs, and
     estimates which languages the dishes are written in
  5. looks for EU allergen information and for online booking / ordering

It writes machine evidence to data/raw/auto_audit.json. The published index
(data/venues.csv) is the human-reviewed version of this evidence: the crawler
finds things fast, a person confirms them before anything is scored.

Usage:  python scripts/audit.py            # all venues
        python scripts/audit.py "Stiftskeller"   # one venue
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "data" / "venues_seed.csv"
OUT = ROOT / "data" / "raw" / "auto_audit.json"

HEADERS = {
    "User-Agent": "TouristFriendlinessIndex/1.0 (research project; "
    "+https://github.com/) Python-requests",
    "Accept-Language": "de,en;q=0.8",
}
TIMEOUT = 20

LANG_NAMES = {
    "de": ["de", "deutsch", "german"],
    "en": ["en", "english", "englisch"],
    "it": ["it", "italiano", "italian", "italienisch"],
    "fr": ["fr", "français", "francais", "french", "französisch"],
    "es": ["es", "español", "espanol", "spanish", "spanisch"],
    "nl": ["nl", "nederlands", "dutch"],
}

# Distinctive food-menu words per language. Short function words that are
# shared between languages (e.g. "con") are left out on purpose.
MENU_WORDS = {
    "de": ["mit", "und", "kartoffeln", "käse", "schwein", "kalb", "salat", "suppe", "rind", "gebraten", "hausgemacht"],
    "en": ["with", "served", "cheese", "pork", "veal", "potatoes", "salad", "soup", "beef", "fried", "homemade"],
    "it": ["alla", "della", "insalata", "formaggio", "maiale", "vitello", "patate", "zuppa", "manzo", "fatto", "contorno"],
    "fr": ["avec", "aux", "pommes", "fromage", "porc", "veau", "salade", "soupe", "bœuf", "maison", "accompagné"],
    "es": ["patatas", "ensalada", "queso", "cerdo", "ternera", "sopa", "casero", "frito", "acompañado", "salsa de"],
}

MENU_LINK = re.compile(
    r"speisekarte|speise|menü|menu|karte|carta|frühstück|fruehstueck|"
    r"tageskarte|abendkarte|mittag|lunch|dinner|food|essen",
    re.I,
)
MENU_EXCLUDE = re.compile(r"getränk|getraenk|drink|wein|wine|cocktail|bar\b|jobs?|impressum|datenschutz|#", re.I)
BOOKING = re.compile(
    r"reserv|booking|book a table|tisch|table|opentable|quandoo|thefork|resmio|"
    r"aleno|dish\.co|shop|bestell|order|click.?&.?collect",
    re.I,
)
# A real allergen legend names most of the 14 EU allergens. A single sentence
# like "ask our staff about allergens" is not enough, so we count distinct
# allergen names and require at least six.
ALLERGEN_NAMES = [
    r"gluten", r"krebstier|crustacean", r"\beier?\b|\beggs?\b", r"\bfisch\b|\bfish\b",
    r"erdn(u|ü)ss|peanut", r"\bsoja\b|\bsoy", r"\bmilch\b|\bmilk\b|lakto|lacto",
    r"schalenfr|tree nuts|\bnüsse\b|\bnuts\b", r"sellerie|celery", r"\bsenf\b|mustard",
    r"sesam", r"sulfit|sulphit|sulfite|sulphite", r"lupin", r"weichtier|mollus",
]
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def has_allergen_legend(text: str) -> bool:
    """True if the text names most EU allergens or tags dishes with letter codes like 'A, C, G'."""
    low = text.lower()
    if sum(1 for pat in ALLERGEN_NAMES if re.search(pat, low)) >= 6:
        return True
    return len(re.findall(r"\b[A-HL-PR](?:\s*,\s*[A-HL-PR]){1,}\b", text)) >= 5


def get(url: str) -> requests.Response | None:
    try:
        return requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException as exc:  # network error, DNS, TLS ...
        print(f"    ! {url}: {exc.__class__.__name__}", file=sys.stderr)
        return None


def same_site(a: str, b: str) -> bool:
    ha, hb = urlparse(a).netloc.lower(), urlparse(b).netloc.lower()
    strip = lambda h: h[4:] if h.startswith("www.") else h  # noqa: E731
    return strip(ha) == strip(hb)


def site_languages(soup: BeautifulSoup, base: str) -> list[str]:
    found: set[str] = set()
    html_lang = (soup.html.get("lang") if soup.html else "") or ""
    if html_lang[:2].lower() in LANG_NAMES:
        found.add(html_lang[:2].lower())
    for link in soup.find_all("link", hreflang=True):
        code = link["hreflang"][:2].lower()
        if code in LANG_NAMES:
            found.add(code)
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True).lower()
        title = (a.get("title") or "").lower()
        href = urljoin(base, a["href"])
        if not same_site(href, base):
            continue
        path = urlparse(href).path.lower()
        for code, names in LANG_NAMES.items():
            if text in names or any(f"switch to {n}" in title for n in names[1:]):
                found.add(code)
            if re.match(rf"^/{code}(/|$)", path):
                found.add(code)
    return sorted(found)


def menu_links(soup: BeautifulSoup, base: str) -> list[str]:
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base, a["href"]).split("#")[0]
        label = f"{a.get_text(' ', strip=True)} {a.get('title') or ''} {href}"
        if not href.startswith("http") or MENU_EXCLUDE.search(a.get_text(" ", strip=True) or ""):
            continue
        is_pdf = href.lower().endswith(".pdf")
        is_img = href.lower().endswith(IMAGE_EXT)
        if is_img and not MENU_LINK.search(href.rsplit("/", 1)[-1]):
            continue  # ordinary photos, not a menu
        if MENU_LINK.search(label) and (is_pdf or is_img or same_site(href, base)):
            if href.rstrip("/") != base.rstrip("/") and href not in out:
                out.append(href)
    return out[:6]


def read_menu(url: str) -> dict:
    r = get(url)
    if r is None:
        return {"url": url, "status": "error"}
    info: dict = {"url": url, "http": r.status_code, "bytes": len(r.content)}
    if r.status_code >= 400:
        info["status"] = "broken"
        return info
    if url.lower().endswith(IMAGE_EXT) or r.headers.get("content-type", "").startswith("image/"):
        info["kind"] = "image"
        info["status"] = "image-only"  # a photo of a menu: no text for translators or search
        return info
    ctype = r.headers.get("content-type", "").lower()
    text = ""
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        info["kind"] = "pdf"
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(r.content))
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
            info["pages"] = len(reader.pages)
        except Exception as exc:  # malformed PDF
            info["pdf_error"] = exc.__class__.__name__
        if len(text.strip()) < 40:
            info["status"] = "image-only"
    else:
        info["kind"] = "html"
        text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
    info.setdefault("status", "ok")
    info["chars"] = len(text)
    info["languages"] = menu_languages(text)
    info["allergens"] = has_allergen_legend(text)
    return info


def menu_languages(text: str) -> dict[str, int]:
    words = re.findall(r"[a-zà-ÿœ]+(?:\s(?:de))?", text.lower())
    joined = " " + " ".join(words) + " "
    scores = {}
    for code, vocab in MENU_WORDS.items():
        hits = sum(joined.count(f" {w} ") for w in vocab)
        if hits >= 5:
            scores[code] = hits
    return scores


def audit(row: dict) -> dict:
    name, url = row["venue"], (row.get("website") or "").strip()
    print(f"- {name}")
    result = {"venue": name, "website": url, "checked": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if not url:
        result["site_status"] = "none"
        return result
    r = get(url)
    if r is None:
        result["site_status"] = "unreachable"
        return result
    result["http"] = r.status_code
    result["final_url"] = r.url
    soup = BeautifulSoup(r.text, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    result["title"] = title
    body = soup.get_text(" ", strip=True)
    result["chars"] = len(body)
    if r.status_code >= 400:
        result["site_status"] = "error"
    elif re.search(r"in arbeit|under construction|coming soon|noch keinem webspace|domain.*(parked|for sale)", body, re.I):
        result["site_status"] = "placeholder"
    else:
        result["site_status"] = "live"
    result["site_languages"] = site_languages(soup, r.url)
    result["booking_signals"] = sorted({m.group(0).lower() for m in BOOKING.finditer(body)})[:8]
    result["allergens_on_site"] = has_allergen_legend(body)
    result["off_topic_signals"] = sorted({m.group(0).lower() for m in re.finditer(r"casino|glücksspiel|betting|wett(en|anbieter)", body, re.I)})
    links = menu_links(soup, r.url)
    result["menus"] = [read_menu(u) for u in links]
    time.sleep(1)  # be polite
    return result


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    with SEED.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if not only or r["venue"] == only]
    results = [audit(r) for r in rows]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if only and OUT.exists():  # merge a single-venue run into the existing file
        old = {r["venue"]: r for r in json.loads(OUT.read_text(encoding="utf-8"))}
        old.update({r["venue"]: r for r in results})
        results = list(old.values())
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {len(results)} venues to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
