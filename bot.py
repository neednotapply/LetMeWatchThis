import os
import json
import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed, ui
import aiohttp
from playwright.async_api import async_playwright
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

async def fetch_json(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json()

async def get_streaming_links(imdb_id, title, media_type):
    """Search Primewire using IMDb ID for movies, and fuzzy matching for TV shows."""
    async def search_primewire(query):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto("https://www.primewire.tf", timeout=60000)
            await page.fill('input#search_term', query)
            await page.click('button.btn[type="submit"]')
            await page.wait_for_load_state('networkidle')
            content = await page.content()
            await browser.close()

            soup = BeautifulSoup(content, "html.parser")
            primewire_results = []
            for result in soup.select('.index_item a'):
                href = result.get('href')
                result_title = result.get('title') or result.text.strip()
                if href and result_title and "genre[]" not in href:
                    primewire_results.append((result_title, href))
            return primewire_results

    # 1st Attempt: Use IMDb ID if it's a movie
    if media_type == "movie":
        primewire_results = await search_primewire(imdb_id)
        if primewire_results:
            return [f"[{title}](https://www.primewire.tf{primewire_results[0][1]})"]

    # 2nd Attempt: Use fuzzy matching for TV shows
    primewire_results = await search_primewire(title)
    if not primewire_results:
        return ["No streaming links found."]

    match_threshold = 75
    matched_links = []
    for result_title, href in primewire_results:
        similarity = fuzz.token_set_ratio(title.lower(), result_title.lower())
        if similarity >= match_threshold:
            full_link = f"https://www.primewire.tf{href}"
            matched_links.append(f"[{result_title}]({full_link})")

    if matched_links:
        links_string = "\n".join(matched_links[:3])  # Show only top 3 links
        if len(links_string) > 1024:
            return ["Too many links, try searching manually on Primewire."]
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
        imdb_id, media_type = select_interaction.data["values"][0].split("|")
        details_url = f"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&i={imdb_id}&plot=short"
        details = await fetch_json(details_url)
        streaming_links = await get_streaming_links(imdb_id, details["Title"], media_type)

        embed = discord.Embed(title=details["Title"], description=details["Plot"], color=discord.Color.blue())
        embed.set_thumbnail(url=details.get("Poster"))
        embed.add_field(name="Year", value=details["Year"])
        embed.add_field(name="IMDb Rating", value=details["imdbRating"])
        embed.add_field(name="Type", value=media_type.capitalize())

        streaming_links_text = "\n".join(streaming_links)
        if len(streaming_links_text) > 1024:
            streaming_links_text = "Too many links, try searching manually on Primewire."

        embed.add_field(name="Streaming Links", value=streaming_links_text, inline=False)

        await select_interaction.edit_original_response(embed=embed, view=None)

    select.callback = select_callback
    view = discord.ui.View()
    view.add_item(select)
    await interaction.followup.send("Select a title:", view=view)

bot.run(TOKEN)
