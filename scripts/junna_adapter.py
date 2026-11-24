"""Read Junna's embedded card catalog and source declarations without running C#."""
import colorsys
import datetime as dt
import json
from pathlib import Path
import re

PREFIX = 'ShoujoKagekiJunna/'
RARITIES = dict(zip(['基础', '普通', '罕见', '稀有', '远古', '事件', '衍生', '状态', '诅咒', '任务'],
                    ['Basic', 'Common', 'Uncommon', 'Rare', 'Ancient', 'Event', 'Token', 'Status', 'Curse', 'Quest']))
TYPES = {'攻击': 'Attack', '技能': 'Skill', '能力': 'Power', '诅咒': 'Curse', '状态': 'Status', '任务': 'Quest', '飞矢': 'Arrow'}


def junna_paths(tree):
    return [path for path in tree if (
        path in ['data/card-pool.json', 'data/card-rules.json']
        or path.startswith('src/Models/') and path.endswith('.cs')
        or path in ['src/UI/Arrows/ArrowCardPresentation.cs', 'src/UI/Arrows/ArrowPortraitTexture.cs',
                    'src/Combat/Knowledge/KnowledgeCombat.cs', 'ShoujoKagekiJunna/scripts/character_select_layers.gd']
        or path.startswith(PREFIX + 'localization/zhs/') and path.endswith('.json')
        or path.startswith(PREFIX + 'images/') and path.endswith(('.png', '.jpg', '.webp', '.svg'))
        and (any('/' + folder + '/' in path for folder in ['cards', 'relics', 'potions', 'events', 'energy_counter'])
             or path in [PREFIX + 'images/character_select/motion_poster.png', PREFIX + 'images/character_select_icon.png', PREFIX + 'images/arrow_portrait_frame.png'])
    )]


def initialize_groups(definitions):
    """KnowledgeGroup.Initialize also builds the reverse associations."""
    groups = {g['mainCardId']: {g['mainCardId']: g.get('mainCardCount', 1),
              **{key: g.get('grantedCardCounts', {}).get(key, 1) for key in g['grantedCardIds']}} for g in definitions}
    referenced = {}
    for definition in definitions:
        for key in set(definition['grantedCardIds']):
            if definition.get('grantedCardCounts', {}).get(key, 1) > 0:
                referenced.setdefault(key, []).append(definition['mainCardId'])
    for key, sources in referenced.items():
        if key not in groups:
            counts = dict(groups[sources[0]]) if len(sources) == 1 else dict.fromkeys(sources, 1)
            own = counts.pop(key, 1)
            groups[key] = {key: max(1, own), **counts}
    return groups


def build_junna(mod, commit, tree, blobs):
    from sync_mods import ADAPTER_VERSION, clean_source, numbers, render_text
    def document(path):
        return json.loads(blobs[path].decode('utf-8-sig'))
    def text(path):
        return blobs[path].decode('utf-8-sig')
    def asset(path):
        if path not in blobs:
            raise ValueError('Missing Junna asset: ' + path)
        return 'assets/' + mod['id'] + '/' + path
    loc = {name: document(PREFIX + 'localization/zhs/' + name + '.json')
           for name in ['characters', 'cards', 'relics', 'potions', 'events', 'card_keywords', 'powers', 'gameplay_ui']}
    shine_loc = document('upstream/shine/resources/ShoujoKagekiCore/localization/zhs/card_keywords.json')
    shine_ui = document('upstream/shine/resources/ShoujoKagekiCore/localization/zhs/gameplay_ui.json')
    catalog = document('data/card-pool.json')
    rules = document('data/card-rules.json')['cards']
    definitions = {c['id']: c for c in [*catalog['cards'], *catalog.get('retiredCards', [])]}
    groups = initialize_groups(catalog['groups'])
    declarations = {}
    for path, data in blobs.items():
        if not path.startswith('src/Models/') or not path.endswith('.cs'):
            continue
        source = clean_source(data.decode('utf-8-sig'))
        matches = list(re.finditer(r'(?:\[[^\]]+\]\s*)*(?:public|internal)\s+(?:(?:sealed|abstract|partial|static)\s+)*class\s+(\w+)\b', source))
        for i, match in enumerate(matches):
            body = source[match.start():matches[i+1].start() if i+1 < len(matches) else len(source)]
            if match[1] in declarations:
                old_path, old_body = declarations[match[1]]
                declarations[match[1]] = (path if 'CustomID(' in body else old_path, old_body + '\n' + body)
            else:
                declarations[match[1]] = (path, body)
    def model_source(class_name, expected_id):
        path, source = declarations[class_name]
        custom_id = re.search(r'CustomID\("([^"]+)"\)', source)
        if not custom_id or custom_id[1] != expected_id:
            raise ValueError('Junna model ID differs from catalog: ' + class_name)
        return path, source
    char_path, char_source = model_source('Junna', 'JUNNA')
    shader = re.search(r'ShaderColor\s*=>\s*new\("([0-9A-Fa-f]{6})"\)', text(char_path))
    if not shader:
        raise ValueError('Missing Junna pool shader color')
    hsv = colorsys.rgb_to_hsv(*(int(shader[1][i:i+2], 16)/255 for i in [0, 2, 4]))
    result = {**mod, 'commit': commit['sha'], 'upstreamUpdatedAt': commit['commit']['committer']['date'],
              'syncedAt': dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(), 'adapterVersion': ADAPTER_VERSION,
              'cards': [], 'relics': [], 'potions': [], 'events': [], 'keywords': {**loc['card_keywords'], **shine_loc}, 'powers': loc['powers'],
              'rendering': {'frameHsv': list(hsv), 'energySource': PREFIX + 'images/energy_counter/energy_icon.png',
                            'inlineEnergySource': PREFIX + 'images/energy_counter/energy_icon_small.png',
                            'energyOutlineColor': '#173c2f', 'gameplayPath': PREFIX + 'localization/zhs/gameplay_ui.json',
                            'shineLabel': shine_ui['CORE_SHINE_LABEL'], 'shineSuffix': shine_ui['CORE_SHINE_SUFFIX'],
                            'arrowPresentationSource': 'src/UI/Arrows/ArrowCardPresentation.cs',
                            'arrowFrameSource': PREFIX + 'images/arrow_portrait_frame.png'},
              'character': {'name': loc['characters']['JUNNA.title'], 'description': loc['characters']['JUNNA.description'],
                            'image': asset(PREFIX + 'images/character_select/motion_poster.png'),
                            'icon': asset(PREFIX + 'images/character_select_icon.png'), 'hp': catalog['startingHp'], 'gold': catalog['startingGold'],
                            'startingDeck': [definitions[entry['cardId']]['className'] for entry in catalog['startingDeck'] for _ in range(entry['count'])],
                            'startingRelics': [name for name, (_, source) in declarations.items() if any('CustomID("' + key + '")' in source for key in catalog['startingRelics'])]}}
    for definition in catalog['cards']:
        design_id, item_id = definition['id'], definition['modelId']
        path, source = model_source(definition['className'], item_id)
        rule = rules.get(design_id, {})
        base = {v['name']: v['base'] for v in definition['values']}
        plus = {v['name']: v['upgraded'] for v in definition['values']}
        for alias, field in rule.get('fields', {}).items():
            if field in base:
                base[alias], plus[alias] = base[field], plus[field]
        # The canonical library model has no owner or combat state.
        if design_id == 'JA108':
            base['ArrowCount'] = plus['ArrowCount'] = 0
        raw = loc['cards'][item_id + '.description']
        description, missing = render_text(raw, base, False)
        upgraded, missing_plus = render_text(raw, plus, True)
        def tips(upgrade):
            refs = []
            names = set(rule.get('upgradedTips' if upgrade else 'tips', []))
            if definition.get('knowledge') or 'Knowledge' in names:
                refs.append({'kind': 'mod', 'key': 'SHOUJOKAGEKIJUNNA-' + ('CHAIN_KNOWLEDGE' if design_id == 'JK126' else 'KNOWLEDGE')})
            if design_id in groups or design_id == 'JK126':
                refs.append({'kind': 'text', 'name': loc['gameplay_ui']['JUNNA.KNOWLEDGE_GROUP'],
                             'description': '\n'.join('[gold]' + definitions[key]['name'] + '[/gold]' for key, count in groups.get(design_id, {design_id: 1}).items() for _ in range(count))})
            background = loc['gameplay_ui'].get('JUNNA.KNOWLEDGE_BACKGROUND.' + design_id)
            if background:
                refs.append({'kind': 'text', 'name': loc['gameplay_ui']['JUNNA.KNOWLEDGE_BACKGROUND'], 'description': background})
            refs += [{'kind': 'card', 'id': definitions[key]['modelId'], 'upgraded': upgrade and design_id == 'JA145' and key == 'JA119'} for key in rule.get('relatedCards', [])]
            if 'Meteor' in names:
                meteor = definitions['JA81B']
                values = {v['name']: v['base'] for v in meteor['values']}
                values['Damage'] = (plus if upgrade else base)['Damage']
                refs.append({'kind': 'card', 'id': meteor['modelId'], 'upgraded': False,
                             'description': render_text(loc['cards'][meteor['modelId']+'.description'], values, False)[0]})
            if definition['type'] == '飞矢' or 'Arrow' in names:
                refs.append({'kind': 'mod', 'key': 'SHOUJOKAGEKIJUNNA-ARROW'})
            for name in ['Weak', 'Vulnerable']:
                if name in names:
                    refs.append({'kind': 'power', 'key': name.upper() + '_POWER'})
            for name, key, kind in [('Energy', 'ENERGY', 'static'), ('Retain', 'RETAIN', 'keyword')]:
                if name in names:
                    refs.append({'kind': kind, 'key': key})
            if definition['type'] != '能力' and 'Block' in base:
                refs.append({'kind': 'static', 'key': 'BLOCK'})
            if 'ShineCard(' in source:
                refs.append({'kind': 'mod', 'key': 'SHOUJO_CORE_SHINE'})
            return refs
        flags = ['Exhaust', 'Retain', 'Innate', 'Ethereal']
        limit = re.search(r'MaxUpgradeLevel\s*=>\s*(\d+|int.MaxValue)', source)
        item = {'id': item_id, 'designId': design_id, 'className': definition['className'], 'sourcePath': path,
                'name': loc['cards'][item_id + '.title'], 'description': description, 'upgradedDescription': upgraded,
                'rawDescription': raw, 'image': asset(PREFIX + 'images/cards/' + definition['portrait']),
                'type': TYPES[definition['type']], 'rarity': RARITIES[definition['rarity']],
                'cost': 'X' if definition['costsX'] else definition['cost'], 'upgradedCost': 'X' if definition['costsX'] else definition['upgradedCost'],
                'keywords': [k for k in flags if definition.get(k[0].lower()+k[1:])],
                'upgradedKeywords': [k for k in flags if definition.get('upgraded'+k)],
                'maxUpgradeLevel': None if limit and limit[1] == 'int.MaxValue' else int(limit[1]) if limit else 1, 'cardPool': mod['id'], 'visualPool': mod['id'],
                'inPool': definition['pool'], 'isRegistered': not definition.get('choiceOnly', False), 'isOption': definition.get('choiceOnly', False),
                'shine': int(re.search(r'ShineCard\((\d+)\)', source)[1]) if 'ShineCard(' in source else None,
                'flavor': loc['cards'].get(item_id + '.flavor', ''), 'unresolved': sorted(set(missing+missing_plus)),
                'tipRefs': tips(False), 'upgradedTipRefs': tips(True)}
        if definition['type'] == '飞矢':
            item['arrowTurns'], item['upgradedArrowTurns'] = base['Turns'], plus['Turns']
        if item['maxUpgradeLevel'] is None:
            field, delta = re.search(r'CardValueNames.Resolve\(DesignId,\s*"(\w+)"\)\]\.UpgradeValueBy\((\d+)\)', source).groups()
            item['upgradeGrowth'] = {'base': base[field], 'first': int(delta), 'step': 0}
        result['cards'].append(item)
    # Pool attributes are inherited by potion and gem subclasses; verify every
    # concrete registered model instead of skipping unfamiliar declarations.
    for name, (path, source) in declarations.items():
        if 'abstract class' in source or 'static class' in source:
            continue
        gem = re.search(r':\s*JunnaGem\(\d+,\s*"([^"]+)"\)', source)
        potion = re.search(r':\s*JunnaPotion\("([^"]+)"\)', source)
        relic = ': CustomRelicModel' in source
        if not (gem or potion or relic):
            continue
        category = 'potions' if potion else 'relics'
        item_id = re.search(r'CustomID\("([^"]+)"\)', source)[1]
        model_source(name, item_id)
        values, _ = numbers(source)
        if name == 'JunnaSpikeTape':
            key, value = re.search(r'new EnergyVar\((\w+),\s*(\d+)\)', source).groups()
            alias = re.search(r'const string ' + key + r'\s*=\s*"([^"]+)"', source)[1]
            values[alias] = int(value)
        description, missing = render_text(loc[category][item_id + '.description'], values, False)
        rarity = 'Starter' if gem else re.search(r'(?:Potion|Relic)Rarity\.(\w+)', source)[1]
        stem = gem[1] if gem else potion[1] if potion else re.search(r'IconBasePath\s*=.*?"images/relics/([^"]+)"', source)[1]
        extension = '.svg' if gem else '.png'
        icon = PREFIX + 'images/' + category + '/' + stem
        refs = [{'kind': 'mod', 'key': 'SHOUJOKAGEKIJUNNA-' + key.upper()} for key in re.findall(r'FromKeyword\(JunnaKeywords\.(\w+)\)', source)]
        result[category].append({'id': item_id, 'className': name, 'sourcePath': path, 'name': loc[category][item_id + '.title'],
                                 'description': description, 'flavor': loc[category].get(item_id + '.flavor', ''), 'rarity': rarity,
                                 'image': asset(icon + ('_big.png' if relic else extension)), 'icon': asset(icon + extension),
                                 'outline': asset(icon + '_outline' + extension), 'unresolved': missing, 'tipRefs': refs})
    for category in ['relics', 'potions']:
        expected = {key.removesuffix('.title') for key in loc[category] if key.endswith('.title')}
        if expected != {item['id'] for item in result[category]}:
            raise ValueError('Junna ' + category + ' registration/localization differs')
    event_id = 'JUNNA_STAGE_GIRL_NOTES'
    path, source = model_source('JunnaStageGirlNotes', event_id)
    options = list(dict.fromkeys(re.findall(r'\.pages.INITIAL.options\.(\w+)', source)))
    portrait = re.search(r'CustomInitialPortraitPath\s*=>\s*JunnaMod.ResourceRoot\s*\+\s*"([^"]+)"', source)[1]
    result['events'].append({'id': event_id, 'sourcePath': path, 'name': loc['events'][event_id + '.title'],
                              'description': loc['events'][event_id + '.pages.INITIAL.description'], 'image': asset(PREFIX + portrait),
                              'isAvailable': not bool(re.search(r'IsAllowed\([^)]*\)\s*=>\s*false', source)),
                              'options': [{'name': loc['events'][event_id + '.pages.INITIAL.options.' + key + '.title'],
                                           'description': loc['events'][event_id + '.pages.INITIAL.options.' + key + '.description']} for key in options]})
    return result
