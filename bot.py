import os
import json
import logging
import urllib.parse

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

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

logging.basicConfig(level=logging.INFO)

async def fetch_json(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json()

async def get_streaming_links(imdb_id, title, media_type):
    """Search Fmovies using IMDb ID for movies, and fuzzy matching for TV shows."""

    async def search_fmovies(query):
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

                    if title_attr and href:
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
        fmovies_results = await search_fmovies(imdb_id)
        if fmovies_results:
            return [f"[{title}](https://en.fmovies24-to.com{fmovies_results[0][1]})"]

    # 2nd Attempt: Use fuzzy matching for TV shows
    fmovies_results = await search_fmovies(title)
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
    for item in search_results["Search"]:
        omdb_title = item["Title"]
        media_type = item["Type"]
        imdb_id = item["imdbID"]
        options.append(discord.SelectOption(
            label=f"{omdb_title} ({item['Year']}) [{media_type.capitalize()}]",
            value=f"{imdb_id}|{media_type}"
        ))

    if len(options) > 20:
        options = options[:20]

    select = discord.ui.Select(placeholder="Select a movie or TV show", options=options)

    async def select_callback(select_interaction: Interaction):
        await select_interaction.response.defer()
        try:
            imdb_id, media_type = select_interaction.data["values"][0].split("|")
            details_url = f"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&i={imdb_id}&plot=short"
            details = await fetch_json(details_url)
            streaming_links = await get_streaming_links(imdb_id, details.get("Title", ""), media_type)

            embed = discord.Embed(title=details.get("Title", "Unknown title"), description=details.get("Plot", "No plot available."), color=discord.Color.blue())
            embed.set_thumbnail(url=details.get("Poster"))
            embed.add_field(name="Year", value=details.get("Year", "N/A"))
            embed.add_field(name="IMDb Rating", value=details.get("imdbRating", "N/A"))
            embed.add_field(name="Type", value=media_type.capitalize())

            streaming_links_text = "\n".join(streaming_links)
            if len(streaming_links_text) > 1024:
                streaming_links_text = "Too many links, try searching manually on Fmovies."

            embed.add_field(name="Streaming Links", value=streaming_links_text or "No streaming links found.", inline=False)

            await select_interaction.edit_original_response(embed=embed, view=None)
        except Exception:
            logging.exception("Error handling selection callback")
            await select_interaction.edit_original_response(content="Sorry, something went wrong while fetching streaming links.", view=None)

    select.callback = select_callback
    view = discord.ui.View()
    view.add_item(select)
    await interaction.followup.send("Select a title:", view=view)

bot.run(TOKEN)
