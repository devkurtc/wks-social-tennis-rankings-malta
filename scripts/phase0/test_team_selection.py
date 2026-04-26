"""Tests for team_selection extractor (Phase 0 v2)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import team_selection  # noqa: E402


class TestClassLabelParser(unittest.TestCase):
    def test_valid_class_labels(self):
        self.assertEqual(team_selection._is_class_label("A1"), ("A", 1))
        self.assertEqual(team_selection._is_class_label("a3"), ("A", 3))
        self.assertEqual(team_selection._is_class_label("D9"), ("D", 9))
        self.assertEqual(team_selection._is_class_label(" B2 "), ("B", 2))

    def test_invalid_class_labels(self):
        self.assertIsNone(team_selection._is_class_label(""))
        self.assertIsNone(team_selection._is_class_label("CAPTAIN"))
        self.assertIsNone(team_selection._is_class_label("Kelsey"))
        self.assertIsNone(team_selection._is_class_label("A"))
        self.assertIsNone(team_selection._is_class_label("E1"))  # E not a tier letter
        self.assertIsNone(team_selection._is_class_label("1A"))


class TestExtractTeamSelection(unittest.TestCase):
    """Integration: real Antes 2025 file end-to-end."""

    def setUp(self):
        self.antes_2025 = Path(__file__).parent.parent.parent / "_DATA_" / "VLTC" / \
            "Antes Insurance Team Tournament IMO Joe results 2025.xlsx"
        if not self.antes_2025.exists():
            self.skipTest("Antes 2025 file not present")

    def test_extracts_assignments(self):
        rows = team_selection.extract_team_selection(str(self.antes_2025))
        # Antes 2025 has 6 teams × 3 slots × 4 men tiers + 6 × 3 × 3 ladies tiers
        # = 72 men + 54 ladies = ~126 expected (give or take a few empty cells)
        self.assertGreater(len(rows), 50)
        # Each row should have all required fields
        for r in rows:
            self.assertIn("team_letter", r)
            self.assertIn("class_label", r)
            self.assertIn("player_name", r)
            self.assertTrue(r["team_letter"] in "ABCDEF")
            self.assertTrue(r["tier_letter"] in "ABCD")
            self.assertGreaterEqual(r["slot_number"], 1)
            self.assertLessEqual(r["slot_number"], 9)

    def test_kurt_assigned_to_a1(self):
        rows = team_selection.extract_team_selection(str(self.antes_2025))
        kurt = [r for r in rows if r["player_name"] == "Kurt Carabott"]
        self.assertEqual(len(kurt), 1, f"Expected exactly one Kurt entry, got {kurt}")
        self.assertEqual(kurt[0]["class_label"], "A1")
        self.assertEqual(kurt[0]["tier_letter"], "A")
        self.assertEqual(kurt[0]["slot_number"], 1)
        self.assertEqual(kurt[0]["gender"], "M")

    def test_clayton_assigned_to_a1_team_a(self):
        rows = team_selection.extract_team_selection(str(self.antes_2025))
        clayton = [r for r in rows if r["player_name"] == "Clayton Zammit Cesare"]
        self.assertEqual(len(clayton), 1)
        self.assertEqual(clayton[0]["class_label"], "A1")
        self.assertEqual(clayton[0]["team_letter"], "A")
        self.assertEqual(clayton[0]["captain_name"], "Kelsey")

    def test_cory_greenland_d1(self):
        rows = team_selection.extract_team_selection(str(self.antes_2025))
        cory = [r for r in rows if r["player_name"] == "Cory Greenland"]
        self.assertEqual(len(cory), 1)
        self.assertEqual(cory[0]["class_label"], "D1")
        self.assertEqual(cory[0]["gender"], "M")

    def test_no_team_selection_sheet_returns_empty(self):
        # Use a file that has no Team Selection sheet (e.g. SE 2025)
        se_2025 = Path(__file__).parent.parent.parent / "_DATA_" / "VLTC" / \
            "Sports Experience Chosen Doubles 2025 result sheet.xlsx"
        if not se_2025.exists():
            self.skipTest("SE 2025 file not present")
        rows = team_selection.extract_team_selection(str(se_2025))
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
