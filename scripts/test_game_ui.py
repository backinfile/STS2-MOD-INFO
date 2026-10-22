"""Native asset conversion regressions; no network or game installation required."""
import json
import re
import unittest

import import_game_ui as ui
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.basePen import NullPen


class NativeAssetTests(unittest.TestCase):
    def test_neutral_shader_and_alpha(self):
        image = ui.Image.new('RGBA', (2, 1))
        image.putdata([(37, 111, 204, 80), (223, 72, 19, 255)])
        result = ui.tint(image, (1, 1, 1))
        self.assertEqual(result.tobytes(), image.tobytes())

    def test_font_variation_preserves_advance_and_transforms_outline(self):
        font = ui.TTFont(ui.ASSETS / 'game-regular.woff2', recalcTimestamp=False)
        options = ui.subset.Options()
        sub = ui.subset.Subsetter(options=options)
        sub.populate(text='伤')
        sub.subset(font)
        name = font.getBestCmap()[ord('伤')]
        before = BoundsPen(font.getGlyphSet())
        font.getGlyphSet()[name].draw(before)
        advance = font['hmtx'].metrics[name][0]
        shift = .05 * (font['hhea'].ascent - font['hhea'].descent)
        ui.apply_font_variation(font, .95, -.05)
        after = BoundsPen(font.getGlyphSet())
        font.getGlyphSet()[name].draw(after)
        self.assertEqual(font['hmtx'].metrics[name][0], advance)
        for actual, expected in zip(after.bounds, (before.bounds[0]*.95, before.bounds[1]*.95+shift, before.bounds[2]*.95, before.bounds[3]*.95+shift)):
            self.assertAlmostEqual(actual, expected, places=4)

    def test_shipped_chinese_glyph_coverage(self):
        catalog = json.loads((ui.ROOT / 'data/catalog.json').read_text(encoding='utf-8'))
        text = json.dumps(catalog, ensure_ascii=False)
        for name in ['game-regular.woff2', 'game-bold.woff2', 'game-medium.woff2']:
            used = text
            if name != 'game-regular.woff2':
                tag = 'b' if name == 'game-bold.woff2' else 'i'
                used = ''.join(re.findall(r'\[' + tag + r'\]([\s\S]*?)\[/' + tag + r'\]', text))
            needed = {ord(c) for c in re.findall(r'[\u3400-\u9fff]', used)}
            font = ui.TTFont(ui.ASSETS / name)
            self.assertFalse(needed - font.getBestCmap().keys(), name + ': Chinese glyph missing')

    def test_font_charstring_and_layout_advances_agree(self):
        for name in ['game-regular.woff2', 'game-bold.woff2', 'game-medium.woff2']:
            font = ui.TTFont(ui.ASSETS / name)
            strings = font['CFF '].cff.topDictIndex[0].CharStrings
            for glyph in font.getGlyphOrder():
                charstring = strings[glyph]
                charstring.draw(NullPen())
                self.assertEqual(charstring.width, font['hmtx'].metrics[glyph][0], name + ': ' + glyph)


if __name__ == '__main__':
    unittest.main()
