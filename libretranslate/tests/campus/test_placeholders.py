"""占位符保护的单元测试。"""
import unittest

from libretranslate.campus.placeholders import PlaceholderTable


class PlaceholderTableTest(unittest.TestCase):
    def setUp(self):
        self.table = PlaceholderTable()
        self.slot_a = self.table.add("数据结构", "структуры данных", "term")
        self.slot_b = self.table.add("3-412", "3-412", "pattern", {"rule": "room"})

    def test_tokens_are_numbered_from_one(self):
        self.assertEqual(self.slot_a.index, 1)
        self.assertEqual(self.slot_b.index, 2)
        self.assertEqual(self.slot_a.token(), "[[T1]]")
        self.assertEqual(self.slot_b.token(), "[[T2]]")

    def test_same_value_shares_one_slot(self):
        again = self.table.add("数据结构", "структуры данных", "term")
        self.assertIs(again, self.slot_a)
        self.assertEqual(len(self.table), 2)

    def test_render_mixes_text_and_slots(self):
        rendered = self.table.render(["本课程讲授", self.slot_a, "，教室 ", self.slot_b])
        self.assertEqual(rendered, "本课程讲授[[T1]]，教室 [[T2]]")

    def test_strict_restore(self):
        result = self.table.restore("Курс охватывает [[T1]], аудитория [[T2]].")
        self.assertEqual(result.text, "Курс охватывает структуры данных, аудитория 3-412.")
        self.assertTrue(result.ok)
        self.assertEqual(result.restore_rate, 1.0)

    def test_loose_restore_handles_mangled_brackets(self):
        for mangled in ("Курс [T1] тут", "Курс (T2) тут", "Курс {{T1}} тут", "Курс [[ t1 ]] тут"):
            result = self.table.restore(mangled)
            self.assertNotIn("T1", result.text.replace("t1", "T1"))
            self.assertTrue(result.restored, "should restore from %r" % mangled)

    def test_lost_slots_are_reported(self):
        result = self.table.restore("Курс охватывает много всего.")
        self.assertFalse(result.ok)
        self.assertEqual([slot.index for slot in result.lost], [1, 2])
        self.assertEqual(result.restore_rate, 0.0)

    def test_partial_loss_reports_only_missing(self):
        result = self.table.restore("Курс [[T1]] без второго.")
        self.assertEqual([slot.index for slot in result.restored], [1])
        self.assertEqual([slot.index for slot in result.lost], [2])
        self.assertAlmostEqual(result.restore_rate, 0.5)

    def test_duplicate_placeholder_is_flagged(self):
        result = self.table.restore("[[T1]] и снова [[T1]]")
        self.assertEqual(len(result.restored), 1)
        self.assertEqual(len(result.duplicated), 1)

    def test_unknown_index_is_left_alone(self):
        result = self.table.restore("Число [[T99]] не наш.")
        self.assertIn("[[T99]]", result.text)

    def test_bare_tokens_require_opt_in(self):
        self.assertIn("T1", self.table.restore("Курс T1 без скобок").text)
        result = self.table.restore("Курс T1 без скобок", loose=True, allow_bare=True)
        self.assertEqual(result.text, "Курс структуры данных без скобок")


if __name__ == "__main__":
    unittest.main()
