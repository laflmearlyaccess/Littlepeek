"""
Intégration JustWatch pour la recherche de films/séries et leurs plateformes
de streaming disponibles en France.

⚠️ IMPORTANT : JustWatch n'a pas d'API publique officielle. Ce module utilise
le package Python "JustWatch" (github.com/dawoudt/JustWatchAPI), qui s'appuie
sur l'API interne de justwatch.com. Cette API peut changer sans préavis côté
JustWatch, ce qui casserait ce module. Si les recherches cessent de fonctionner
du jour au lendemain, c'est la première chose à vérifier.
"""

from justwatch import JustWatch

jw_client = None  # initialisé au démarrage du bot (voir init_justwatch)
PROVIDER_MAP = {}  # provider_id -> nom lisible de la plateforme

LABELS_MONETIZATION = {
    "flatrate": "Abonnement",
    "free": "Gratuit",
    "ads": "Gratuit avec pub",
    "rent": "Location",
    "buy": "Achat",
}


def init_justwatch():
    """
    Initialise le client JustWatch pour la France.
    Fait un appel réseau (bloquant) : à appeler depuis un executor, pas
    directement dans une coroutine asyncio.
    """
    global jw_client
    jw_client = JustWatch(country="FR")


def load_providers():
    """Récupère la liste des plateformes (Netflix, Disney+, etc.) et met en cache leur nom."""
    global PROVIDER_MAP
    if jw_client is None:
        return
    try:
        providers = jw_client.get_providers()
        PROVIDER_MAP = {
            p["id"]: p.get("clear_name") or p.get("short_name") or f"Plateforme {p['id']}"
            for p in providers
        }
    except Exception as e:
        print(f"Erreur chargement des plateformes JustWatch : {e}")


def search(query: str, limit: int = 5):
    """
    Cherche un film ou une série par mot-clé.
    Retourne une liste d'items bruts JustWatch (dict), limitée à `limit`.
    """
    if jw_client is None:
        raise RuntimeError("Client JustWatch non initialisé (init_justwatch() n'a pas été appelé).")
    result = jw_client.search_for_item(query=query, content_types=["movie", "show"])
    return result.get("items", [])[:limit]


def get_title_details(title_id, content_type: str):
    """Récupère les détails complets d'un titre (offres de streaming, saisons pour une série, etc.)."""
    return jw_client.get_title(title_id, content_type=content_type)


def get_season_episodes(season_id):
    """Récupère la liste des épisodes d'une saison, avec leurs offres de streaming propres."""
    data = jw_client.get_season(season_id)
    return data.get("episodes", [])


def offers_to_platform_list(offers: list) -> list[tuple[str, str]]:
    """
    Transforme une liste d'offres JustWatch en liste de tuples (libellé, url)
    prêts à être affichés comme boutons. Dédoublonne par plateforme+type.
    """
    seen = set()
    platforms = []
    for offer in offers or []:
        provider_id = offer.get("provider_id")
        url = (offer.get("urls") or {}).get("standard_web")
        monetization = offer.get("monetization_type")
        if not url or provider_id is None:
            continue
        key = (provider_id, monetization)
        if key in seen:
            continue
        seen.add(key)
        provider_name = PROVIDER_MAP.get(provider_id, f"Plateforme {provider_id}")
        mono_label = LABELS_MONETIZATION.get(monetization, "")
        label = f"{provider_name} ({mono_label})" if mono_label else provider_name
        platforms.append((label, url))
    return platforms