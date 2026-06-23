"""Generate the PWA / favicon assets from the Arsenal crest.

Pulls the same ESPN crest the Europe crest-wall uses (config.CLUB_CRESTS),
trims the transparent border, then:
  - docs/icon-192.png, docs/icon-512.png : crest centred on the app's dark
    background with maskable-safe padding (home-screen / install icon).
  - docs/favicon.ico (16/32/48) + docs/favicon-32.png : crest on transparent
    for the browser tab.

Re-run after the crest source changes. Needs Pillow + requests (both in venv).
"""

import io

import requests
from PIL import Image

import config

CREST_URL = config.CLUB_CRESTS["Arsenal"]
BG = (10, 14, 22, 255)          # --bg #0a0e16, matches manifest theme/background
SAFE = 0.64                     # crest occupies ~64% of the icon (maskable safe zone)


def _fetch_crest():
    r = requests.get(CREST_URL, headers={"User-Agent": config.USER_AGENT}, timeout=20)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content)).convert("RGBA")
    bbox = img.getbbox()        # trim transparent margin so our padding is exact
    return img.crop(bbox) if bbox else img


def _square_on(crest, size, bg, scale):
    canvas = Image.new("RGBA", (size, size), bg)
    target = int(size * scale)
    w, h = crest.size
    ratio = min(target / w, target / h)
    new = crest.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), Image.LANCZOS)
    pos = ((size - new.width) // 2, (size - new.height) // 2)
    canvas.alpha_composite(new, pos)
    return canvas


def main():
    crest = _fetch_crest()

    # home-screen / install icons: crest on the dark app background.
    # NOTE: filenames carry a version suffix on purpose. iOS/Safari and the
    # service worker cache home-screen icons hard; re-adding reuses the old URL.
    # Bumping the filename is the only reliable cache-bust. Bump ICON_VER when
    # the crest changes and update the references in index.html + manifest + sw.js.
    _square_on(crest, 512, BG, SAFE).save("docs/icon-512-v2.png")
    _square_on(crest, 192, BG, SAFE).save("docs/icon-192-v2.png")

    # favicon: crest on transparent, a touch more bleed so it reads at tab size
    fav = _square_on(crest, 64, (0, 0, 0, 0), 0.92)
    fav.save("docs/favicon-32-v2.png")
    fav.save("docs/favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

    print("Wrote docs/icon-512-v2.png, icon-192-v2.png, favicon.ico, favicon-32-v2.png")


if __name__ == "__main__":
    main()
