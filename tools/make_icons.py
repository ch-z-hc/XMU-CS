#!/usr/bin/env python3
"""Export the app's SVG artwork. Install CairoSVG to regenerate the PNGs."""

from pathlib import Path
from xml.etree import ElementTree

import cairosvg


ASSETS = Path(__file__).resolve().parents[1] / "assets"


def main():
    artwork = ElementTree.parse(ASSETS / "icon-source.svg").getroot()
    for name, size in (
        ("favicon.png", 64),
        ("apple-touch-icon.png", 180),
        ("icon-192.png", 192),
        ("icon-512.png", 512),
    ):
        # Keep the entire mark inside the home-screen mask safe zone.
        favicon = name == "favicon.png"
        artwork.set("viewBox", "0 0 96 96" if favicon else "-20 -20 136 136")
        cairosvg.svg2png(
            bytestring=ElementTree.tostring(artwork),
            write_to=str(ASSETS / name),
            output_width=size,
            output_height=size,
            background_color=None if favicon else "#f5f7ff",
        )


if __name__ == "__main__":
    main()
