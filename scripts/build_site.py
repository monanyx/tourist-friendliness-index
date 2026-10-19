#!/usr/bin/env python3
"""
Build docs/index.html (the GitHub Pages site) from docs/index.src.html.

The source file is written as a page body. This script wraps it in a full
HTML document and inlines Leaflet's stylesheet, so the site has no build
tooling and no external CSS beyond Google Fonts.

Usage:  python scripts/build_site.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "index.src.html"
OUT = ROOT / "docs" / "index.html"
LEAFLET_CSS = ROOT / "docs" / "vendor" / "leaflet-1.9.4.css"


def main() -> None:
    src = SRC.read_text(encoding="utf-8").replace("/*LEAFLET_CSS*/", LEAFLET_CSS.read_text(encoding="utf-8"))
    cut = src.index('<div class="wrap">')
    head, body = src[:cut], src[cut:]
    page = (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
        "<style>:root{color-scheme:light dark}body{margin:0}[hidden]{display:none!important}img{max-width:100%}</style>\n"
        f"{head}</head>\n<body>\n{body}</body>\n</html>\n"
    )
    OUT.write_text(page, encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} ({len(page):,} bytes)")


if __name__ == "__main__":
    main()
