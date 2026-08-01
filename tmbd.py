import logging
import os
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

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


def _get_tmdb_auth():
    for env_name in ("TMDB_BEARER", "TMDB_ACCESS_TOKEN", "TMDB_READ_ACCESS_TOKEN"):
        value = os.getenv(env_name)
        if value and str(value).strip():
            token = str(value).strip()
            if token.lower().startswith("bearer "):
                token = token[7:].strip()
            return "bearer", token

    api_key = os.getenv("TMDB_API_KEY")
    if api_key and str(api_key).strip():
        return "api_key", str(api_key).strip()

    return None, None


def search_tmdb(query, language="fr-FR", genre=None, random_choice=False):
    auth_type, auth_value = _get_tmdb_auth()
    if not auth_type or not auth_value:
        logger.error("TMDB credentials missing. Set TMDB_BEARER, TMDB_ACCESS_TOKEN, TMDB_READ_ACCESS_TOKEN or TMDB_API_KEY in the environment.")
        return []

    headers = {"Content-Type": "application/json;charset=utf-8"}
    if auth_type == "bearer":
        headers["Authorization"] = f"Bearer {auth_value}"

    try:
        if random_choice:
            url = f"{TMDB_BASE_URL}/trending/movie/week"
            params = {"language": language, "page": 1}
            if auth_type == "api_key":
                params["api_key"] = auth_value
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
                if auth_type == "api_key":
                    params["api_key"] = auth_value
                response = requests.get(url, headers=headers, params=params, timeout=10)
            else:
                url = f"{TMDB_BASE_URL}/search/multi"
                params = {
                    "query": query or genre,
                    "language": language,
                    "include_adult": True,
                    "page": 1,
                }
                if auth_type == "api_key":
                    params["api_key"] = auth_value
                response = requests.get(url, headers=headers, params=params, timeout=10)
        else:
            url = f"{TMDB_BASE_URL}/search/multi"
            params = {
                "query": query,
                "language": language,
                "include_adult": True,
                "page": 1,
            }
            if auth_type == "api_key":
                params["api_key"] = auth_value
            response = requests.get(url, headers=headers, params=params, timeout=10)
    except requests.RequestException as exc:
        logger.exception("TMDB request failed: %s", exc)
        return []

    if response.status_code != 200:
        logger.error("TMDB request failed with status %s: %s", response.status_code, response.text[:400])
        return []

    try:
        payload = response.json()
    except ValueError as exc:
        logger.exception("TMDB returned invalid JSON: %s", exc)
        return []

    return payload.get("results", [])[:5]