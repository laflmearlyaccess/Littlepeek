import json
import os
import tempfile
import unittest

import bot


class SearchCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.catalog_path = os.path.join(self.tmp_dir.name, "catalog.json")
        with open(self.catalog_path, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "titre": "Spider-Man: No Way Home",
                        "genre": "Action, Aventure",
                        "type": "Film",
                        "annee": 2021,
                        "description": "Un film de super-héros",
                    },
                    {
                        "titre": "Inception",
                        "genre": "Science-fiction",
                        "type": "Film",
                        "annee": 2010,
                        "description": "Un film de science-fiction",
                    },
                ],
                f,
            )
        bot.CATALOG_FILE = self.catalog_path

    def test_search_without_hyphen_matches_title(self):
        results = bot.search_catalog("spider man")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["titre"], "Spider-Man: No Way Home")


if __name__ == "__main__":
    unittest.main()
