"""Check the shipped snapshot, provenance, and static entry point without network access."""
from pathlib import Path
import hashlib
import json
import re
import sys

from sync_mods import ROOT, check_catalog


def validate():
    catalog = json.loads((ROOT / "data/catalog.json").read_text(encoding="utf-8"))
    check_catalog(catalog, lambda p: (ROOT / p).is_file())
    javascript = (ROOT / "data/catalog.js").read_text(encoding="utf-8")
    data_in_js = javascript.split("window.MOD_CATALOG = ", 1)[1].rstrip().removesuffix(";")
    assert json.loads(data_in_js) == catalog, "JSON and browser snapshots differ"
    provenance = json.loads((ROOT / "data/provenance.json").read_text(encoding="utf-8"))
    for mod in catalog["mods"]:
        for category in ["cards", "relics", "potions"]:
            for item in mod[category]:
                assert item["sourcePath"] in provenance[mod["id"]], "Missing source provenance"
                if category == "cards":
                    assert item["type"] != "Unknown", item["id"]
                    assert isinstance(item["cost"], int) or item["cost"] == "X", item["id"]
                    assert "{" not in item["description"], item["id"]
                    assert 'maxUpgradeLevel' in item, 'Missing upgrade limit: ' + item['id']
                for ref in item.get('tipRefs', []):
                    if ref['kind'] == 'mod':
                        assert ref['key'] + '.description' in mod['keywords'], 'Missing Mod tip: ' + ref['key']
                    if ref['kind'] == 'card':
                        assert any(card['id'] == ref['id'] for card in mod['cards']), 'Missing related card: ' + ref['id']
        for path, record in provenance[mod["id"]].items():
            if not path.lower().endswith((".png", ".jpg", ".webp")):
                continue
            image = ROOT / "assets" / mod["id"] / path
            data = image.read_bytes()
            assert len(data) == record["bytes"], "Image size mismatch: " + path
            assert hashlib.sha256(data).hexdigest() == record["sha256"], "Image hash mismatch: " + path
        print(f"{mod['id']}: {len(mod['cards'])} cards ({sum(c['inPool'] for c in mod['cards'])} in pool), {len(mod['relics'])} relics, {len(mod['potions'])} potions; all image hashes verified.")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    for path in re.findall(r'(?:src|href)="([^"#]+)"', html):
        if not re.match(r"(?:https?:|data:)", path):
            assert (ROOT / path).is_file(), "Missing HTML asset: " + path
    ui = json.loads((ROOT / "data/game-ui.json").read_text(encoding="utf-8"))
    runtime = (ROOT / "data/game-ui.js").read_text(encoding="utf-8").split("window.GAME_UI = ", 1)[1].rstrip().removesuffix(";")
    assert json.loads(runtime) == {key: ui[key] for key in ['localization', 'modGameplay', 'artifactUi', 'mods', 'cardLibrary']}, "Native UI runtime differs from its source manifest"
    for mod in catalog['mods']:
        assert mod['id'] in ui['mods'], 'Missing per-Mod rendering assets'
        for category in ['cards', 'relics', 'potions']:
            for item in mod[category]:
                for ref in item.get('tipRefs', []):
                    if ref['kind'] in ['power', 'potion', 'static']:
                        dictionary = {'power': 'powers', 'potion': 'potions', 'static': 'static_hover_tips'}[ref['kind']]
                        key = ref.get('key', ref.get('id')) + '.description'
                        assert key in ui['localization'].get(dictionary, {}) or key in mod.get('powers', {}) or any(p['id'] == ref.get('id') for p in mod['potions']), 'Unresolved hover tip: ' + str(ref)
    for path, record in ui["outputs"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == record["sha256"], "Native asset hash mismatch: " + path
    web = json.loads((ROOT / 'data/web-assets.json').read_text(encoding='utf-8'))
    web_runtime = (ROOT / 'data/web-assets.js').read_text(encoding='utf-8').split('window.WEB_ASSETS = ', 1)[1].rstrip().removesuffix(';')
    assert json.loads(web_runtime) == {path: record['path'] for path, record in web.items()}, 'Browser asset map differs'
    for path, record in web.items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == record['sourceSha256'], 'Stale browser image: ' + path
        assert hashlib.sha256((ROOT / record['path']).read_bytes()).hexdigest() == record['sha256'], 'Browser image mismatch: ' + path
    for stylesheet in ['styles.css', 'collections.css']:
        for path in re.findall(r"url\(['\"]?([^)'\"]+)", (ROOT / stylesheet).read_text(encoding="utf-8")):
            assert (ROOT / path).is_file(), "Missing CSS asset: " + path
    for script in ["app.js", "card-renderer.js", "styles.css", "collections.css"]:
        text = (ROOT / script).read_text(encoding="utf-8")
        assert "fetch(" not in text and "WebSocket(" not in text, "Runtime network dependency introduced"
    print(f"Catalog, {len(ui['outputs'])} native UI assets, runtime data and static references validated.")


if __name__ == "__main__":
    try:
        validate()
    except (AssertionError, KeyError, ValueError, OSError) as error:
        print("Validation failed: " + str(error), file=sys.stderr)
        sys.exit(1)
