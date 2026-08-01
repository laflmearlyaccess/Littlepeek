import random
import discord
from discord import app_commands
from discord.ext import commands
import os
import json
import difflib
import re
import unicodedata
from dotenv import load_dotenv
from keep_alive import keep_alive
from tmbd import search_tmdb


class SeasonEpisodeButton(discord.ui.Button):
    def __init__(self, show_id: str, title: str):
        label = title if len(title) <= 75 else title[:72] + "..."
        super().__init__(label=f"🎬 {label}", style=discord.ButtonStyle.primary)
        self.show_id = show_id
        self.title = title

    async def callback(self, interaction: discord.Interaction):
        modal = EpisodeModal(self.show_id, self.title)
        await interaction.response.send_modal(modal)


class EpisodeModal(discord.ui.Modal, title="Choisir la saison et l’épisode"):
    def __init__(self, show_id: str, title: str):
        super().__init__(title="Choisir la saison et l’épisode")
        self.show_id = show_id
        self.title = title
        self.season_input = discord.ui.TextInput(
            label="Numéro de la saison",
            placeholder="Ex: 1",
            required=True,
            max_length=3,
        )
        self.episode_input = discord.ui.TextInput(
            label="Numéro de l’épisode",
            placeholder="Ex: 1",
            required=True,
            max_length=3,
        )
        self.add_item(self.season_input)
        self.add_item(self.episode_input)

    async def on_submit(self, interaction: discord.Interaction):
        season = self.season_input.value.strip()
        episode = self.episode_input.value.strip()
        if not season.isdigit() or not episode.isdigit():
            await interaction.response.send_message("⚠️ La saison et l’épisode doivent être des nombres.", ephemeral=True)
            return

        url = f"https://cinejoy.to/watch/tv/{self.show_id}/{season}/{episode}"
        view = discord.ui.View(timeout=None)
        view.add_item(
            discord.ui.Button(
                label="▶️ Ouvrir la série",
                style=discord.ButtonStyle.link,
                url=url,
            )
        )
        await interaction.response.send_message("Accédez à l'épisode ici :", view=view, ephemeral=True)

load_dotenv()

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

CATALOG_FILE = "catalog.json"
MAX_RESULTS = 10
FUZZY_THRESHOLD = 0.75

MEMBER_COMMANDS_CHANNEL = "cmds"


def in_member_commands_channel():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.channel is not None and interaction.channel.name == MEMBER_COMMANDS_CHANNEL
    return app_commands.check(predicate)


def load_catalog():
    if not os.path.exists(CATALOG_FILE):
        return []
    with open(CATALOG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def map_tmdb_result(item: dict):
    title = item.get("title") or item.get("name") or ""
    if not title:
        return None

    media_type = item.get("media_type")
    if media_type == "movie":
        item_type = "Film"
    elif media_type == "tv":
        item_type = "Série"
    else:
        item_type = "Autre"

    release_date = item.get("release_date") or item.get("first_air_date") or ""
    annee = int(release_date[:4]) if release_date and release_date[:4].isdigit() else None

    tmdb_id = item.get("id")
    if media_type == "movie" and tmdb_id:
        link = f"https://cinejoy.to/watch/movie/{tmdb_id}"
    elif media_type == "tv" and tmdb_id:
        link = f"https://cinejoy.to/watch/show/{tmdb_id}"
    else:
        link = ""

    return {
        "titre": title,
        "type": item_type,
        "annee": annee,
        "genre": "",
        "description": item.get("overview", ""),
        "lien": link,
        "id": tmdb_id,
    }


def build_short_summary(text: str, max_length: int = 260) -> str:
    if not text:
        return "Résumé indisponible."

    cleaned = " ".join(text.split())
    if len(cleaned) <= max_length:
        return cleaned

    truncated = cleaned[:max_length].rsplit(" ", 1)[0]
    return f"{truncated}…"


def search_catalog(keyword: str):
    keyword = normalize_text(keyword)
    if not keyword:
        return []

    tmdb_results = search_tmdb(keyword)
    mapped_results = [result for result in (map_tmdb_result(item) for item in tmdb_results) if result]
    return mapped_results[:MAX_RESULTS]


class SearchModal(discord.ui.Modal, title="Recherche dans le catalogue"):
    def __init__(self):
        super().__init__(title="Recherche dans le catalogue")
        self.keyword_input = discord.ui.TextInput(
            label="Titre à rechercher",
            placeholder="Ex: Inception, Breaking Bad...",
            required=True,
            max_length=100,
        )
        self.add_item(self.keyword_input)

    async def on_submit(self, interaction: discord.Interaction):
        keyword_value = self.keyword_input.value or ""
        results = search_catalog(keyword_value)

        if not results:
            await interaction.response.send_message(
                f"❌ Aucun résultat pour **{keyword_value}**.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"🔍 Résultats pour « {keyword_value} »",
            color=discord.Color.blurple(),
        )
        view = discord.ui.View(timeout=None)

        MAX_BUTTONS = 25
        buttons_added = 0

        for item in results:
            summary = build_short_summary(item.get("description", ""))
            embed.add_field(
                name=f"{item['titre']} ({item.get('annee', '????')}) — {item.get('type', 'N/A')}",
                value=summary,
                inline=False,
            )

            lien = item.get("lien", "").strip()
            if item.get("type") == "Série" and item.get("lien"):
                view.add_item(
                    SeasonEpisodeButton(item.get("id", ""), item["titre"])
                )
                buttons_added += 1
            elif lien and buttons_added < MAX_BUTTONS:
                label = item["titre"]
                if len(label) > 75:
                    label = label[:72] + "..."
                view.add_item(
                    discord.ui.Button(
                        label=f"▶️ {label}",
                        style=discord.ButtonStyle.link,
                        url=lien,
                    )
                )
                buttons_added += 1

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Recherche",
        emoji="🔍",
        style=discord.ButtonStyle.primary,
        custom_id="panel_recherche_button",
    )
    async def recherche_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchModal())


@bot.event
async def on_ready():
    bot.add_view(PanelView())
    try:
        synced = await bot.tree.sync()
        print(f"{len(synced)} commande(s) slash synchronisée(s) globalement (jusqu'à 1h pour apparaître).")

        for guild in bot.guilds:
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
        print(f"Commandes synchronisées instantanément sur {len(bot.guilds)} serveur(s).")
    except Exception as e:
        print(f"Erreur de synchronisation des commandes : {e}")
    print(f"Connecté en tant que {bot.user} (ID: {bot.user.id})")


REQUIRED_ROLE = "staff"


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


SERVER_RULES = [
    ("🔞", "Pas de contenu NSFW", "Aucun contenu à caractère explicite ou choquant n'est toléré.",
     "No NSFW content of any kind is tolerated."),
    ("🤝", "Respectez-vous les uns les autres", "Aucune insulte, harcèlement ou comportement toxique envers les autres membres.",
     "No insults, harassment, or toxic behavior towards other members."),
    ("📢", "Pas de promotion ni de publicité", "Merci de ne pas faire la promotion d'autres serveurs, produits ou services sans autorisation.",
     "Please do not advertise other servers, products, or services without permission."),
    ("💰", "Pas de vente ni de transaction", "Aucune vente, achat ou échange de biens/services n'est autorisé sur ce serveur.",
     "No selling, buying, or trading of goods/services is allowed on this server."),
    ("🚫", "Pas de spam", "Évitez les messages répétitifs, les mentions abusives et le flood dans les salons.",
     "Avoid repetitive messages, excessive mentions, and channel flooding."),
    ("🎯", "Restez dans le sujet du salon", "Utilisez chaque salon pour ce à quoi il est destiné.",
     "Use each channel for its intended purpose."),
    ("👮", "Respectez les décisions du staff", "Les modérateurs veillent au bon fonctionnement du serveur ; leurs décisions doivent être respectées.",
     "Moderators keep the server running smoothly; their decisions must be respected."),
]


@bot.tree.command(name="rules", description="Affiche le règlement du serveur")
@app_commands.checks.has_role(REQUIRED_ROLE)
async def rules(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📜 Règlement du serveur",
        description="Merci de respecter les règles suivantes pour garder une communauté saine.",
        color=discord.Color.blurple(),
    )
    for emoji, titre, texte_fr, texte_en in SERVER_RULES:
        embed.add_field(
            name=f"{emoji} {titre}",
            value=f"{texte_fr}\n-# {texte_en}",
            inline=False,
        )
    await interaction.response.send_message(embed=embed, ephemeral=False)


@rules.error
async def rules_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingRole):
        await interaction.response.send_message(
            f"❌ Tu dois avoir le rôle **{REQUIRED_ROLE}** pour utiliser cette commande.",
            ephemeral=True,
        )
    else:
        print(f"Erreur /rules : {error}")
        await interaction.response.send_message("Une erreur est survenue.", ephemeral=True)


@bot.tree.command(name="stats", description="Affiche le nombre de films et de séries dans le catalogue")
@in_member_commands_channel()
async def stats(interaction: discord.Interaction):
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

    await interaction.response.send_message(embed=embed, ephemeral=False)


@stats.error
async def stats_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        print(f"/stats bloqué : utilisé hors de #{MEMBER_COMMANDS_CHANNEL} par {interaction.user}.")
        return
    print(f"Erreur /stats : {error}")


STAFF_COMMANDS = {"panel", "rules"}
COMMANDS_PER_PAGE = 5


def build_phelp_embed(page_commands: list, page_num: int, total_pages: int) -> discord.Embed:
    embed = discord.Embed(
        title="📖 Commandes disponibles",
        description=(
            f"Toutes ces commandes ne fonctionnent que dans #{MEMBER_COMMANDS_CHANNEL}.\n"
            f"Page {page_num}/{total_pages}"
        ),
        color=discord.Color.blurple(),
    )
    for cmd in page_commands:
        embed.add_field(name=f"/{cmd.name}", value=cmd.description or "Pas de description.", inline=False)
    return embed


class PhelpNavButton(discord.ui.Button):
    def __init__(self, label: str, target_page: int, parent_view: "PhelpView"):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.target_page = target_page
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.current = self.target_page
        self.parent_view.refresh_buttons()
        embed = build_phelp_embed(
            self.parent_view.pages[self.parent_view.current],
            self.parent_view.current + 1,
            len(self.parent_view.pages),
        )
        await interaction.response.edit_message(embed=embed, view=self.parent_view)


class PhelpView(discord.ui.View):
    def __init__(self, pages: list):
        super().__init__(timeout=120)
        self.pages = pages
        self.current = 0
        self.refresh_buttons()

    def refresh_buttons(self):
        self.clear_items()
        if self.current > 0:
            self.add_item(PhelpNavButton("◀️ Précédent", self.current - 1, self))
        if self.current < len(self.pages) - 1:
            self.add_item(PhelpNavButton("Suivant ▶️", self.current + 1, self))


@bot.tree.command(name="phelp", description="Affiche la liste des commandes disponibles pour les membres")
@in_member_commands_channel()
async def phelp(interaction: discord.Interaction):
    commands_list = [cmd for cmd in bot.tree.get_commands() if cmd.name not in STAFF_COMMANDS]
    pages = [
        commands_list[i:i + COMMANDS_PER_PAGE]
        for i in range(0, len(commands_list), COMMANDS_PER_PAGE)
    ] or [[]]

    embed = build_phelp_embed(pages[0], 1, len(pages))
    view = PhelpView(pages)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@phelp.error
async def phelp_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        print(f"/phelp bloqué : utilisé hors de #{MEMBER_COMMANDS_CHANNEL} par {interaction.user}.")
        return
    print(f"Erreur /phelp : {error}")


@bot.tree.command(name="tag", description="Affiche ton tag mural (pseudo, avatar, date d'arrivée)")
@in_member_commands_channel()
async def tag(interaction: discord.Interaction):
    member = interaction.user
    embed = discord.Embed(
        title=f"🏷️ Tag de {member.display_name}",
        color=discord.Color.blurple(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Pseudo", value=member.display_name, inline=True)

    joined_at = getattr(member, "joined_at", None)
    joined_str = joined_at.strftime("%d/%m/%Y") if joined_at else "Inconnue"
    embed.add_field(name="Arrivé le", value=joined_str, inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=False)


@tag.error
async def tag_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        print(f"/tag bloqué : utilisé hors de #{MEMBER_COMMANDS_CHANNEL} par {interaction.user}.")
        return
    print(f"Erreur /tag : {error}")


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