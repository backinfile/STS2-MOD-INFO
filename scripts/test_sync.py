"""Focused regression tests for source parsing and safe update decisions."""
import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sync_mods as sync


class ParserTests(unittest.TestCase):
    def temporary_directory(self):
        parent = sync.ROOT / '.sync-staging' / 'tests'
        parent.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(dir=parent)

    def test_comment_does_not_become_active_card(self):
        self.assertEqual(sync.clean_source('// ModelDb.Card<Removed>();\nModelDb.Card<Active>();').strip(), 'ModelDb.Card<Active>();')

    def test_literal_upgrade_and_keyword_power_mapping(self):
        source = 'new DamageVar(5m); new PowerVar<WeakPower>(1m); void OnUpgrade(){DynamicVars.Damage.UpgradeValueBy(2m); DynamicVars.Weak.UpgradeValueBy(1m);}'
        base, plus = sync.numbers(source)
        self.assertEqual(base, {"Damage": 5, "WeakPower": 1})
        self.assertEqual(plus, {"Damage": 7, "WeakPower": 2})

    def test_balanced_upgrade_expression_and_out_of_combat(self):
        text = '{IfUpgraded:show:抽{Cards:diff()}张牌|不抽牌}{InCombat:战斗提示|}'
        self.assertEqual(sync.render_text(text, {"Cards": 2}, True), ('抽2张牌', []))
        self.assertEqual(sync.render_text(text, {"Cards": 2}, False), ('不抽牌', []))

    def test_unknown_value_stays_explicit(self):
        self.assertEqual(sync.render_text('造成{CalculatedDamage:diff()}点伤害', {}, False), ('造成〔动态值〕点伤害', ['CalculatedDamage']))

    def test_named_and_indexed_dynamic_variables(self):
        source = 'const string IncreaseVarName = "Increase"; new DynamicVar(IncreaseVarName, 2m); new DynamicVar("Relics", 1); void OnUpgrade(){ DynamicVars[IncreaseVarName].UpgradeValueBy(1m); DynamicVars["Relics"].UpgradeValueBy(1m); }'
        self.assertEqual(sync.numbers(source), ({'Increase': 2, 'Relics': 1}, {'Increase': 3, 'Relics': 2}))

    def test_choose_formatter_resolves_nested_value(self):
        text = '{Count:choose(1):第1|前{Count:diff()}}次'
        self.assertEqual(sync.render_text(text, {'Count': 2}, True), ('前2次', []))

    def test_upgrade_keywords_and_method_boundary(self):
        source = 'class Example : KarenBaseCardModel { public Example():base(1, CardType.Skill, CardRarity.Common){} CanonicalKeywords => new CardKeyword[]{ CardKeyword.Exhaust }; void OnUpgrade(){ RemoveKeyword(CardKeyword.Exhaust); AddKeyword(CardKeyword.Innate); } void Other(){ AddKeyword(CardKeyword.Ethereal); } }'
        item = sync.parse_model('Example.cs', source, {'EXAMPLE.title': 'test'}, {'images/packed/card_portraits/karen/example.png': {}}, 'cards', {'Example'})
        self.assertEqual(item['keywords'], ['Exhaust'])
        self.assertEqual(item['upgradedKeywords'], ['Innate'])

    def test_numeric_suffix_and_actual_class_name(self):
        self.assertEqual(sync.slug('KarenStarlight02Card'), 'karen_starlight02_card')
        item = sync.parse_model('src/Core/Models/Cards/KarenWeKnow.cs', 'class KarenWeKown : KarenBaseCardModel { public KarenWeKown() : base(3, CardType.Power, CardRarity.Rare) {} }', {'KAREN_WE_KOWN.title': '两人的梦想'}, {'images/packed/card_portraits/karen/karen_we_kown.png': {}}, 'cards', {'KarenWeKown'})
        self.assertTrue(item['inPool'])
        self.assertEqual(item['className'], 'KarenWeKown')

    def test_failure_preserves_previous_snapshot(self):
        with self.temporary_directory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/mods.json').write_text(json.dumps({'mods': [{'id': 'karen', 'repository': 'owner/repo', 'ref': 'main', 'adapter': 'karen'}]}))
            previous = '{"mods": []}\n'
            (root / 'data/catalog.json').write_text(previous)
            with patch.object(sync, 'ROOT', root), patch.object(sync, 'api', side_effect=RuntimeError('upstream unavailable')):
                with self.assertRaises(RuntimeError):
                    sync.synchronize()
            self.assertEqual((root / 'data/catalog.json').read_text(), previous)

    def test_unchanged_commit_skips_tree_and_download(self):
        with self.temporary_directory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            config = {'id': 'karen', 'repository': 'owner/repo', 'ref': 'main', 'adapter': 'karen', 'enabled': True}
            current = {**config, 'adapterHash': hashlib.sha256(Path(sync.__file__).read_bytes()).hexdigest(), 'commit': 'a' * 40, 'cards': [], 'relics': [], 'potions': [], 'events': [], 'character': {'image': 'example.png', 'name':'example', 'hp':10, 'gold':0, 'startingDeck':[], 'startingRelics':[]}}
            (root / 'example.png').write_bytes(b'example')
            (root / 'data/mods.json').write_text(json.dumps({'mods': [config]}))
            (root / 'data/catalog.json').write_text(json.dumps({'mods': [current]}))
            with patch.object(sync, 'ROOT', root), patch.object(sync, 'api', return_value={'sha': 'a' * 40}) as api, patch.object(sync, 'fetch') as fetch:
                sync.synchronize()
                self.assertEqual(api.call_count, 1)
                fetch.assert_not_called()

    def test_non_upgradable_card_and_explicit_mechanic_references(self):
        source = 'class Example : KarenBaseCardModel { public override int MaxUpgradeLevel => 0; public Example():base(1, CardType.Curse, CardRarity.Curse){} protected override IEnumerable<IHoverTip> ExtraHoverTips => [MechanicTip("KAREN_RETAIN_TMP_STRENGTH")]; }'
        item = sync.parse_model('Example.cs', source, {'EXAMPLE.title':'test'}, {'images/packed/card_portraits/karen/example.png':{}}, 'cards', set(), 'second-mod')
        self.assertEqual(item['maxUpgradeLevel'], 0)
        self.assertEqual(item['tipRefs'], [{'kind':'mod','key':'KAREN_RETAIN_TMP_STRENGTH'}])
        self.assertTrue(item['image'].startswith('assets/second-mod/'))

    def test_missing_concrete_model_cannot_silently_disappear(self):
        with self.assertRaisesRegex(ValueError, 'Missing localized model title'):
            sync.parse_model('NewRelic.cs', 'class NewRelic : RelicModel {}', {}, {}, 'relics', set())
        with self.assertRaisesRegex(ValueError, 'Missing model portrait'):
            sync.parse_model('NewRelic.cs', 'class NewRelic : RelicModel {}', {'NEW_RELIC.title':'new'}, {}, 'relics', set())

    def test_infinite_upgrade_first_increment_is_not_lost(self):
        source = 'class Example : KarenBaseCardModel { public Example():base(1, CardType.Attack, CardRarity.Common){} public override int MaxUpgradeLevel => int.MaxValue; new DamageVar(12m); void OnUpgrade(){ DynamicVars.Damage.UpgradeValueBy(4m + _upgradeCount); _upgradeCount++; }}'
        item = sync.parse_model('Example.cs', source, {'EXAMPLE.title':'test','EXAMPLE.description':'造成{Damage:diff()}点伤害。'}, {'images/packed/card_portraits/karen/example.png':{}}, 'cards', set())
        self.assertIsNone(item['maxUpgradeLevel'])
        self.assertEqual(item['upgradedDescription'], '造成16点伤害。')
        self.assertEqual(item['upgradeGrowth'], {'base':12,'first':4,'step':1})

    def test_second_mod_snapshot_owns_its_assets_and_ids(self):
        document = {'character':{'name':'second','image':'mod-info/portrait.png','hp':10,'gold':0}, 'cards':[{'id':'SAME_ID','name':'card','description':'text','image':'mod-info/card.png','cost':1,'type':'Skill','rarity':'Common'}]}
        blobs = {'mod-info/catalog.json': json.dumps(document).encode(), 'mod-info/portrait.png':b'image', 'mod-info/card.png':b'image'}
        commit = {'sha':'a'*40,'commit':{'committer':{'date':'2026-10-22T00:00:00Z'}}}
        first = sync.build_snapshot({'id':'first'},commit,{},blobs)
        second = sync.build_snapshot({'id':'second'},commit,{},blobs)
        self.assertEqual(first['cards'][0]['id'], second['cards'][0]['id'])
        self.assertEqual(second['cards'][0]['cardPool'], 'second')
        self.assertNotEqual(first['cards'][0]['image'], second['cards'][0]['image'])

    def test_ui_build_failure_preserves_complete_live_snapshot(self):
        import subprocess
        import update_site
        with self.temporary_directory() as directory:
            root = Path(directory)
            (root/'data').mkdir(); (root/'assets').mkdir()
            (root/'data/catalog.json').write_text('previous')
            for name in ['app.js','card-renderer.js','styles.css','collections.css','index.html']:
                (root/name).write_text('fixture')
            def build(command, **kwargs):
                stage = Path(kwargs['env']['STS2_MOD_BUILD_ROOT'])
                if command[3].endswith('sync_mods.py'):
                    (stage/'data/catalog.json').write_text('new catalog')
                else:
                    raise subprocess.CalledProcessError(1,command)
            with patch.object(update_site,'SOURCE',root), patch.object(update_site.subprocess,'run',side_effect=build):
                with self.assertRaises(subprocess.CalledProcessError):
                    update_site.update(pinned=True)
            self.assertEqual((root/'data/catalog.json').read_text(), 'previous')


if __name__ == '__main__':
    unittest.main()
