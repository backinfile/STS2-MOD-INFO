"""Import fixed-commit public Mod snapshots; stdlib only, no game installation needed."""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(os.environ.get('STS2_MOD_BUILD_ROOT', Path(__file__).resolve().parents[1])).resolve()
CACHE = Path(os.environ.get('STS2_SOURCE_CACHE', ROOT / '.sync-staging/cache')).resolve()
API = "https://api.github.com"
HEADERS = {"User-Agent": "STS2-Mod-Info-static-importer", "Accept": "application/vnd.github+json"}
TOKEN = os.environ.get("GITHUB_TOKEN")
ADAPTER_VERSION = 2


def member_body(source: str, name: str) -> str:
    """Read a property body without leaking into the following model member."""
    match = re.search(r'\b' + re.escape(name) + r'\s*(=>|\{)', source)
    if not match:
        return ''
    if match[1] == '=>':
        return source[match.end():source.find(';', match.end())]
    cursor, depth = match.end(), 1
    while cursor < len(source) and depth:
        depth += (source[cursor] == '{') - (source[cursor] == '}')
        cursor += 1
    return source[match.end():cursor - 1]


def model_id(name):
    return {'KAREN_WE_KONW_TOKEN': 'KAREN_WE_KOWN_TOKEN'}.get(slug(name).upper(), slug(name).upper())


def tip_references(source, local):
    body = member_body(source, 'ExtraHoverTips')
    refs = [{'kind': 'mod', 'key': key} for key in re.findall(r'MechanicTip\("([\w]+)"\)', body)]
    refs += [{'kind': 'power', 'key': model_id(name)} for name in re.findall(r'FromPower<(\w+)>', body)]
    refs += [{'kind': 'potion', 'id': model_id(name)} for name in re.findall(r'FromPotion<(\w+)>', body)]
    for name, arg in re.findall(r'FromCard<(\w+)>\(([^)]*)\)', body):
        refs.append({'kind': 'card', 'id': model_id(name), 'upgraded': 'match' if arg == 'IsUpgraded' else arg == 'true'})
    refs += [{'kind': 'card', 'id': model_id(name), 'upgraded': False} for name in re.findall(r'new CardHoverTip\(ModelDb.Card<(\w+)>', body)]
    if 'ForEnergy(' in body:
        refs.append({'kind': 'static', 'key': 'ENERGY'})
    # Inline localized tips and the shared Tips aliases retain their exact source text.
    aliases = {'KarenFight': 'KAREN_SHINE_REPRODUCE', 'StageReproduce': 'KAREN_STAGE_REPRODUCE'}
    keys = re.findall(r'new LocString\("cards",\s*"([^"\n]+\.title)"\)', body)
    keys += [key + '.tip.title' for alias, key in aliases.items() if 'Tips.' + alias + 'TipTitle' in body]
    for key in keys:
        description = local.get(key.removesuffix('.title') + '.description', local.get(key.removesuffix('.title'), ''))
        description, _ = render_text(description, {'AdditionalPlays': 0}, False)
        if key in local and description:
            refs.append({'kind': 'text', 'name': local[key], 'description': description})
    return refs


def fetch(url: str) -> bytes:
    headers = dict(HEADERS)
    if TOKEN and url.startswith(API + "/"):
        headers["Authorization"] = "Bearer " + TOKEN
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=70) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(1 + attempt * 2)
    raise RuntimeError("Unreachable")


def api(path: str):
    return json.loads(fetch(API + path))


def slug(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def clean_source(source: str) -> str:
    return re.sub(r"//[^\n]*|/\*[\s\S]*?\*/", "", source)


def upgrade_body(source: str) -> str:
    match = re.search(r"void\s+OnUpgrade\(\)\s*(=>[^;]*;|\{)", source)
    if not match:
        return ""
    if match[1].startswith("=>"):
        return match[1]
    start, cursor, depth = match.end(), match.end(), 1
    while cursor < len(source) and depth:
        depth += (source[cursor] == "{") - (source[cursor] == "}")
        cursor += 1
    return source[start:cursor - 1]


def numbers(source: str) -> tuple[dict, dict]:
    """Conservative extraction of literal canonical values and literal upgrade deltas."""
    base = {}
    for name, value in re.findall(r"new\s+(\w+)Var\(\s*(-?\d+(?:\.\d+)?)[mf]?\b", source):
        base[name] = float(value)
    for name, value in re.findall(r"new\s+PowerVar<(\w+)>\(\s*(-?\d+(?:\.\d+)?)[mf]?\b", source):
        base[name] = float(value)
    for name, value in re.findall(r'(?:new\s+(?:DynamicVar|\w+Var)\s*|new\s*)\(\s*"(\w+)"\s*,\s*(-?\d+(?:\.\d+)?)[mf]?\b', source):
        base[name] = float(value)
    aliases = dict(re.findall(r'const\s+string\s+(\w+)\s*=\s*"(\w+)"', source))
    for alias, value in re.findall(r'new\s+DynamicVar\(\s*(\w+)\s*,\s*(-?\d+(?:\.\d+)?)[mf]?\b', source):
        if alias in aliases:
            base[aliases[alias]] = float(value)
    upgraded = dict(base)
    on_upgrade = upgrade_body(source)
    for name, value in re.findall(r"DynamicVars\.(\w+)\.UpgradeValueBy\(\s*(-?\d+(?:\.\d+)?)[mf]?\s*\)", on_upgrade):
        key = name if name in upgraded else name + "Power"
        if key in upgraded:
            upgraded[key] += float(value)
    for name, value in re.findall(r'DynamicVars\[\s*("\w+"|\w+)\s*\]\.UpgradeValueBy\(\s*(-?\d+(?:\.\d+)?)[mf]?\s*\)', on_upgrade):
        key = name.strip('"') if name.startswith('"') else aliases.get(name)
        if key in upgraded:
            upgraded[key] += float(value)
    return base, upgraded


def fmt(number):
    return str(int(number)) if float(number).is_integer() else str(number)


def render_text(template: str, values: dict, upgraded: bool) -> tuple[str, list[str]]:
    """Resolve balanced localization expressions. Unknown runtime expressions stay explicit."""
    unresolved = set()

    def resolve(text):
        result, cursor = "", 0
        while cursor < len(text):
            if text[cursor] != "{":
                result += text[cursor]
                cursor += 1
                continue
            start, depth = cursor, 1
            cursor += 1
            while cursor < len(text) and depth:
                depth += (text[cursor] == "{") - (text[cursor] == "}")
                cursor += 1
            if depth:
                raise ValueError("Unbalanced localization expression: " + text)
            expr = text[start + 1:cursor - 1]
            if expr.startswith("IfUpgraded:show:"):
                yes, _, no = expr[len("IfUpgraded:show:"):].partition("|")
                result += resolve(yes if upgraded else no)
            elif expr.startswith("InCombat:"):
                # A static library represents an out-of-combat preview.
                _, _, no = expr[len("InCombat:"):].partition("|")
                result += resolve(no)
            else:
                key = expr.split(":", 1)[0]
                if key in values and (":" not in expr or expr.split(":", 1)[1] in ("diff()", "energyIcons()")):
                    value = values[key]
                    result += ("[energy]" * max(0, int(value))) if expr.endswith("energyIcons()") else fmt(value)
                elif (choice := re.match(r"(\w+):choose\((-?\d+)\):([\s\S]*)", expr)) and choice[1] in values:
                    yes, _, no = choice[3].partition("|")
                    result += resolve(yes if values[choice[1]] == int(choice[2]) else no)
                elif expr.startswith("ShinePileUniqueCount:choose(0):"):
                    result += ""
                else:
                    unresolved.add(key)
                    result += "〔动态值〕"
        return result

    return resolve(template), sorted(unresolved)


def parse_model(path: str, source: str, local: dict, tree: dict, category: str, pool: set, mod_id='karen') -> dict | None:
    source = clean_source(source)
    if re.search(r'\b(?:abstract|static)\s+class\b', source):
        return None
    class_match = re.search(r"\bclass\s+(\w+)", source)
    class_name = class_match[1] if class_match else Path(path).stem
    item_id = model_id(class_name)
    title = local.get(item_id + ".title")
    if not title:
        raise ValueError('Missing localized model title: ' + path)
    base_values, upgraded_values = numbers(source)
    # The canonical library card has zero disposed Shine cards; this is the
    # exact multiplier supplied by KarenCarryingGuilt.AddExtraArgsToDescription.
    if item_id == "KAREN_CARRYING_GUILT" and "ShinePileManager.GetDisposedShineCardUniqueCount" in source and "new CalculatedDamageVar" in source:
        base_values["CalculatedDamage"] = base_values["CalculationBase"]
        upgraded_values["CalculatedDamage"] = upgraded_values["CalculationBase"]
    description, missing = render_text(local.get(item_id + ".description", ""), base_values, False)
    upgraded, missing_plus = render_text(local.get(item_id + ".description", ""), upgraded_values, True)
    stem = item_id.lower()
    candidates = ([f"images/packed/card_portraits/{folder}/{stem}.png" for folder in ["karen", "token", "curse"]]
                  if category == "cards" else [f"images/{category}/{stem}_big.png", f"images/{category}/{stem}.png"])
    portrait = next((candidate for candidate in candidates if candidate in tree), None)
    if not portrait:
        raise ValueError('Missing model portrait: ' + path)
    item = {"id": item_id, "name": title, "description": description, "rawDescription": local.get(item_id + ".description", ""),
            "image": f"assets/{mod_id}/" + portrait, "sourcePath": path, "className": class_name, "unresolved": sorted(set(missing + missing_plus)),
            "flavor": local.get(item_id + ".flavor", ""), 'tipRefs': tip_references(source, local)}
    if category == "cards":
        meta = re.search(r"(?:base|KarenBaseCardModel)\(\s*(-?\d+)\s*,\s*CardType\.(\w+)\s*,\s*CardRarity\.(\w+)", source)
        item.update({"cost": int(meta[1]) if meta else None, "type": meta[2] if meta else "Unknown",
                     "rarity": meta[3] if meta else "Unknown", "upgradedDescription": upgraded, "upgradedCost": None,
                     "inPool": class_name in pool, "group": "shine" if "/shine/" in path or "AddShineMax" in source else "promise" if "/promisePile/" in path else "other"})
        # An X cost is a distinct canonical override, not an arbitrary negative cost.
        if re.search(r"HasEnergyCostX\s*=>\s*true", source):
            item["cost"] = "X"
        energy = re.search(r"(?:EnergyCost\.SetCanonical|EnergyCost\.UpgradeBy|EnergyCost\.UpgradeValueBy)\(\s*(-?\d+)\s*\)", upgrade_body(source))
        if energy and isinstance(item["cost"], int):
            item["upgradedCost"] = int(energy[1]) if "SetCanonical" in energy[0] else item["cost"] + int(energy[1])
        shine = re.search(r"AddShineMax\(\s*(\d+)\s*\)", source)
        item["shine"] = int(shine[1]) if shine else None
        keywords = re.search(r"CanonicalKeywords\s*=>\s*([\s\S]*?);", source)
        item["keywords"] = re.findall(r"CardKeyword\.(\w+)", keywords[1]) if keywords else []
        item["upgradedKeywords"] = list(item["keywords"])
        limit = re.search(r'MaxUpgradeLevel\s*=>\s*(\d+|int.MaxValue)', source)
        item['maxUpgradeLevel'] = None if limit and limit[1] == 'int.MaxValue' else int(limit[1]) if limit else 1
        growth = re.search(r'DynamicVars.Damage.UpgradeValueBy\((\d+)m\s*\+\s*_upgradeCount\)', upgrade_body(source))
        if growth and '_upgradeCount++' in upgrade_body(source) and 'Damage' in base_values:
            first = int(growth[1])
            item['upgradeGrowth'] = {'base': base_values['Damage'], 'first': first, 'step': 1}
            upgraded_values['Damage'] = base_values['Damage'] + first
            item['upgradedDescription'] = render_text(local.get(item_id + '.description', ''), upgraded_values, True)[0]
        if item_id in ['KAREN_BANANA', 'KAREN_SHINE_REPRODUCE']:
            item['bannerOverride'] = 'rare'
        tags = set(re.findall(r'KarenCustomEnum\.(\w+)', member_body(source, 'CanonicalTags')))
        tag_tips = {'PromisePileRelated': 'KAREN_PROMISE_PILE', 'ShineRelated': 'KAREN_SHINE', 'ShineCardReward': 'KAREN_SHINE_CARD_REWARD', 'TmpStrength': 'KAREN_TMP_STRENGTH', 'RetainTmpStrength': 'KAREN_RETAIN_TMP_STRENGTH', 'DisableRelicRelated': 'KAREN_DISABLE_RELIC'}
        item['tipRefs'] += [{'kind': 'mod', 'key': key} for tag, key in tag_tips.items() if tag in tags]
        if item['shine'] and 'ShineRelated' not in tags:
            item['tipRefs'].append({'kind': 'mod', 'key': 'KAREN_SHINE'})
        if item['shine']:
            item['tipRefs'].append({'kind': 'mod', 'key': 'KAREN_ETERNAL_SHINE', 'ifKeyword': 'Eternal'})
        if ': KarenDisableRelicBaseCardModel' in source and 'DisableRelicRelated' not in tags:
            item['tipRefs'].append({'kind': 'mod', 'key': 'KAREN_DISABLE_RELIC'})
        if 'new BlockVar(' in source or re.search(r'GainsBlock\s*=>\s*true', source):
            item['tipRefs'].append({'kind': 'static', 'key': 'BLOCK'})
        for action, keyword in re.findall(r"(Add|Remove)Keyword\(CardKeyword\.(\w+)\)", upgrade_body(source)):
            if action == "Add" and keyword not in item["upgradedKeywords"]:
                item["upgradedKeywords"].append(keyword)
            elif action == "Remove" and keyword in item["upgradedKeywords"]:
                item["upgradedKeywords"].remove(keyword)
        if not meta:
            raise ValueError("Unsupported card constructor: " + path)
    else:
        rarity = re.search(r"(?:RelicRarity|PotionRarity)\.(\w+)", source)
        item["rarity"] = rarity[1] if rarity else "Unknown"
        icon = f"images/{category}/{stem}.png"
        outline = f"images/{category}/{stem}_outline.png"
        item["icon"] = f"assets/{mod_id}/" + icon if icon in tree else item["image"]
        item["outline"] = f"assets/{mod_id}/" + outline if outline in tree else None
    return item


def build_karen(mod, commit, tree, blobs):
    prefix = "ShoujoKagekiAijoKaren/localization/zhs/"
    loc = {name: json.loads(blobs[prefix + name + ".json"].decode("utf-8-sig")) for name in ["cards", "characters", "relics", "potions", "card_keywords", 'powers']}
    pool_source = clean_source(blobs["src/Core/Models/CardPools/KarenCardPool.cs"].decode("utf-8-sig"))
    pool = set(re.findall(r"ModelDb.Card<(\w+)>", pool_source))
    result = {**mod, "commit": commit["sha"], "upstreamUpdatedAt": commit["commit"]["committer"]["date"],
              "syncedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
              "cards": [], "relics": [], "potions": [], "events": [], "keywords": loc["card_keywords"], 'powers': loc['powers'],
              'adapterVersion': ADAPTER_VERSION,
              'rendering': {'frameMaterialSource': 'materials/cards/frames/card_frame_purple_mat.tres', 'energySource': 'images/atlases/ui_atlas.sprites/card/energy_karen.tres', 'inlineEnergySource': 'images/packed/sprite_fonts/karen_energy_icon.png', 'gameplayPath': prefix + 'gameplay_ui.json', 'shineLabelKey': 'KAREN_SHINE_LABEL', 'shineSuffixKey': 'KAREN_SHINE_SUFFIX', 'outlineColors': {'relics': [238/255, 130/255, 238/255, .66], 'potions': [251/255, 84/255, 88/255, .66]}},
              "character": {"name": loc["characters"]["KAREN.title"], "description": loc["characters"]["KAREN.description"],
                            "image": f"assets/{mod['id']}/scenes/screens/char_select/karenPortrait.jpg", "icon": f"assets/{mod['id']}/images/packed/character_select/char_select_karen.png"}}
    char_source = blobs["src/Core/Models/Characters/Karen.cs"].decode("utf-8-sig")
    for name, prop in [("hp", "StartingHp"), ("gold", "StartingGold")]:
        match = re.search(prop + r"\s*=>\s*(\d+)", char_source)
        if not match:
            raise ValueError("Missing character " + prop)
        result["character"][name] = int(match[1])
    result["character"]["startingDeck"] = re.findall(r"ModelDb.Card<(\w+)>", char_source.split("StartingDeck", 1)[1].split("StartingRelics", 1)[0])
    result["character"]["startingRelics"] = re.findall(r"ModelDb.Relic<(\w+)>", char_source.split("StartingRelics", 1)[1].split("AttackAnimDelay", 1)[0])
    for category, folder in [("cards", "Cards"), ("relics", "Relics"), ("potions", "Potions")]:
        for path in sorted(blobs):
            if path.startswith(f"src/Core/Models/{folder}/") and path.endswith(".cs"):
                item = parse_model(path, blobs[path].decode("utf-8-sig"), loc[category], tree, category, pool, mod['id'])
                if item:
                    result[category].append(item)
    # Shared pools are injected by Harmony patches, independently of the
    # character's reward pool. Folder names such as "neutral" are not pools.
    patch_path = 'src/Core/Patches/CardPoolPatches.cs'
    patch_source = clean_source(blobs[patch_path].decode('utf-8-sig'))
    shared_pools = {}
    for match in re.finditer(r'\[HarmonyPatch\(typeof\((\w+)CardPool\),\s*"GenerateAllCards"\)\]([\s\S]*?)(?=\[HarmonyPatch|\Z)', patch_source):
        shared_pools[match[1].lower()] = set(re.findall(r'ModelDb.Card<(\w+)>', match[2]))
    for card in result['cards']:
        source = clean_source(blobs[card['sourcePath']].decode('utf-8-sig'))
        card_pool = mod['id'] if card['inPool'] else next((name for name, members in shared_pools.items() if card['className'] in members), 'unregistered')
        visual = re.search(r'VisualCardPool\s*=>\s*ModelDb.CardPool<(\w+)CardPool>', source)
        card['cardPool'] = card_pool
        card['visualPool'] = (mod['id'] if visual[1] == 'Karen' else visual[1].lower()) if visual else 'colorless' if card_pool in ['token', 'status', 'colorless'] else card_pool if card_pool != 'unregistered' else mod['id']
        card['isRegistered'] = card_pool != 'unregistered'
        card['isOption'] = '/options/' in card['sourcePath']
        if card_pool == 'token':
            card['tipRefs'].append({'kind': 'mod', 'key': 'KAREN_TOKEN_CARD'})
    # Resolve specialized power inheritance to the Mod's canonical mechanic text.
    for item in [*result['cards'], *result['relics'], *result['potions']]:
        for ref in item['tipRefs']:
            if ref['kind'] == 'power' and ref['key'].endswith('_TEMP_STRENGTH_POWER'):
                ref.update(kind='mod', key='KAREN_TMP_STRENGTH')
    for category, name, model in [('relics', 'Relic', 'Relic'), ('potions', 'Potion', 'Potion')]:
        source = clean_source(blobs[f'src/Core/Models/{name}Pools/Karen{name}Pool.cs'].decode('utf-8-sig'))
        expected = set(re.findall(r'ModelDb\.' + model + r'<(\w+)>', source))
        missing = expected - {item['className'] for item in result[category]}
        if missing:
            raise ValueError('Missing active ' + category + ': ' + ', '.join(sorted(missing)))
    imported = {c['className'] for c in result['cards']}
    missing_shared = set().union(*shared_pools.values()) - imported
    if missing_shared:
        raise ValueError('Missing shared pool cards: ' + ', '.join(sorted(missing_shared)))
    # Fail visibly if an upstream rename or constructor change silently drops pool cards.
    imported_pool = {c["className"] for c in result["cards"] if c["inPool"]}
    if pool - imported_pool:
        raise ValueError("Missing active pool cards: " + ", ".join(sorted(pool - imported_pool)))
    event_sources = [p for p in tree if re.search(r"src/Core/Models/Events/.+\.cs$", p)]
    if event_sources:
        raise ValueError("New upstream events detected; extend the event adapter before publishing.")
    return result


def selected_paths(tree):
    names = {"cards", "characters", "relics", "potions", "card_keywords", 'powers', 'gameplay_ui'}
    return [p for p in tree if (
        p.startswith("ShoujoKagekiAijoKaren/localization/zhs/") and Path(p).stem in names and p.endswith(".json")
        or re.match(r"src/Core/Models/(Cards|Relics|Potions)/.+\.cs$", p)
        or p in {"src/Core/Models/Characters/Karen.cs", "src/Core/Models/CardPools/KarenCardPool.cs", "scenes/screens/char_select/karenPortrait.jpg", "images/packed/character_select/char_select_karen.png"}
        or p == 'src/Core/Patches/CardPoolPatches.cs'
        or p in {'src/Core/Models/RelicPools/KarenRelicPool.cs', 'src/Core/Models/PotionPools/KarenPotionPool.cs', 'src/Core/Patches/CardHoverTipsPatch.cs', 'src/Core/KarenCustomEnum.cs', 'src/Core/Utils/Tips.cs'}
        or re.match(r"images/packed/card_portraits/(karen|token|curse)/[^/]+\.png$", p) and "_backup" not in p
        or re.match(r"images/(relics|potions)/[^/]+\.png$", p)
    )]


def snapshot_paths(tree, mod):
    root = mod.get('contentRoot', 'mod-info/').rstrip('/') + '/'
    if '..' in Path(root).parts or Path(root).is_absolute():
        raise ValueError('Unsafe snapshot root')
    return [path for path in tree if path.startswith(root) and path.endswith(('.json', '.png', '.jpg', '.webp', '.tres'))]


def build_snapshot(mod, commit, tree, blobs):
    path = mod.get('contentRoot', 'mod-info/').rstrip('/') + '/catalog.json'
    document = json.loads(blobs[path].decode('utf-8-sig'))
    result = {**document, **mod, 'commit': commit['sha'], 'upstreamUpdatedAt': commit['commit']['committer']['date'],
              'syncedAt': dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(), 'adapterVersion': ADAPTER_VERSION}
    for category in ['cards', 'relics', 'potions', 'events']:
        result.setdefault(category, [])
        for item in result[category]:
            item.setdefault('sourcePath', path)
            item.setdefault('tipRefs', [])
            item.setdefault('description', '')
            item.setdefault('flavor', '')
            if category == 'cards':
                for key, value in {'className': item['id'], 'maxUpgradeLevel': 1, 'keywords': [], 'upgradedKeywords': item.get('keywords', []), 'upgradedCost': None, 'upgradedDescription': item['description'], 'cardPool': mod['id'], 'visualPool': mod['id'], 'isRegistered': True, 'inPool': True, 'shine': None}.items():
                    item.setdefault(key, value)
    for item in [result['character'], *result['cards'], *result['relics'], *result['potions'], *result['events']]:
        for key in ['image', 'icon', 'outline']:
            if item.get(key):
                if item[key] not in blobs or '..' in Path(item[key]).parts:
                    raise ValueError('Snapshot asset not in content root: ' + item[key])
                item[key] = f"assets/{mod['id']}/" + item[key]
    result.setdefault('keywords', {})
    result.setdefault('powers', {})
    result.setdefault('rendering', {})
    character = result['character']
    character.setdefault('description', '')
    character.setdefault('icon', character['image'])
    character.setdefault('startingDeck', [])
    character.setdefault('startingRelics', [])
    return result


ADAPTERS = {'karen': (build_karen, selected_paths), 'snapshot': (build_snapshot, snapshot_paths)}


def check_catalog(catalog, file_exists):
    if not catalog.get("mods"):
        raise ValueError("No enabled Mods")
    if len({mod['id'] for mod in catalog['mods']}) != len(catalog['mods']):
        raise ValueError('Duplicate Mod identifier')
    for mod in catalog["mods"]:
        if not re.fullmatch(r"[0-9a-f]{40}", mod["commit"]):
            raise ValueError("Invalid snapshot commit")
        for category in ["cards", "relics", "potions", "events"]:
            seen = set()
            for item in mod[category]:
                if item["id"] in seen or not item["name"] or not file_exists(item["image"]):
                    raise ValueError(f"Invalid {category} item: {item['id']}")
                seen.add(item["id"])
                if category == 'cards' and item.get('maxUpgradeLevel', 1) is not None and item.get('maxUpgradeLevel', 1) < 0:
                    raise ValueError('Invalid upgrade limit: ' + item['id'])
                for field in ["icon", "outline"]:
                    if item.get(field) and not file_exists(item[field]):
                        raise ValueError(f"Missing {field}: {item['id']}")
        if not file_exists(mod["character"]["image"]):
            raise ValueError("Missing character image")
        for key in ['name', 'hp', 'gold', 'startingDeck', 'startingRelics']:
            if key not in mod['character']:
                raise ValueError('Missing character field: ' + key)


def synchronize(force=False, pinned=False):
    config = json.loads((ROOT / "data/mods.json").read_text(encoding="utf-8"))
    previous = json.loads((ROOT / "data/catalog.json").read_text(encoding="utf-8")) if (ROOT / "data/catalog.json").exists() else {"mods": []}
    old_mods = {m["id"]: m for m in previous["mods"]}
    old_manifest = json.loads((ROOT / "data/provenance.json").read_text(encoding="utf-8")) if (ROOT / "data/provenance.json").exists() else {}
    mods, manifests = [], {}
    staging_parent = ROOT / ".sync-staging"
    staging_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="snapshot-", dir=staging_parent) as temp_dir:
        staging = Path(temp_dir)
        if not staging.resolve().is_relative_to(staging_parent.resolve()):
            raise ValueError("Unsafe staging directory")
        for mod in config["mods"]:
            if not mod.get("enabled", True):
                continue
            if not re.fullmatch(r"[a-z0-9-]+", mod["id"]) or not re.fullmatch(r"[\w.-]+/[\w.-]+", mod["repository"]):
                raise ValueError("Unsafe Mod identifier or repository")
            if mod["adapter"] not in ADAPTERS:
                raise ValueError("Unsupported adapter " + mod["adapter"])
            repo = mod["repository"]
            old = old_mods.get(mod["id"])
            commit = {'sha': old['commit'], 'commit': {'committer': {'date': old['upstreamUpdatedAt']}}} if pinned and old else api(f"/repos/{repo}/commits/{urllib.parse.quote(mod['ref'], safe='')}")
            adapter_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            if not force and old and old.get('adapterHash') == adapter_hash and old["commit"] == commit["sha"] and all(old.get(k) == mod.get(k) for k in mod):
                print(f"{mod['id']}: unchanged at {commit['sha'][:8]}", flush=True)
                mods.append(old)
                manifests[mod["id"]] = old_manifest.get(mod["id"], {})
                continue
            print(f"{mod['id']}: importing {repo}@{commit['sha'][:8]}", flush=True)
            tree_cache = ROOT / '.sync-staging' / f"{mod['id']}-tree.json"
            legacy_cache = ROOT / '.sync-staging/mod-tree.json'
            saved = json.loads((tree_cache if tree_cache.exists() else legacy_cache).read_text(encoding='utf-8-sig')) if tree_cache.exists() or legacy_cache.exists() else {}
            listing = saved if saved.get('commit') == commit['sha'] and (saved.get('repository', repo) == repo) else api(f"/repos/{repo}/git/trees/{commit['sha']}?recursive=1")
            if listing.get("truncated"):
                raise ValueError("GitHub returned a truncated tree")
            tree = {item["path"]: item for item in listing["tree"] if item["type"] == "blob"}
            tree_cache.write_text(json.dumps({'repository': repo, 'commit': commit['sha'], 'tree': listing['tree']}), encoding='utf-8')
            builder, selector = ADAPTERS[mod['adapter']]
            paths = selector(tree, mod) if mod['adapter'] == 'snapshot' else selector(tree)
            print(f"Downloading/verifying {len(paths)} source and asset files", flush=True)
            manifest = {}

            def download(path):
                if ".." in Path(path).parts or Path(path).is_absolute():
                    raise ValueError("Unsafe upstream asset path")
                dest = "assets/" + mod["id"] + "/" + path
                old_record = old_manifest.get(mod["id"], {}).get(path, {})
                local_path = ROOT / dest
                cache = CACHE / tree[path]["sha"]
                is_asset = path.lower().endswith((".png", ".jpg", ".webp"))
                if is_asset and old_record.get("gitBlob") == tree[path]["sha"] and local_path.exists():
                    data = local_path.read_bytes()
                elif cache.exists():
                    data = cache.read_bytes()
                else:
                    data = fetch(f"https://raw.githubusercontent.com/{repo}/{commit['sha']}/{urllib.parse.quote(path)}")
                git_blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
                if git_blob != tree[path]["sha"]:
                    raise ValueError("Blob hash mismatch: " + path)
                if not cache.exists():
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_bytes(data)
                manifest[path] = {"gitBlob": git_blob, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                if is_asset:
                    target = staging / dest
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                return path, data

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                blobs = dict(executor.map(download, paths))
            parsed = builder(mod, commit, tree, blobs)
            parsed['adapterHash'] = adapter_hash
            mods.append(parsed)
            manifests[mod["id"]] = manifest
            source_dir = staging / "data" / mod["id"] / "source"
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "localization.json").write_text(json.dumps({p: json.loads(b.decode("utf-8-sig")) for p, b in blobs.items() if p.endswith(".json")}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (source_dir / "models.json").write_text(json.dumps({p: b.decode("utf-8-sig") for p, b in blobs.items() if p.endswith(".cs")}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"{mod['id']}: {len(parsed['cards'])} cards, {len(parsed['relics'])} relics, {len(parsed['potions'])} potions", flush=True)
        catalog = {"schemaVersion": 1, "mods": mods}
        check_catalog(catalog, lambda p: (staging / p).is_file() or (ROOT / p).is_file())
        encoded = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
        outputs = {"data/catalog.json": encoded,
                   "data/catalog.js": "// Generated by scripts/sync_mods.py. Do not edit.\nwindow.MOD_CATALOG = " + encoded.rstrip() + ";\n",
                   "data/provenance.json": json.dumps(manifests, ensure_ascii=False, indent=2, sort_keys=True) + "\n"}
        for name, content in outputs.items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        # No live data is touched until the complete fixed-commit import validates.
        # CI commits only after this process and the separate integrity check succeed.
        for path in staging.rglob("*"):
            if path.is_file():
                dest = ROOT / path.relative_to(staging)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)
        print("Static snapshot validated and saved.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Rebuild the pinned snapshot even when the upstream SHA has not changed")
    parser.add_argument('--pinned', action='store_true', help='Rebuild the existing fixed commit without advancing upstream')
    args = parser.parse_args()
    try:
        synchronize(args.force, args.pinned)
    except Exception as error:
        print(f"Sync failed: {error}", file=sys.stderr)
        sys.exit(1)
