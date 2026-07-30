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


def search_catalog(keyword: str):
    keyword = normalize_text(keyword)
    catalog = load_catalog()
    if not keyword or not catalog:
        return []

    exact_matches = [
        item for item in catalog
        if keyword in normalize_text(item.get("titre", ""))
        or keyword in normalize_text(item.get("genre", ""))
    ]
    if exact_matches:
        return exact_matches[:MAX_RESULTS]

    keyword_words = keyword.split()
    fuzzy_matches = []
    for item in catalog:
        titre_words = normalize_text(item.get("titre", "")).split()
        per_word_scores = [
            max([similarity(kw, tw) for tw in titre_words] or [0])
            for kw in keyword_words
        ]
        if all(score >= FUZZY_THRESHOLD for score in per_word_scores):
            avg_score = sum(per_word_scores) / len(per_word_scores)
            fuzzy_matches.append((avg_score, item))

    fuzzy_matches.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in fuzzy_matches][:MAX_RESULTS]


class SearchModal(discord.ui.Modal, title="Recherche dans le catalogue"):
    keyword = discord.ui.TextInput(
        label="Titre ou genre à rechercher",
        placeholder="Ex: Inception, Science-fiction...",
        required=True,
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        results = search_catalog(str(self.keyword))

        if not results:
            await interaction.response.send_message(
                f"❌ Aucun résultat pour **{self.keyword}**.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"🔍 Résultats pour « {self.keyword} »",
            color=discord.Color.blurple(),
        )
        view = discord.ui.View(timeout=None)

        MAX_BUTTONS = 25
        buttons_added = 0

        for item in results:
            embed.add_field(
                name=f"{item['titre']} ({item.get('annee', '????')}) — {item.get('type', 'N/A')}",
                value=f"*{item.get('genre', 'N/A')}*\n{item.get('description', '')}",
                inline=False,
            )

            lien = item.get("lien", "").strip()
            if lien and buttons_added < MAX_BUTTONS:
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