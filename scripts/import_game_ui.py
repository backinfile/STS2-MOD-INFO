"""Bake native Godot UI atlas regions and YIQ materials into standalone web assets."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile
import urllib.parse

from sync_mods import ROOT, CACHE, api, fetch, numbers, render_text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.sync-staging/python'))
from PIL import Image
from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.transformPen import TransformPen

GAME_REPO = 'Hexpion/Slay-the-spire-2'
GAME_COMMIT = '64ed626b7ec9692bc54536b0123fc3cb580c28da'
GAME_ROOT = 'Slay the Spire 2/'
VERSION = 10
ASSETS = ROOT / 'assets/game-ui'
SOURCES = ROOT / 'data/game-ui.json'


def multiply(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def inverse(a):
    det = (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
           - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
           + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    return [[(((-1) ** (i + j)) * (a[(j + 1) % 3][(i + 1) % 3] * a[(j + 2) % 3][(i + 2) % 3]
             - a[(j + 1) % 3][(i + 2) % 3] * a[(j + 2) % 3][(i + 1) % 3]) / det)
             * ((-1) ** (i + j)) for j in range(3)] for i in range(3)]


def material_matrix(h, s, v):
    # The shader's col.rgb *= hue_shift uses a row-vector multiplication.
    yiq = [[.2989, .5870, .1140], [.5959, -.2774, -.3216], [.2115, -.5229, .3114]]
    angle = (1 - h) * 6.283185
    c, sn = math.cos(angle), math.sin(angle)
    rotation = [[v, 0, 0], [0, s * v * c, -s * v * sn], [0, s * v * sn, s * v * c]]
    return multiply(inverse(yiq), multiply(rotation, yiq))


def tint(image, params):
    matrix = material_matrix(*params)
    rgba = image.convert('RGBA')
    rgb = rgba.convert('RGB').convert('RGB', tuple(number for row in matrix for number in (*row, 0)))
    rgb.putalpha(rgba.getchannel('A'))
    return rgb


def modulate(image, color):
    return Image.merge('RGBA', tuple(channel.point(lambda value, factor=factor: round(value * factor)) for channel, factor in zip(image.convert('RGBA').split(), color)))


def apply_font_variation(font, scale, baseline_offset):
    """Bake Godot's outline transform and baseline shift; retain glyph advances."""
    top = font['CFF '].cff.topDictIndex[0]
    glyph_set = font.getGlyphSet()
    height = font['hhea'].ascent - font['hhea'].descent
    transform = (scale, 0, 0, scale, 0, -baseline_offset * height)
    changed = {}
    for name in font.getGlyphOrder():
        original = top.CharStrings[name]
        advance, bearing = font['hmtx'].metrics[name]
        # Type 2 charstrings encode a delta from nominalWidthX, or omit the
        # operand for defaultWidthX. CID font dictionaries use different values.
        width = None if advance == original.private.defaultWidthX else advance - original.private.nominalWidthX
        pen = T2CharStringPen(width, glyph_set, roundTolerance=0)
        original.draw(TransformPen(pen, transform))
        changed[name] = pen.getCharString(private=original.private, globalSubrs=original.globalSubrs)
        font['hmtx'].metrics[name] = (advance, round(bearing * scale))
    for name, charstring in changed.items():
        top.CharStrings[name] = charstring


class NativeSource:
    def __init__(self, repo, commit, prefix='', cached_tree=None):
        self.repo, self.commit, self.prefix = repo, commit, prefix
        cached = ROOT / '.sync-staging' / (cached_tree or 'unused.json')
        saved = json.loads(cached.read_text(encoding='utf-8-sig')) if cached.exists() else {}
        if saved.get('commit') == commit:
            tree = saved['tree']
        else:
            response = api(f'/repos/{repo}/git/trees/{commit}?recursive=1')
            if response.get('truncated'):
                raise ValueError('Incomplete source tree')
            tree = response['tree']
        self.tree = {item['path']: item for item in tree if item['type'] == 'blob'}
        self.records = {}
        self.memory = {}

    def read(self, path):
        full_path = self.prefix + path
        item = self.tree[full_path]
        if path in self.memory:
            return self.memory[path]
        cache = CACHE / item['sha']
        data = cache.read_bytes() if cache.exists() else fetch(f'https://raw.githubusercontent.com/{self.repo}/{self.commit}/{urllib.parse.quote(full_path)}')
        actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if actual != item['sha']:
            raise ValueError('Native source blob mismatch: ' + full_path)
        if not cache.exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(data)
        self.records[path] = {'path': full_path, 'gitBlob': actual, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        self.memory[path] = data
        return data

    def text(self, path):
        return self.read(path).decode('utf-8-sig')

    def texture(self, path):
        if not path.endswith('.tres'):
            return Image.open(BytesIO(self.read(path))).convert('RGBA')
        source = self.text(path)
        image_path = re.search(r'path="res://([^"]+)"', source)[1]
        image = self.texture(image_path)
        region = re.search(r'region\s*=\s*Rect2\(([^)]+)\)', source)
        if region:
            x, y, w, h = [round(float(n.strip())) for n in region[1].split(',')]
            image = image.crop((x, y, x + w, y + h))
        margin = re.search(r'margin\s*=\s*Rect2\(([^)]+)\)', source)
        if margin:
            x, y, w, h = [float(n.strip()) for n in margin[1].split(',')]
            canvas = Image.new('RGBA', (round(image.width + w), round(image.height + h)))
            canvas.paste(image, (round(x), round(y)))
            image = canvas
        return image

    def parameters(self, path):
        source = self.text(path)
        return tuple(float(re.search(r'shader_parameter/' + name + r'\s*=\s*([\d.]+)', source)[1]) for name in ['h', 's', 'v'])


def font_characters():
    # Both Mod content and necessary web controls are included. Rebuild after upstream changes.
    text = ''.join((ROOT / path).read_text(encoding='utf-8') for path in ['data/catalog.json', 'app.js', 'card-renderer.js', 'index.html', 'styles.css', 'collections.css'])
    return set(text) | set(chr(i) for i in range(32, 127))


def card_library_metrics(game):
    card = game.text('src/Core/Nodes/Cards/NCard.cs')
    holder = game.text('src/Core/Nodes/Cards/Holders/NCardHolder.cs')
    grid = game.text('src/Core/Nodes/Cards/NCardGrid.cs')
    project = game.text('project.godot')
    game.text('src/Core/Nodes/Screens/CardLibrary/NCardLibraryGrid.cs')
    game.text('src/Core/Nodes/Cards/Holders/NGridCardHolder.cs')
    game.text('scenes/cards/holders/grid_card_holder.tscn')
    size = re.search(r'defaultSize\s*=\s*new Vector2\(([\d.]+)f,\s*([\d.]+)f\)', card)
    scale = re.search(r'smallScale\s*=\s*Vector2.One\s*\*\s*([\d.]+)f', holder)
    padding = re.search(r'CardPadding\s*=>\s*([\d.]+)f', grid)
    width = re.search(r'window/size/viewport_width=(\d+)', project)
    height = re.search(r'window/size/viewport_height=(\d+)', project)
    if not all([size, scale, padding, width, height]) or 'NCard.defaultSize * NCardHolder.smallScale' not in grid:
        raise ValueError('Unsupported native card library sizing rules')
    small = float(scale[1])
    return {'baseWidth': float(size[1]), 'baseHeight': float(size[2]), 'smallScale': small,
            'cardWidth': float(size[1]) * small, 'cardHeight': float(size[2]) * small,
            'gap': float(padding[1]), 'hoverScale': 1 / small,
            'designWidth': int(width[1]), 'designHeight': int(height[1])}


def build(force=False):
    catalog = json.loads((ROOT / 'data/catalog.json').read_text(encoding='utf-8'))
    karen = catalog['mods'][0]
    signature = {'version': VERSION, 'builderHash': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'gameCommit': GAME_COMMIT, 'mods': {m['id']: {'commit': m['commit'], 'adapterHash': m.get('adapterHash'), 'rendering': m.get('rendering', {})} for m in catalog['mods']}, 'characters': ''.join(sorted(font_characters()))}
    old = json.loads(SOURCES.read_text(encoding='utf-8')) if SOURCES.exists() else {}
    if not force and (ROOT / 'data/game-ui.js').exists() and old.get('signature') == signature and all((ROOT / name).is_file() and hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == record['sha256'] for name, record in old.get('outputs', {}).items()):
        print('Native UI assets unchanged; no downloads required.')
        return
    game = NativeSource(GAME_REPO, GAME_COMMIT, GAME_ROOT, 'game-tree.json')
    library_metrics = card_library_metrics(game)
    mod = NativeSource(karen['repository'], karen['commit'], cached_tree=karen['id'] + '-tree.json')
    # Fetch source fonts while the atlas and material sources load.
    font_paths = ['fonts/zhs/NotoSansMonoCJKsc-Regular.otf', 'fonts/zhs/SourceHanSerifSC-Bold.otf', 'fonts/zhs/SourceHanSerifSC-Medium.otf']
    warm_paths = font_paths + ['images/atlases/ui_atlas_0.png', 'images/atlases/ui_atlas_1.png']
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(game.read, warm_paths))
    parent = ROOT / '.sync-staging'
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='native-ui-', dir=parent) as directory:
        stage = Path(directory)
        assert stage.resolve().is_relative_to(parent.resolve())
        outputs = {}

        def save(name, image):
            target = stage / name
            image.save(target, optimize=True)
            outputs['assets/game-ui/' + name] = {'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'size': list(image.size)}

        rendering = karen.get('rendering', {})
        frame_params = mod.parameters(rendering['frameMaterialSource']) if rendering.get('frameMaterialSource') else (1, 1, 1)
        banner_params = {key: game.parameters(f'materials/cards/banners/card_banner_{key}_mat.tres') for key in ['common', 'uncommon', 'rare', 'curse', 'status', 'event', 'ancient']}
        for card_type in ['attack', 'skill', 'power']:
            frame = game.texture(f'images/atlases/ui_atlas.sprites/card/card_frame_{card_type}_s.tres')
            save('frame-' + card_type + '.png', tint(frame, frame_params))
            for pool in ['colorless', 'curse']:
                save(f'frame-{pool}-{card_type}.png', tint(frame, game.parameters(f'materials/cards/frames/card_frame_{pool}_mat.tres')))
            border = game.texture(f'images/atlases/ui_atlas.sprites/card/card_portrait_border_{card_type}_s.tres')
            for rarity, parameters in banner_params.items():
                save(f'portrait-{card_type}-{rarity}.png', tint(border, parameters))
        banner = game.texture('images/atlases/ui_atlas.sprites/card/card_banner.tres')
        plaque = game.texture('images/ui/cards/card_portrait_border_plaque2.png')
        for rarity, parameters in banner_params.items():
            save('banner-' + rarity + '.png', tint(banner, parameters))
            save('plaque-' + rarity + '.png', tint(plaque, parameters))
        for name in ['ancient_card_border', 'ancient_card_text_bg_attack', 'ancient_card_text_bg_skill', 'ancient_card_text_bg_power', 'ancient_portrait_mask_large', 'card_highlight_ancient']:
            save(name.replace('_', '-') + '.png', game.texture(f'images/atlases/compressed.sprites/card_template/{name}.tres'))
        save('ancient-banner.png', game.texture('images/atlases/ui_atlas.sprites/card/ancient_banner.tres'))
        for index in range(10):
            save(f'ancient-flame-{index}.png', game.texture(f'images/atlases/compressed.sprites/card_template/ancient_flame/ancient_card_flame_{index}.tres'))
        save('energy-karen.png', mod.texture(rendering['energySource']) if rendering.get('energySource') else game.texture('images/atlases/ui_atlas.sprites/card/energy_colorless.tres'))
        save('energy-colorless.png', game.texture('images/atlases/ui_atlas.sprites/card/energy_colorless.tres'))
        save('pool-other.png', game.texture('images/packed/card_library/pool_filter_other.png'))
        save('pool-ancient.png', game.texture('images/ui/run_history/neow.png'))
        for name in ['Token', 'Curse', 'Status', 'Colorless']:
            game.text(f'src/Core/Models/CardPools/{name}CardPool.cs')
        game.text('src/Core/Nodes/Screens/CardLibrary/NCardLibrary.cs')
        save('energy-inline.png', mod.texture(rendering['inlineEnergySource']) if rendering.get('inlineEnergySource') else game.texture('images/atlases/ui_atlas.sprites/card/energy_colorless.tres'))
        save('health-icon.png', game.texture('images/atlases/ui_atlas.sprites/top_bar/top_bar_heart.tres'))
        save('hover-tip.png', game.texture('images/ui/hover_tip.png'))
        save('top-bar.png', game.texture('images/atlases/ui_atlas.sprites/top_bar/top_bar.tres'))
        # Native header, selection states, and library filters, without redrawing their shapes.
        for name in ['type_sort_attack', 'type_sort_skill', 'type_sort_power', 'type_sort_other', 'type_sort_outline2', 'cost_tickbox', 'cost_tickbox_outline']:
            save(name.replace('_', '-') + '.png', game.texture('images/packed/card_library/' + name + '.png'))
        for name in ['submenu_card_library', 'submenu_relic_collection', 'submenu_potion_lab', 'submenu_unknown', 'submenu_standard']:
            save(name.replace('_', '-') + '.png', game.texture('images/ui/main_menu/' + name + '.png'))
        for name in ['card_icon', 'gold_icon', 'potion_icon']:
            save(name.replace('_', '-') + '.png', game.texture('images/packed/sprite_fonts/' + name + '.png'))
        # Relic inspect screen and the exact collection outline colors.
        reward_panel = game.texture('images/ui/reward_screen/reward_panel.png')
        save('inspect-panel.png', reward_panel)
        save('inspect-frame-bg.png', modulate(reward_panel, (.0812, .28, .246867, .501961)))
        inspect_frame = game.texture('images/packed/inspect_relic_screen/relic_inspect_frame.png')
        inspect_materials = {'starter': (.95, .25, .9), 'common': (.95, .25, .9), 'uncommon': (.426, .8, 1.1), 'rare': (1, .8, 1.15), 'shop': (.525, 2.5, .85), 'event': (.23, .75, .9), 'ancient': (.875, 3, .9)}
        for rarity, parameters in inspect_materials.items():
            save('inspect-frame-' + rarity + '.png', tint(inspect_frame, parameters))
        for direction in ['left', 'right']:
            save('inspect-arrow-' + direction + '.png', tint(game.texture('images/packed/common_ui/settings_tiny_' + direction + '_arrow.png'), (1, 1, .9)))
        artifact_ui = {'relics': {}, 'potions': {}}
        game.text('src/Core/Helpers/StsColors.cs')
        for category, color in rendering.get('outlineColors', {}).items():
            for item in karen[category]:
                if item.get('outline'):
                    name = item['id'].lower() + '-collection-outline.png'
                    save(name, modulate(mod.texture(item['outline'].removeprefix('assets/' + karen['id'] + '/')), color))
                    artifact_ui[category][item['id']] = {'outline': 'assets/game-ui/' + name}
        # Match the native library's actual control text and tooltip rules.
        localization = {}
        for name in ['card_library', 'static_hover_tips', 'card_keywords', 'gameplay_ui', 'main_menu', 'powers', 'potions', 'relic_collection', 'potion_lab', 'inspect_relic_screen']:
            path = f'localization/zhs/{name}.json'
            if GAME_ROOT + path in game.tree:
                localization[name] = json.loads(game.text(path))
        game.text('scenes/cards/card.tscn')
        game.text('scenes/ui/hover_tip.tscn')
        game.text('scenes/screens/card_library/card_library.tscn')
        for folder, names in [('relic_collection', ['relic_collection', 'relic_collection_category', 'relic_collection_subcategory', 'relic_collection_entry']), ('potion_lab', ['potion_lab', 'potion_category', 'lab_potion_holder']), ('inspect_relic_screen', ['inspect_relic_screen'])]:
            for name in names:
                game.text(f'scenes/screens/{folder}/{name}.tscn')
        for path in ['scenes/relics/relic.tscn', 'scenes/potions/potion.tscn', 'src/Core/Nodes/Screens/RelicCollection/NRelicCollectionEntry.cs', 'src/Core/Nodes/Screens/PotionLab/NLabPotionHolder.cs', 'src/Core/Nodes/Screens/InspectScreens/NInspectRelicScreen.cs']:
            game.text(path)
        game.text('shaders/hsv.gdshader')
        # Each Mod owns its frames, energy and outlines. No global Karen lookup.
        mod_ui, mod_sources = {}, {}
        for entry in catalog['mods']:
            native = NativeSource(entry['repository'], entry['commit'], cached_tree=entry['id'] + '-tree.json')
            config = entry.get('rendering', {})
            prefix = entry['id'] + '-'
            params = native.parameters(config['frameMaterialSource']) if config.get('frameMaterialSource') else game.parameters('materials/cards/frames/card_frame_colorless_mat.tres')
            for kind in ['attack', 'skill', 'power']:
                save(prefix + 'frame-' + kind + '.png', tint(game.texture(f'images/atlases/ui_atlas.sprites/card/card_frame_{kind}_s.tres'), params))
            for key, output in [('energySource', 'energy'), ('inlineEnergySource', 'inline-energy')]:
                image = native.texture(config[key]) if config.get(key) else game.texture('images/atlases/ui_atlas.sprites/card/energy_colorless.tres')
                save(prefix + output + '.png', image)
            outlines = {'relics': {}, 'potions': {}}
            for category in outlines:
                for item in entry[category]:
                    if item.get('outline'):
                        name = prefix + item['id'].lower() + '-outline.png'
                        save(name, modulate(native.texture(item['outline'].removeprefix('assets/' + entry['id'] + '/')), config.get('outlineColors', {}).get(category, [1, 1, 1, .66])))
                        outlines[category][item['id']] = {'outline': 'assets/game-ui/' + name}
            gameplay = json.loads(native.text(config['gameplayPath'])) if config.get('gameplayPath') else {}
            mod_ui[entry['id']] = {'id': entry['id'], 'framePrefix': 'assets/game-ui/' + prefix + 'frame-', 'energy': 'assets/game-ui/' + prefix + 'energy.png', 'inlineEnergy': 'assets/game-ui/' + prefix + 'inline-energy.png', 'gameplay': gameplay, 'shineLabel': gameplay.get(config.get('shineLabelKey'), ''), 'shineSuffix': gameplay.get(config.get('shineSuffixKey'), ''), 'artifactUi': outlines}
            mod_sources[entry['id']] = native.records
        # Keep only dictionary entries actually referenced by the static reader.
        references = [ref for entry in catalog['mods'] for category in ['cards', 'relics', 'potions'] for item in entry[category] for ref in item.get('tipRefs', [])]
        for dictionary, kind in [('powers', 'power'), ('potions', 'potion')]:
            keys = {ref.get('key', ref.get('id')) for ref in references if ref['kind'] == kind}
            localization[dictionary] = {key: value for key, value in localization.get(dictionary, {}).items() if key.split('.')[0] in keys}
        for ref in references:
            if ref['kind'] == 'potion' and ref['id'] + '.description' in localization['potions']:
                name = ''.join(word.title() for word in ref['id'].split('_'))
                base, _ = numbers(game.text('src/Core/Models/Potions/' + name + '.cs'))
                localization['potions'][ref['id'] + '.description'] = render_text(localization['potions'][ref['id'] + '.description'], base, False)[0]
        game.text('src/Core/Localization/Fonts/FontPathSets/ZhsFontPathSet.cs')
        game.text('src/Core/Localization/Fonts/FontControlUtils.cs')
        game.text('addons/mega_text/MegaLabel.cs')
        game.text('addons/mega_text/MegaRichTextLabel.cs')
        font_variations = {}
        font_themes = ['noto_sans_mono_cjksc_regular_shared', 'source_han_serif_sc_bold_shared', 'source_han_serif_sc_medium_shared']
        for source_path, theme, name in zip(font_paths, font_themes, ['game-regular.woff2', 'game-bold.woff2', 'game-medium.woff2']):
            theme_source = game.text('themes/fonts/zhs/' + theme + '.tres')
            scale = float(re.search(r'variation_transform = Transform2D\(([^,]+)', theme_source)[1])
            baseline = float(re.search(r'baseline_offset = ([-\d.]+)', theme_source)[1])
            font = TTFont(BytesIO(game.read(source_path)), recalcTimestamp=False)
            options = subset.Options()
            options.flavor = 'woff2'
            options.recalc_timestamp = False
            sub = subset.Subsetter(options=options)
            if name == 'game-regular.woff2':
                characters = signature['characters'] + json.dumps(localization, ensure_ascii=False)
            else:
                tag = 'b' if name == 'game-bold.woff2' else 'i'
                characters = ''.join(re.findall(r'\[' + tag + r'\]([\s\S]*?)\[/' + tag + r'\]', json.dumps(catalog, ensure_ascii=False) + json.dumps(localization, ensure_ascii=False))) + ''.join(chr(i) for i in range(32, 127))
            sub.populate(text=characters)
            sub.subset(font)
            apply_font_variation(font, scale, baseline)
            font_variations[name] = {'outlineScale': scale, 'baselineOffset': baseline, 'advanceScale': 1}
            font.flavor = 'woff2'
            target = stage / name
            font.save(target)
            outputs['assets/game-ui/' + name] = {'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'bytes': target.stat().st_size}
        for source_path, name in [('fonts/kreon_regular.ttf', 'kreon-regular.ttf'), ('fonts/kreon_bold.ttf', 'kreon-bold.ttf')]:
            data = game.read(source_path)
            (stage / name).write_bytes(data)
            outputs['assets/game-ui/' + name] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        manifest = {'signature': signature, 'gameRepository': GAME_REPO, 'gameCommit': GAME_COMMIT, 'modRepository': karen['repository'], 'modCommit': karen['commit'],
                    'frameMaterial': {'h': frame_params[0], 's': frame_params[1], 'v': frame_params[2]}, 'bannerMaterials': banner_params, 'fontVariations': font_variations,
                    'sources': {'game': game.records, 'mod': mod.records}, 'outputs': outputs, 'localization': localization, 'artifactUi': artifact_ui, 'inspectMaterials': inspect_materials,
                    'mods': mod_ui, 'modSources': mod_sources, 'modGameplay': mod_ui[karen['id']]['gameplay'], 'cardLibrary': library_metrics}
        ASSETS.mkdir(parents=True, exist_ok=True)
        for path in stage.iterdir():
            shutil.copyfile(path, ASSETS / path.name)
        SOURCES.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        runtime = {'localization': localization, 'modGameplay': manifest['modGameplay'], 'artifactUi': artifact_ui, 'mods': mod_ui, 'cardLibrary': library_metrics}
        (ROOT / 'data/game-ui.js').write_text('window.GAME_UI = ' + json.dumps(runtime, ensure_ascii=False) + ';\n', encoding='utf-8')
        print(f'Native UI: {len(outputs)} textures/fonts, {len(game.records)} game source files, {len(mod.records)} Mod source files verified.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--force', action='store_true')
    build(parser.parse_args().force)
