#!/usr/bin/env python3
"""
Add map coordinates to data/venues.csv using OpenStreetMap data via the
Photon geocoder (https://photon.komoot.io). Only rows without lat/lon are
looked up, so hand corrections are never overwritten.

Usage:  python scripts/geocode.py
"""
from __future__ import annotations

import csv
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "venues.csv"
# Innsbruck city centre, used to bias results and reject far-away matches
CENTER = (47.2683, 11.3933)
HEADERS = {"User-Agent": "TouristFriendlinessIndex/1.0 (research project)"}


def lookup(query: str) -> tuple[float, float] | None:
    r = requests.get(
        "https://photon.komoot.io/api/",
        params={"q": query, "lat": CENTER[0], "lon": CENTER[1], "limit": 1},
        headers=HEADERS,
        timeout=20,
    )
    r.raise_for_status()
    feats = r.json().get("features") or []
    if not feats:
        return None
    lon, lat = feats[0]["geometry"]["coordinates"]
    # anything more than ~3 km from the centre is a wrong match
    if abs(lat - CENTER[0]) > 0.03 or abs(lon - CENTER[1]) > 0.04:
        return None
    return round(lat, 6), round(lon, 6)


def main() -> None:
    with CSV.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames
        rows = list(reader)
    for row in rows:
        if row.get("lat") and row.get("lon"):
            continue
        hit = None
        for q in (f"{row['venue']} {row['address']} Innsbruck", f"{row['address']}, 6020 Innsbruck"):
            hit = lookup(q)
            if hit:
                break
            time.sleep(1)
        if hit:
            row["lat"], row["lon"] = hit
            print(f"  {row['venue']}: {hit}")
        else:
            print(f"  {row['venue']}: not found, add lat/lon by hand")
        time.sleep(1)
    with CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
