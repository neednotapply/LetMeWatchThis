import os
import json
import logging
import urllib.parse
import asyncio
import uuid

import aiohttp
import discord
from discord import Interaction, app_commands
from discord.ext import commands
from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, "config.json")

with open(config_path, "r") as f:
    config = json.load(f)

TOKEN = config["token"]
GUILD_ID = int(config["guildId"])  # This is still available if needed elsewhere
OMDB_API_KEY = config["omdbApiKey"]
PREFIX = config["prefix"]
PLEX_CONFIG = config.get("plex", {})
PLEX_URL = PLEX_CONFIG.get("url")
PLEX_TOKEN = PLEX_CONFIG.get("token")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")


def _plex_headers():
    client_identifier = PLEX_CONFIG.get("clientIdentifier") or os.environ.get("PLEX_CLIENT_IDENTIFIER")
    if not client_identifier:
        client_identifier = str(uuid.UUID(int=uuid.getnode()))

    return {
        "X-Plex-Product": "LetMeWatchThis",
        "X-Plex-Version": "1.0",
        "X-Plex-Device": "DiscordBot",
        "X-Plex-Platform": "Python",
        "X-Plex-Client-Identifier": client_identifier,
    }

async def fetch_json(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json()


async def verify_plex_connection():
    if not PLEX_URL or not PLEX_TOKEN:
        logging.info("Skipping Plex connection test; missing URL or token in config.")
        return False

    status_url = f"{PLEX_URL.rstrip('/')}/status/sessions"
    params = {"X-Plex-Token": PLEX_TOKEN}
    timeout = aiohttp.ClientTimeout(total=10)

    headers = _plex_headers()

    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(status_url, params=params, headers=headers) as response:
                if response.status == 200:
                    logging.info("Plex connection verified at %s", status_url)
                    return True

                response_text = await response.text()
                logging.warning(
                    "Plex connection check returned status %s at %s: %s",
                    response.status,
                    status_url,
                    response_text[:200],
                )
                return False
    except Exception:
        logging.exception("Failed to connect to Plex at %s", status_url)
        return False

async def get_streaming_links(imdb_id, title, media_type):
    """Search Fmovies using IMDb ID for movies, and fuzzy matching for TV shows."""

    def is_valid_href(href: str, expected_media_type: str) -> bool:
        if not href:
            return False

        movie_paths = ("/movie/", "/movies/")
        tv_paths = ("/tv/",)

        if expected_media_type == "movie":
            return any(path in href for path in movie_paths)
        if expected_media_type == "series" or expected_media_type == "tv":
            return any(path in href for path in tv_paths)

        return True

    async def search_fmovies(query, expected_media_type):
        browser = None
        encoded_query = urllib.parse.quote_plus(query)
        search_url = f"https://en.fmovies24-to.com/search?q={encoded_query}"
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(search_url, timeout=60000)
                await page.wait_for_selector("div.germ.p-card > div > a.poster", timeout=20000)

                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")

                results = []
                cards = soup.select("div.germ.p-card > div")
                for card in cards:
                    link = card.select_one("a.poster") or card.select_one("a")
                    if not link:
                        continue

                    href = link.get("href")
                    title_attr = None

                    img = link.find("img")
                    if img:
                        title_attr = img.get("alt")

                    if not title_attr:
                        title_attr = link.get("title") or link.get_text(strip=True)

                    if title_attr and href and is_valid_href(href, expected_media_type):
                        results.append((title_attr, href))

                return results
        except PlaywrightTimeoutError:
            logging.error("Fmovies search timed out while waiting for results.")
            return []
        except Exception:
            logging.exception("Unexpected error while searching Fmovies")
            return []
        finally:
            if browser:
                await browser.close()

    # 1st Attempt: Use IMDb ID if it's a movie
    if media_type == "movie":
        fmovies_results = await search_fmovies(imdb_id, media_type)
        if fmovies_results:
            return [f"[{title}](https://en.fmovies24-to.com{fmovies_results[0][1]})"]

    # 2nd Attempt: Use fuzzy matching for TV shows
    fmovies_results = await search_fmovies(title, media_type)
    if not fmovies_results:
        return ["No streaming links found. Fmovies may be unavailable right now."]

    match_threshold = 75
    matched_links = []
    for result_title, href in fmovies_results:
        similarity = fuzz.token_set_ratio(title.lower(), result_title.lower())
        if similarity >= match_threshold:
            full_link = f"https://en.fmovies24-to.com{href}"
            matched_links.append(f"[{result_title}]({full_link})")

    if matched_links:
        links_string = "\n".join(matched_links[:3])  # Show only top 3 links
        if len(links_string) > 1024:
            return ["Too many links, try searching manually on Fmovies."]
        return [links_string]

    return ["No streaming links found."]

@bot.event
async def on_ready():
    # Global sync – note that global commands may take some time to appear
    await bot.tree.sync()
    plex_verified = await verify_plex_connection()
    if plex_verified:
        logging.info("Plex connection is available; Plex results should be reachable.")
    else:
        logging.warning("Plex connection could not be verified; Plex results may be unavailable.")
    print(f"Logged in as {bot.user}")

@bot.tree.command(name="watch", description="Search OMDb for movies or series")
@app_commands.describe(title="Movie or series title to search")
async def watch(interaction: Interaction, title: str):
    await interaction.response.defer()

    search_url = f"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&s={title}"
    search_results = await fetch_json(search_url)

    if search_results.get("Response") == "False":
        await interaction.followup.send("No results found.")
        return

    options = []
    seen_values = set()
    for item in search_results["Search"]:
        omdb_title = item.get("Title")
        media_type = item.get("Type")
        imdb_id = item.get("imdbID")

        if not omdb_title or not media_type or not imdb_id:
            logging.warning("Skipping search result missing required fields: %s", item)
            continue

        normalized_media_type = media_type.lower()
        option_value = f"{imdb_id}|{normalized_media_type}"

        if option_value in seen_values:
            logging.info("Skipping duplicate select option for %s (%s)", omdb_title, option_value)
            continue

        seen_values.add(option_value)
        options.append(discord.SelectOption(
            label=f"{omdb_title} ({item.get('Year', 'N/A')}) [{normalized_media_type.capitalize()}]",
            value=option_value
        ))

        if len(options) >= 25:
            logging.info("Limiting select menu to 25 options")
            break

    if not options:
        await interaction.followup.send("No valid results found to display.")
        return

    select = discord.ui.Select(placeholder="Select a movie or TV show", options=options)

    async def select_callback(select_interaction: Interaction):
        await select_interaction.response.defer()
        try:
            imdb_id, media_type = select_interaction.data["values"][0].split("|")
            details_url = f"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&i={imdb_id}&plot=short"
            details = await fetch_json(details_url)

            embed = discord.Embed(title=details.get("Title", "Unknown title"), description=details.get("Plot", "No plot available."), color=discord.Color.blue())
            embed.set_thumbnail(url=details.get("Poster"))
            embed.add_field(name="Year", value=details.get("Year", "N/A"))
            embed.add_field(name="IMDb Rating", value=details.get("imdbRating", "N/A"))
            embed.add_field(name="Type", value=media_type.capitalize())

            embed.add_field(name="Streaming Links", value="Fetching streaming links...", inline=False)

            message = await select_interaction.edit_original_response(embed=embed, view=None)

            async def update_streaming_links_message():
                try:
                    streaming_links = await get_streaming_links(imdb_id, details.get("Title", ""), media_type)
                    streaming_links_text = "\n".join(streaming_links)
                    if len(streaming_links_text) > 1024:
                        streaming_links_text = "Too many links, try searching manually on Fmovies."

                    updated_embed = embed.copy()
                    updated_embed.set_field_at(3, name="Streaming Links", value=streaming_links_text or "No streaming links found.", inline=False)
                    await message.edit(embed=updated_embed)
                except Exception:
                    logging.exception("Error updating streaming links")
                    fallback_embed = embed.copy()
                    fallback_embed.set_field_at(3, name="Streaming Links", value="Sorry, something went wrong while fetching streaming links.", inline=False)
                    await message.edit(embed=fallback_embed)

            asyncio.create_task(update_streaming_links_message())
        except Exception:
            logging.exception("Error handling selection callback")
            await select_interaction.edit_original_response(content="Sorry, something went wrong while fetching streaming links.", view=None)

    select.callback = select_callback
    view = discord.ui.View()
    view.add_item(select)
    await interaction.followup.send("Select a title:", view=view)

bot.run(TOKEN)
