"""Targeted checks for committed local imports and Junna's native catalog."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import sync_mods as sync
from junna_adapter import initialize_groups


class JunnaTests(unittest.TestCase):
    def test_local_source_imports_committed_bytes(self):
        parent = sync.ROOT / '.sync-staging/tests'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            def git(*args):
                return subprocess.check_output(['git', '-C', directory, *args], stderr=subprocess.DEVNULL)
            git('init', '--quiet')
            git('remote', 'add', 'origin', 'https://github.com/example/mod.git')
            file = Path(directory) / 'card.json'
            file.write_bytes(b'committed')
            git('add', 'card.json')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.com', 'commit', '-qm', 'fixture')
            file.write_bytes(b'uncommitted')
            commit, tree, read = sync.local_snapshot(directory, 'example/mod')
            self.assertEqual(len(commit['sha']), 40)
            self.assertEqual(read(tree['tree'][0]['sha']), b'committed')
            with self.assertRaisesRegex(ValueError, 'origin'):
                sync.local_snapshot(directory, 'example/other')

    def test_reverse_knowledge_groups(self):
        groups = initialize_groups([{'mainCardId': 'A', 'grantedCardIds': ['B'], 'grantedCardCounts': {'B': 2}}])
        self.assertEqual(groups['A'], {'A': 1, 'B': 2})
        self.assertEqual(groups['B'], {'B': 2, 'A': 1})

    def test_catalog_keeps_associated_cards_and_native_arrow_metadata(self):
        mods = json.loads((sync.ROOT / 'data/catalog.json').read_text('utf-8'))['mods']
        junna = next(mod for mod in mods if mod['id'] == 'junna')
        source = json.loads((sync.ROOT / 'data/junna/source/localization.json').read_text('utf-8'))['data/card-pool.json']
        by_design = {card['designId']: card for card in junna['cards']}
        self.assertEqual(set(by_design), {card['id'] for card in source['cards']})
        for definition in source['cards']:
            card = by_design[definition['id']]
            self.assertTrue(card['isRegistered'])
            self.assertTrue(card['image'].startswith('assets/junna/'))
            self.assertEqual(card['unresolved'], [])
            if definition['type'] == '飞矢':
                self.assertEqual(card['type'], 'Arrow')
                self.assertEqual(card['arrowTurns'], next(v['base'] for v in definition['values'] if v['name'] == 'Turns'))
        self.assertIsNone(by_design['JK82']['maxUpgradeLevel'])
        self.assertEqual(by_design['JK82']['upgradeGrowth']['first'], 1)
        self.assertIn('[energy]', by_design['B']['description'])
        self.assertEqual(len(junna['relics']), 3)
        self.assertEqual(len(junna['potions']), 3)


if __name__ == '__main__':
    unittest.main()
