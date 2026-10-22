"""Compile lossless browser images; retain every original snapshot and its provenance."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import json
from pathlib import Path
from PIL import Image

from sync_mods import ROOT


def optimize():
    manifest_path = ROOT / 'data/web-assets.json'
    old = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    images = [p for p in (ROOT / 'assets').rglob('*') if p.suffix.lower() in ['.png', '.jpg'] and 'web' not in p.relative_to(ROOT / 'assets').parts]

    def compile_image(path):
        source = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        target = 'assets/web/' + path.relative_to(ROOT / 'assets').as_posix() + '.webp'
        output = ROOT / target
        previous = old.get(source, {})
        if previous.get('sourceSha256') == digest and output.exists() and hashlib.sha256(output.read_bytes()).hexdigest() == previous.get('sha256'):
            return source, previous
        image = Image.open(BytesIO(data)).convert('RGBA')
        encoded = BytesIO()
        image.save(encoded, format='WEBP', lossless=True, exact=True, method=6)
        result = encoded.getvalue()
        # The compilation must preserve every RGBA pixel, including transparent pixels.
        assert Image.open(BytesIO(result)).convert('RGBA').tobytes() == image.tobytes(), source
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(result)
        return source, {'path': target, 'sourceSha256': digest, 'sha256': hashlib.sha256(result).hexdigest(), 'sourceBytes': len(data), 'bytes': len(result)}

    with ThreadPoolExecutor(max_workers=4) as executor:
        records = dict(executor.map(compile_image, images))
    manifest_path.write_text(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    (ROOT / 'data/web-assets.js').write_text('window.WEB_ASSETS = ' + json.dumps({key: value['path'] for key, value in records.items()}, ensure_ascii=False) + ';\n', encoding='utf-8')
    before, after = sum(r['sourceBytes'] for r in records.values()), sum(r['bytes'] for r in records.values())
    print(f'{len(records)} lossless browser images: {before:,} -> {after:,} bytes ({100 * (1 - after / before):.1f}% saved).')


if __name__ == '__main__':
    optimize()
