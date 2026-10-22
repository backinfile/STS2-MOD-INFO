"""Prepare a static hosting directory containing only browser-facing files."""
from pathlib import Path
import shutil

from sync_mods import ROOT
from validate_catalog import validate

validate()
out = ROOT / "dist"
out.mkdir(exist_ok=True)
for name in ["index.html", "styles.css", "collections.css", "app.js", "card-renderer.js"]:
    shutil.copyfile(ROOT / name, out / name)
(out / "data").mkdir(exist_ok=True)
for name in ["catalog.js", "catalog.json", "game-ui.js", "web-assets.js"]:
    shutil.copyfile(ROOT / "data" / name, out / "data" / name)
shutil.copytree(ROOT / "assets", out / "assets", dirs_exist_ok=True)
print("Static site prepared in dist/")
