import json
import re
import os
import asyncio
import unicodedata
from pathlib import Path
import httpx
from dotenv import load_dotenv

load_dotenv()
TMDB_BEARER = os.getenv("TMDB_BEARER")
TMDB = "https://api.themoviedb.org/3"
CINEJOY = "https://cinejoy.to"
CATALOG = Path("catalog.json")

HEADERS = {
    "Authorization": f"Bearer {TMDB_BEARER}",
    "accept": "application/json",
}


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_-]+", "-", text).strip("-")


async def tmdb_search(client, titre, annee, is_movie):
    endpoint = "movie" if is_movie else "tv"
    params = {"query": titre, "year": annee} if is_movie else {"query": titre, "first_air_date_year": annee}
    response = await client.get(f"{TMDB}/{endpoint}/search", params=params)
    if response.status_code == 200:
        data = response.json()
        if data["results"]:
            return data["results"][0]["id"]
    return None