import discord
import feedparser
import requests
from bs4 import BeautifulSoup
import asyncio

TOKEN = "SEU_TOKEN_AQUI"
CHANNEL_ID = 123456789012345678  # id do canal

RSS_URL = "https://www.gamespot.com/feeds/news/"

intents = discord.Intents.default()
client = discord.Client(intents=intents)

def get_image_from_article(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        og = soup.find("meta", property="og:image")
        if og:
            return og["content"]
    except:
        return None

def clean_html(text):
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text()

async def post_news():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)
    posted = set()

    while True:
        feed = feedparser.parse(RSS_URL)

        for entry in feed.entries[:5]:
            if entry.link in posted:
                continue

            title = entry.title
            description = clean_html(entry.summary)
            link = entry.link
            image_url = get_image_from_article(link)

            embed = discord.Embed(
                title=title,
                description=description[:300] + "...",
                url=link,
                color=0x5865F2
            )

            if image_url:
                embed.set_image(url=image_url)

            await channel.send(embed=embed)
            posted.add(entry.link)

        await asyncio.sleep(900)  # 15 minutos

@client.event
async def on_ready():
    print("Bot online:", client.user)
    client.loop.create_task(post_news())

client.run(TOKEN)
