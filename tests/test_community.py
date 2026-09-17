"""Regression coverage for the catalogue with an authenticated, new voter."""

import sqlite3
import unittest
from unittest.mock import patch

from backend import accounts


class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        connection = patch.object(accounts.sqlite3, "connect", return_value=self.db)
        connection.start()
        self.addCleanup(connection.stop)
        self.author = accounts.create_user("author@example.com", "password123", "Author")
        self.voter = accounts.create_user("voter@example.com", "password123", "Voter")
        self.first = accounts.save_design(self.author["id"], "First", {}, "", None)
        self.second = accounts.save_design(self.author["id"], "Second", {}, "", None)

    def test_catalogue_before_and_after_voting(self):
        guest = accounts.community_designs()
        logged_in = accounts.community_designs(user_id=self.voter["id"])
        self.assertEqual(guest, logged_in)
        self.assertEqual(len(logged_in), 2)
        self.assertTrue(all(d["rating"]["mine"] is None for d in logged_in))

        accounts.rate_design(self.voter["id"], self.first["id"], 4)
        designs = {d["id"]: d for d in accounts.community_designs(user_id=self.voter["id"])}
        self.assertEqual(designs[self.first["id"]]["rating"], {"average": 4.0, "count": 1, "mine": 4})
        self.assertIsNone(designs[self.second["id"]]["rating"]["mine"])
        self.assertEqual(accounts.leaderboard()[0]["nickname"], "Author")
        public = accounts.community_designs("First")[0]
        self.assertEqual(public["rating"]["average"], 4.0)
        self.assertIsNone(public["rating"]["mine"])

    def test_public_profile_and_owner_editing(self):
        guest = accounts.profile(self.author["id"])
        self.assertFalse(guest["is_owner"])
        self.assertEqual(guest["user"]["nickname"], "Author")
        self.assertEqual(guest["stats"]["designs"], 2)
        self.assertEqual(sum(day["count"] for day in guest["activity"]), 2)

        updated = accounts.update_profile(self.author["id"], {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "city": "London",
            "bio": "Cover designer",
            "website": "https://example.com",
            "social_link": "https://social.example/ada",
            "avatar_url": "https://example.com/avatar.png",
        })
        self.assertTrue(updated["is_owner"])
        self.assertEqual(updated["user"]["first_name"], "Ada")
        self.assertEqual(updated["user"]["avatar_url"], "https://example.com/avatar.png")

        with self.assertRaises(ValueError):
            accounts.update_profile(self.author["id"], {"website": "example.com"})

    def test_rating_can_be_changed_removed_and_not_self_applied(self):
        with self.assertRaises(PermissionError):
            accounts.rate_design(self.author["id"], self.first["id"], 5)

        self.assertEqual(accounts.rate_design(self.voter["id"], self.first["id"], 4)["mine"], 4)
        self.assertEqual(accounts.rate_design(self.voter["id"], self.first["id"], 0), {
            "average": 0.0,
            "count": 0,
            "mine": None,
        })

    def test_ranked_designers_designs_and_my_rank(self):
        accounts.rate_design(self.voter["id"], self.first["id"], 5)
        designers = accounts.top_designers(5)
        self.assertEqual(designers[0]["id"], self.author["id"])
        self.assertEqual(designers[0]["average"], 5.0)
        self.assertEqual(designers[0]["designs"], 2)
        self.assertEqual(designers[0]["ratings"], 1)

        designs = accounts.top_designs(5)
        self.assertEqual(designs[0]["id"], self.first["id"])
        self.assertEqual(designs[0]["average"], 5.0)
        self.assertEqual(accounts.my_rank(self.author["id"])["rank"], 1)
        self.assertIsNone(accounts.my_rank(self.voter["id"])["rank"])


if __name__ == "__main__":
    unittest.main()
