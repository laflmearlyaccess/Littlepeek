import os
import requests
from dotenv import load_dotenv

load_dotenv()

TMDB_API_KEY = os.getenv("TMDB_BEARER")
TMDB_BASE_URL = "https://api.themoviedb.org/3"
GENRE_IDS = {
    "action": 28,
    "aventure": 12,
    "animation": 16,
    "comedie": 35,
    "drame": 18,
    "fantastique": 14,
    "horreur": 27,
    "science-fiction": 878,
    "science fiction": 878,
    "thriller": 53,
    "romance": 10749,
}


def search_tmdb(query, language="fr-FR", genre=None, random_choice=False):
    if not TMDB_API_KEY:
        return []

    headers = {
        "Authorization": f"Bearer {TMDB_API_KEY}",
        "Content-Type": "application/json;charset=utf-8"
    }

    try:
        if random_choice:
            url = f"{TMDB_BASE_URL}/trending/movie/week"
            params = {"language": language, "page": 1}
            response = requests.get(url, headers=headers, params=params, timeout=10)
        elif genre and genre != "Tout":
            genre_key = " ".join(str(genre).lower().split())
            genre_id = GENRE_IDS.get(genre_key)
            if genre_id is not None:
                url = f"{TMDB_BASE_URL}/discover/movie"
                params = {
                    "with_genres": genre_id,
                    "sort_by": "popularity.desc",
                    "language": language,
                    "include_adult": True,
                    "page": 1,
                }
                response = requests.get(url, headers=headers, params=params, timeout=10)
            else:
                url = f"{TMDB_BASE_URL}/search/multi"
                params = {
                    "query": query or genre,
                    "language": language,
                    "include_adult": True,
                    "page": 1,
                }
                response = requests.get(url, headers=headers, params=params, timeout=10)
        else:
            url = f"{TMDB_BASE_URL}/search/multi"
            params = {
                "query": query,
                "language": language,
                "include_adult": True,
                "page": 1,
            }
            response = requests.get(url, headers=headers, params=params, timeout=10)
    except requests.RequestException:
        return []

    if response.status_code != 200:
        return []

    return response.json().get("results", [])[:5]