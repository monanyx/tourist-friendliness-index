#!/usr/bin/env python3
"""
Score every venue in data/venues.csv against data/rubric.json and write the
files the website reads:

  docs/data/venues.json   scores, point breakdown, quick wins, coordinates
  docs/data/venues.csv    the same, flat, for people who want to download it

Usage:  python scripts/score.py
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
VENUES = ROOT / "data" / "venues.csv"
RUBRIC = ROOT / "data" / "rubric.json"
OUT_DIR = ROOT / "docs" / "data"

LANG_LABEL = {"de": "German", "en": "English", "it": "Italian", "fr": "French", "es": "Spanish", "nl": "Dutch"}


def codes(value: str) -> list[str]:
    return [c.strip() for c in (value or "").split(";") if c.strip()]


def points(v: dict) -> dict[str, int]:
    site_langs = codes(v["site_languages"])
    menu_langs = codes(v["menu_languages"])
    p = {
        "site": 10 if v["site_status"] == "live" else 0,
        "site_lang": 25 if len(site_langs) >= 3 else 15 if len(site_langs) == 2 else 0,
        "menu": 15 if v["menu_status"] in {"yes", "image", "app"} else 0,
        "menu_lang": 0,
        "allergens": 15 if v["allergens"] == "yes" else 0,
        "booking": 10 if v["booking"] == "yes" else 0,
    }
    if v["menu_status"] == "yes":
        if v["menu_translation"] == "partial":
            p["menu_lang"] = 5
        elif len(menu_langs) >= 3:
            p["menu_lang"] = 25
        elif len(menu_langs) == 2 and "en" in menu_langs:
            p["menu_lang"] = 15
    return p


def quick_wins(v: dict, p: dict[str, int]) -> list[dict]:
    """The cheapest fixes, biggest gain first."""
    wins = []
    if p["site"] == 0:
        wins.append(("site", 10, "Get a working website online, even one page with hours, menu and a map."))
    if p["site_lang"] == 0 and v["site_status"] == "live":
        gain = 15
        text = "Add an English version of the website."
        if codes(v["site_languages"]) == ["en"]:
            text = "Add a German version next to the English site."
        wins.append(("site_lang", gain, text))
    elif p["site_lang"] == 15:
        wins.append(("site_lang", 10, "Add a third website language, such as Italian or French."))
    if v["menu_status"] in {"no", "broken"}:
        msg = "Fix the broken menu link." if v["menu_status"] == "broken" else "Put the food menu online as a text PDF or web page."
        wins.append(("menu", 15, msg))
    if v["menu_status"] == "image":
        wins.append(("menu_lang", 15, "Replace the photo or scanned menu with a text version, so phones can translate it and search engines can read it."))
    elif v["menu_status"] == "app":
        wins.append(("menu_lang", 15, "Offer the menu as a plain web page or PDF next to the app, so it can be translated and indexed."))
    elif v["menu_status"] == "yes" and p["menu_lang"] < 25:
        gain = 25 - p["menu_lang"]
        wins.append(("menu_lang", gain, "Add English dish names to the menu." if p["menu_lang"] == 0 else "Add a third menu language, such as Italian or French." if p["menu_lang"] == 15 else "Translate every dish on the menu, not just the notes."))
    if p["allergens"] == 0:
        wins.append(("allergens", 15, "Print the EU allergen letters (A–R) next to each dish on the online menu."))
    if p["booking"] == 0:
        wins.append(("booking", 10, "Add a simple online reservation form."))
    wins.sort(key=lambda w: -w[1])
    return [{"criterion": c, "gain": g, "text": t} for c, g, t in wins]


def main() -> None:
    rubric = json.loads(RUBRIC.read_text(encoding="utf-8"))
    with VENUES.open(encoding="utf-8") as fh:
        venues = list(csv.DictReader(fh))

    out = []
    for v in venues:
        p = points(v)
        out.append({
            "venue": v["venue"],
            "category": v["category"],
            "address": v["address"],
            "lat": float(v["lat"]) if v["lat"] else None,
            "lon": float(v["lon"]) if v["lon"] else None,
            "website": v["website"],
            "site_status": v["site_status"],
            "site_languages": codes(v["site_languages"]),
            "menu_status": v["menu_status"],
            "menu_languages": codes(v["menu_languages"]),
            "menu_translation": v["menu_translation"],
            "allergens": v["allergens"],
            "booking": v["booking"],
            "booking_detail": v["booking_detail"],
            "note": v["note"],
            "checked": v["checked"],
            "points": p,
            "score": sum(p.values()),
            "quick_wins": quick_wins(v, p),
        })
    out.sort(key=lambda r: (-r["score"], r["venue"]))
    for i, r in enumerate(out, 1):
        r["rank"] = i

    summary = {
        "venues": len(out),
        "average": round(mean(r["score"] for r in out)),
        "checked": max(r["checked"] for r in out),
        "english_menu": sum(1 for r in out if r["points"]["menu_lang"] >= 15),
        "allergens": sum(1 for r in out if r["allergens"] == "yes"),
        "no_website": sum(1 for r in out if r["site_status"] != "live"),
        "criteria": [
            {**c, "collected": sum(r["points"][c["id"]] for r in out), "possible": c["max"] * len(out)}
            for c in rubric
        ],
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"summary": summary, "rubric": rubric, "languages": LANG_LABEL, "venues": out}
    (OUT_DIR / "venues.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    flat_fields = ["rank", "venue", "category", "address", "score"] + [f"pts_{c['id']}" for c in rubric] + [
        "site_languages", "menu_status", "menu_languages", "allergens", "booking_detail", "note", "website", "lat", "lon", "checked"]
    with (OUT_DIR / "venues.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=flat_fields)
        w.writeheader()
        for r in out:
            row = {k: r.get(k) for k in flat_fields}
            row.update({f"pts_{k}": v for k, v in r["points"].items()})
            row["site_languages"] = ";".join(r["site_languages"])
            row["menu_languages"] = ";".join(r["menu_languages"])
            w.writerow(row)

    print(f"{summary['venues']} venues, average score {summary['average']}/100")
    for r in out:
        print(f"  {r['rank']:>2}. {r['venue']:<26} {r['score']:>3}")


if __name__ == "__main__":
    main()
