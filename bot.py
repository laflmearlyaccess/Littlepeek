import discord
from discord import app_commands
from discord.ext import commands
import os
import json
import difflib
from dotenv import load_dotenv
from keep_alive import keep_alive

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


# --- Modal (formulaire) de recherche ---
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

        # Discord limite à 25 composants par message (5 lignes x 5) :
        # on limite donc le nombre de boutons affichés au besoin.
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
                # Bouton "lien" : Discord ouvre directement l'URL, pas besoin
                # de gérer le clic côté bot.
                label = item["titre"]
                if len(label) > 75:  # limite Discord (80 caractères) avec marge
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