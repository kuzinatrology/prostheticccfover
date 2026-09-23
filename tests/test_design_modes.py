"""Each tab reads a saved design back through its own parameters.

The tabs share a panel and nothing else: a design saved on Iteration 2 carries
fields the transtibial cover has never heard of, and reading it back through
the wrong class would silently return that class's defaults instead.
"""

import unittest

from backend.app import DESIGN_MODES


class DesignModeTests(unittest.TestCase):
    def test_every_tab_the_front_end_offers_can_be_saved(self):
        self.assertEqual(
            sorted(DESIGN_MODES),
            ["anatomic", "iter1", "iter2", "proto", "reference", "transfemoral", "transtibial"],
        )

    def test_a_tab_keeps_its_own_fields(self):
        saved = DESIGN_MODES["iter2"]({"magnet_count": 4.0, "flexion": 120.0})
        self.assertEqual(saved["magnet_count"], 4.0)
        self.assertEqual(saved["flexion"], 120.0)

        scaled = DESIGN_MODES["proto"]({"scale": 0.5})
        self.assertEqual(scaled["scale"], 0.5)

    def test_a_tab_drops_fields_that_are_not_its_own(self):
        """And does not fall over on them: a transtibial cover has no magnets."""
        plain = DESIGN_MODES["transtibial"]({"magnet_count": 4.0, "length": 400.0})
        self.assertNotIn("magnet_count", plain)
        self.assertEqual(plain["length"], 400.0)

    def test_values_outside_a_tab_s_range_are_pulled_back_in(self):
        pulled = DESIGN_MODES["proto"]({"scale": 99.0})
        self.assertLessEqual(pulled["scale"], 1.0)


if __name__ == "__main__":
    unittest.main()
