import discord
from discord import app_commands
from discord.ext import commands
import os
import json
import difflib
import asyncio
from dotenv import load_dotenv
from keep_alive import keep_alive
import justwatch_helper

load_dotenv()

# --- Configuration ---
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

CATALOG_FILE = "catalog.json"
MAX_RESULTS = 10
FUZZY_THRESHOLD = 0.75  # 0 = tout accepté, 1 = correspondance exacte uniquement


def load_catalog():
    """Charge le catalogue depuis le fichier JSON."""
    if not os.path.exists(CATALOG_FILE):
        return []
    with open(CATALOG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def search_catalog(keyword: str):
    """
    Cherche le mot-clé dans le titre ou le genre.
    - Correspondance directe (sous-chaîne) en priorité : si elle donne des
      résultats, on s'arrête là (pas de recherche floue en plus).
    - Sinon seulement, recherche floue sur les titres (tolère les fautes
      de frappe) via difflib.
    """
    keyword = keyword.lower().strip()
    catalog = load_catalog()
    if not keyword or not catalog:
        return []

    exact_matches = [
        item for item in catalog
        if keyword in item["titre"].lower() or keyword in item.get("genre", "").lower()
    ]
    if exact_matches:
        return exact_matches[:MAX_RESULTS]

    # Aucune correspondance directe : on tente une recherche floue,
    # uniquement sur les titres (pas les genres, pour éviter les faux
    # positifs comme "inception" qui matcherait avec "fiction").
    # On compare mot-clé par mot-clé (si plusieurs mots) à chaque mot du titre.
    keyword_words = keyword.split()
    fuzzy_matches = []
    for item in catalog:
        titre_words = item["titre"].lower().split()
        # Pour chaque mot du mot-clé, on cherche son meilleur score face aux mots du titre
        per_word_scores = [
            max([similarity(kw, tw) for tw in titre_words] or [0])
            for kw in keyword_words
        ]
        # Tous les mots du mot-clé doivent avoir une correspondance correcte
        if all(score >= FUZZY_THRESHOLD for score in per_word_scores):
            avg_score = sum(per_word_scores) / len(per_word_scores)
            fuzzy_matches.append((avg_score, item))

    fuzzy_matches.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in fuzzy_matches][:MAX_RESULTS]


# --- Étape 4 (séries) : sélection de l'épisode, puis affichage des plateformes ---
class EpisodeSelect(discord.ui.Select):
    def __init__(self, episodes: list, show_title: str, season_number):
        self.episodes = episodes
        self.show_title = show_title
        self.season_number = season_number
        options = [
            discord.SelectOption(
                label=f"Épisode {ep.get('episode_number', '?')} — {ep.get('title', 'Sans titre')}"[:100],
                value=str(ep["id"]),
            )
            for ep in episodes[:25]  # limite Discord : 25 options max
        ]
        super().__init__(placeholder="Choisis l'épisode...", options=options)

    async def callback(self, interaction: discord.Interaction):
        episode_id = int(self.values[0])
        episode = next((e for e in self.episodes if e["id"] == episode_id), None)
        if episode is None:
            await interaction.response.edit_message(content="❌ Épisode introuvable.", embed=None, view=None)
            return

        platforms = justwatch_helper.offers_to_platform_list(episode.get("offers", []))
        embed = discord.Embed(
            title=f"{self.show_title} — Saison {self.season_number}, Épisode {episode.get('episode_number', '?')}",
            description=episode.get("title", ""),
            color=discord.Color.blurple(),
        )

        view = discord.ui.View(timeout=180)
        if not platforms:
            embed.add_field(name="Disponibilité", value="Aucune plateforme trouvée pour cet épisode en France.")
        else:
            for label, url in platforms[:25]:
                view.add_item(discord.ui.Button(label=f"▶️ {label}", style=discord.ButtonStyle.link, url=url))

        await interaction.response.edit_message(embed=embed, view=view)


class EpisodeSelectView(discord.ui.View):
    def __init__(self, episodes: list, show_title: str, season_number):
        super().__init__(timeout=180)
        self.add_item(EpisodeSelect(episodes, show_title, season_number))


# --- Étape 3 (séries) : sélection de la saison ---
class SeasonSelect(discord.ui.Select):
    def __init__(self, seasons: list, show_title: str):
        self.seasons = seasons
        self.show_title = show_title
        options = [
            discord.SelectOption(
                label=f"Saison {s.get('season_number', '?')}"[:100],
                value=str(s["id"]),
            )
            for s in seasons[:25]
        ]
        super().__init__(placeholder="Choisis la saison...", options=options)

    async def callback(self, interaction: discord.Interaction):
        season_id = int(self.values[0])
        season = next((s for s in self.seasons if s["id"] == season_id), None)
        if season is None:
            await interaction.response.edit_message(content="❌ Saison introuvable.", embed=None, view=None)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            episodes = await asyncio.get_event_loop().run_in_executor(
                None, justwatch_helper.get_season_episodes, season_id
            )
        except Exception as e:
            print(f"Erreur récupération des épisodes JustWatch : {e}")
            await interaction.edit_original_response(
                content="❌ Erreur en récupérant les épisodes. Réessaie plus tard.", embed=None, view=None
            )
            return

        if not episodes:
            await interaction.edit_original_response(
                content=f"❌ Aucun épisode trouvé pour la saison {season.get('season_number', '?')}.",
                embed=None, view=None,
            )
            return

        embed = discord.Embed(
            title=f"{self.show_title} — Saison {season.get('season_number', '?')}",
            description="Choisis l'épisode :",
            color=discord.Color.blurple(),
        )
        view = EpisodeSelectView(episodes, self.show_title, season.get("season_number", "?"))
        await interaction.edit_original_response(embed=embed, view=view)


class SeasonSelectView(discord.ui.View):
    def __init__(self, seasons: list, show_title: str):
        super().__init__(timeout=180)
        self.add_item(SeasonSelect(seasons, show_title))


# --- Étape 2 : sélection du bon titre parmi les résultats de recherche ---
class TitleSelect(discord.ui.Select):
    def __init__(self, items: list):
        self.items = items
        options = []
        for item in items:
            year = item.get("original_release_year", "????")
            kind = "Série" if item.get("object_type") == "show" else "Film"
            label = f"{item.get('title', 'Sans titre')} ({year}) — {kind}"[:100]
            options.append(discord.SelectOption(label=label, value=str(item["id"])))
        super().__init__(placeholder="Choisis le bon titre...", options=options)

    async def callback(self, interaction: discord.Interaction):
        item_id = int(self.values[0])
        item = next((i for i in self.items if i["id"] == item_id), None)
        if item is None:
            await interaction.response.edit_message(content="❌ Titre introuvable.", embed=None, view=None)
            return

        is_show = item.get("object_type") == "show"
        content_type = "show" if is_show else "movie"
        title = item.get("title", "Sans titre")

        await interaction.response.defer(ephemeral=True)
        try:
            details = await asyncio.get_event_loop().run_in_executor(
                None, justwatch_helper.get_title_details, item_id, content_type
            )
        except Exception as e:
            print(f"Erreur récupération des détails JustWatch : {e}")
            await interaction.edit_original_response(
                content="❌ Erreur en récupérant les détails de ce titre. Réessaie plus tard.",
                embed=None, view=None,
            )
            return

        if is_show:
            seasons = details.get("seasons", [])
            if not seasons:
                await interaction.edit_original_response(
                    content=f"❌ Aucune saison trouvée pour **{title}**.", embed=None, view=None
                )
                return
            embed = discord.Embed(
                title=title,
                description="Choisis la saison :",
                color=discord.Color.blurple(),
            )
            view = SeasonSelectView(seasons, title)
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            platforms = justwatch_helper.offers_to_platform_list(details.get("offers", []))
            embed = discord.Embed(
                title=title,
                description=item.get("short_description", ""),
                color=discord.Color.blurple(),
            )
            view = discord.ui.View(timeout=180)
            if not platforms:
                embed.add_field(name="Disponibilité", value="Aucune plateforme trouvée pour ce film en France.")
            else:
                for label, url in platforms[:25]:
                    view.add_item(discord.ui.Button(label=f"▶️ {label}", style=discord.ButtonStyle.link, url=url))
            await interaction.edit_original_response(embed=embed, view=view)


class TitleSelectView(discord.ui.View):
    def __init__(self, items: list):
        super().__init__(timeout=180)
        self.add_item(TitleSelect(items))


# --- Modal (formulaire) de recherche ---
class SearchModal(discord.ui.Modal, title="Recherche d'un film ou d'une série"):
    keyword = discord.ui.TextInput(
        label="Titre à rechercher",
        placeholder="Ex: Inception, Stranger Things...",
        required=True,
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            items = await asyncio.get_event_loop().run_in_executor(
                None, justwatch_helper.search, str(self.keyword)
            )
        except Exception as e:
            print(f"Erreur recherche JustWatch : {e}")
            await interaction.followup.send(
                "❌ Erreur pendant la recherche. Réessaie plus tard.", ephemeral=True
            )
            return

        if not items:
            await interaction.followup.send(
                f"❌ Aucun résultat pour **{self.keyword}**.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"🔍 Résultats pour « {self.keyword} »",
            description="Sélectionne le bon titre dans la liste ci-dessous :",
            color=discord.Color.blurple(),
        )
        view = TitleSelectView(items)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)



# --- Vue persistante du panel ---
class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # pas de timeout = reste actif indéfiniment

    @discord.ui.button(
        label="Recherche",
        emoji="🔍",
        style=discord.ButtonStyle.primary,
        custom_id="panel_recherche_button",  # custom_id fixe = nécessaire pour la persistance
    )
    async def recherche_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchModal())


@bot.event
async def on_ready():
    # Ré-enregistre la vue persistante à chaque redémarrage du bot,
    # sinon le bouton cesse de répondre après un restart.
    bot.add_view(PanelView())

    # Initialise le client JustWatch (appels réseau bloquants -> executor)
    try:
        await asyncio.get_event_loop().run_in_executor(None, justwatch_helper.init_justwatch)
        await asyncio.get_event_loop().run_in_executor(None, justwatch_helper.load_providers)
        print("Client JustWatch initialisé.")
    except Exception as e:
        print(f"Erreur d'initialisation de JustWatch : {e}")

    try:
        synced = await bot.tree.sync()
        print(f"{len(synced)} commande(s) slash synchronisée(s).")
    except Exception as e:
        print(f"Erreur de synchronisation des commandes : {e}")
    print(f"Connecté en tant que {bot.user} (ID: {bot.user.id})")


REQUIRED_ROLE = "staff"  # nom exact du rôle autorisé à utiliser /panel


def only_in_cmds_channel():
    async def predicate(interaction: discord.Interaction):
        channel = interaction.channel
        if channel is None or getattr(channel, "name", "").lower() != "cmds":
            raise app_commands.CheckFailure("Cette commande doit être utilisée dans le salon #cmds.")
        return True

    return app_commands.check(predicate)


@bot.tree.command(name="panel", description="Affiche le panel du catalogue films/séries")
@app_commands.checks.has_role(REQUIRED_ROLE)
async def panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎬 Catalogue Films & Séries",
        description="Clique sur **Recherche** pour trouver un film ou une série dans le catalogue.",
        color=discord.Color.blurple(),
    )
    await interaction.response.send_message(embed=embed, view=PanelView())


@panel.error
async def panel_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingRole):
        await interaction.response.send_message(
            f"❌ Tu dois avoir le rôle **{REQUIRED_ROLE}** pour utiliser cette commande.",
            ephemeral=True,
        )
    else:
        print(f"Erreur /panel : {error}")
        await interaction.response.send_message(
            "Une erreur est survenue.", ephemeral=True
        )


@bot.tree.command(name="cinestats", description="Affiche le nombre de films et de séries dans le catalogue")
@only_in_cmds_channel()
async def cinestats(interaction: discord.Interaction):
    catalog = load_catalog()
    nb_films = sum(1 for item in catalog if item.get("type") == "Film")
    nb_series = sum(1 for item in catalog if item.get("type") == "Série")
    nb_autres = len(catalog) - nb_films - nb_series

    embed = discord.Embed(
        title="📊 Statistiques du catalogue",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="🎬 Films", value=str(nb_films), inline=True)
    embed.add_field(name="📺 Séries", value=str(nb_series), inline=True)
    embed.add_field(name="📦 Total", value=str(len(catalog)), inline=True)
    if nb_autres:
        embed.set_footer(text=f"{nb_autres} entrée(s) sans type reconnu (ni 'Film' ni 'Série')")

    await interaction.response.send_message(embed=embed, ephemeral=True)


@cinestats.error
async def cinestats_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message(
            "⚠️ Cette commande ne peut être utilisée que dans le salon #cmds.",
            ephemeral=True,
        )
    else:
        print(f"Erreur /cinestats : {error}")
        await interaction.response.send_message("Une erreur est survenue.", ephemeral=True)


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError(
            "DISCORD_TOKEN introuvable. Vérifie ton fichier .env "
            "(il doit contenir : DISCORD_TOKEN=ton_token_ici)"
        )
    print("Lancement du bot...")
    keep_alive()
    bot.run(token)