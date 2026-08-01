import random
import discord
from discord import app_commands
from discord.ext import commands
import os
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


class EpisodeModal(discord.ui.Modal, title="Select Season and Episode"):
    def __init__(self, show_id: str, title: str):
        super().__init__(title="Select Season and Episode")
        self.show_id = show_id
        self.title = title
        self.season_input = discord.ui.TextInput(
            label="Season number",
            placeholder="Ex: 1",
            required=True,
            max_length=3,
        )
        self.episode_input = discord.ui.TextInput(
            label="Episode number",
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
            await interaction.response.send_message("⚠️ Season and episode must be numbers.", ephemeral=True)
            return

        url = f"https://cinejoy.to/watch/tv/{self.show_id}/{season}/{episode}"
        view = discord.ui.View(timeout=None)
        view.add_item(
            discord.ui.Button(
                label="▶️ Open the show",
                style=discord.ButtonStyle.link,
                url=url,
            )
        )
        await interaction.response.send_message("Access the episode here:", view=view, ephemeral=True)

load_dotenv()

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

MAX_RESULTS = 10
FUZZY_THRESHOLD = 0.75

MEMBER_COMMANDS_CHANNEL = "cmds"


def in_member_commands_channel():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.channel is not None and interaction.channel.name == MEMBER_COMMANDS_CHANNEL
    return app_commands.check(predicate)


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
        item_type = "Movie"
    elif media_type == "tv":
        item_type = "TV Show"
    else:
        item_type = "Other"

    release_date = item.get("release_date") or item.get("first_air_date") or ""
    year = int(release_date[:4]) if release_date and release_date[:4].isdigit() else None

    tmdb_id = item.get("id")
    if media_type == "movie" and tmdb_id:
        link = f"https://cinejoy.to/watch/movie/{tmdb_id}"
    elif media_type == "tv" and tmdb_id:
        link = f"https://cinejoy.to/watch/show/{tmdb_id}"
    else:
        link = ""

    return {
        "title": title,
        "type": item_type,
        "year": year,
        "genre": "",
        "description": item.get("overview", ""),
        "link": link,
        "id": tmdb_id,
    }


def build_short_summary(text: str, max_length: int = 260) -> str:
    if not text:
        return "Summary unavailable."

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


class SearchModal(discord.ui.Modal, title="Search the catalog"):
    def __init__(self):
        super().__init__(title="Search the catalog")
        self.keyword_input = discord.ui.TextInput(
            label="Title to search",
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
                f"❌ No results for **{keyword_value}**.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f'🔍 Results for "{keyword_value}"',
            color=discord.Color.blurple(),
        )
        view = discord.ui.View(timeout=None)

        MAX_BUTTONS = 25
        buttons_added = 0

        for item in results:
            summary = build_short_summary(item.get("description", ""))
            embed.add_field(
                name=f"{item['title']} ({item.get('year', '????')}) — {item.get('type', 'N/A')}",
                value=summary,
                inline=False,
            )

            link = item.get("link", "").strip()
            if item.get("type") == "TV Show" and item.get("link"):
                view.add_item(
                    SeasonEpisodeButton(item.get("id", ""), item["title"])
                )
                buttons_added += 1
            elif link and buttons_added < MAX_BUTTONS:
                label = item["title"]
                if len(label) > 75:
                    label = label[:72] + "..."
                view.add_item(
                    discord.ui.Button(
                        label=f"▶️ {label}",
                        style=discord.ButtonStyle.link,
                        url=link,
                    )
                )
                buttons_added += 1

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Search",
        emoji="🔍",
        style=discord.ButtonStyle.primary,
        custom_id="panel_recherche_button",
    )
    async def search_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchModal())


@bot.event
async def on_ready():
    bot.add_view(PanelView())
    try:
        synced = await bot.tree.sync()
        print(f"{len(synced)} slash command(s) synced globally (may take up to 1 hour to appear).")

        for guild in bot.guilds:
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
        print(f"Commands synced instantly on {len(bot.guilds)} server(s).")
    except Exception as e:
        print(f"Error syncing commands: {e}")
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


@bot.tree.command(name="panel", description="Display the movies & series catalog panel")
async def panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎬 Movies & TV Shows Catalog",
        description="Click **Search** to find a movie or series in the catalog.",
        color=discord.Color.blurple(),
    )
    await interaction.response.send_message(embed=embed, view=PanelView())


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError(
            "DISCORD_TOKEN not found. Check your .env file "
            "(it must contain: DISCORD_TOKEN=your_token_here)"
        )
    print("Starting bot...")
    keep_alive()
    bot.run(token)