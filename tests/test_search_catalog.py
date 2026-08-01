import os
import unittest
from unittest.mock import patch

import bot
import tmbd


class SearchCatalogTests(unittest.TestCase):
    def test_build_short_summary_truncates_long_text(self):
        long_text = (
            "Cette phrase est volontairement très longue pour vérifier que le résumé est bien raccourci "
            "dans l’embed de recherche, avec un texte suffisamment long pour dépasser la limite de caractères."
        )
        summary = bot.build_short_summary(long_text)

        self.assertLessEqual(len(summary), 260)
        self.assertIn("résumé", summary.lower())

    def test_search_catalog_uses_selected_genre(self):
        with patch("bot.search_tmdb") as mock_search_tmdb:
            mock_search_tmdb.return_value = [
                {
                    "title": "Dune",
                    "media_type": "movie",
                    "release_date": "2021-10-22",
                    "overview": "Un film de science-fiction.",
                    "id": 438631,
                }
            ]

            results = bot.search_catalog("Science-fiction")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["titre"], "Dune")
        mock_search_tmdb.assert_called_once_with("science fiction")

    def test_map_tmdb_result_keeps_tmdb_id_for_series(self):
        mapped = bot.map_tmdb_result({
            "id": 1396,
            "name": "Breaking Bad",
            "media_type": "tv",
            "first_air_date": "2008-01-20",
            "overview": "Un drame de crime.",
        })

        self.assertEqual(mapped["id"], 1396)
        self.assertEqual(mapped["type"], "Série")

    def test_search_tmdb_uses_tmdb_api_key_env_var(self):
        with patch.dict(os.environ, {"TMDB_API_KEY": "test-api-key"}, clear=True):
            with patch("tmbd.requests.get") as mock_get:
                mock_get.return_value.status_code = 200
                mock_get.return_value.json.return_value = {"results": [{"title": "Test"}]}

                results = tmbd.search_tmdb("inception")

        self.assertEqual(results, [{"title": "Test"}])
        mock_get.assert_called_once()
        self.assertEqual(mock_get.call_args.kwargs["params"]["api_key"], "test-api-key")

    def test_search_catalog_uses_tmdb_results(self):
        with patch("bot.search_tmdb") as mock_search_tmdb:
            mock_search_tmdb.return_value = [
                {
                    "title": "Spider-Man: No Way Home",
                    "media_type": "movie",
                    "release_date": "2021-12-15",
                    "overview": "Un film de super-héros.",
                    "id": 634649,
                }
            ]

            results = bot.search_catalog("spider man")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["titre"], "Spider-Man: No Way Home")
        self.assertEqual(results[0]["type"], "Film")
        self.assertEqual(results[0]["annee"], 2021)
        self.assertEqual(results[0]["description"], "Un film de super-héros.")


if __name__ == "__main__":
    unittest.main()
