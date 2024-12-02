import discord
import os
import webserver
import requests
import random
import asyncio
from dotenv import load_dotenv
from discord.ext import commands, tasks
from discord import FFmpegPCMAudio
from datetime import datetime
import yt_dlp
from collections import deque
import re

# Carga del archivo .env
load_dotenv()

# Credenciales de Discord
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_NOTIFICATION_CHANNEL_ID = int(os.getenv("DISCORD_NOTIFICATION_CHANNEL_ID"))

# Credenciales de Twitch
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
TWITCH_CHANNEL_NAME = os.getenv("TWITCH_CHANNEL_NAME")

# Configuración de FFMPEG y yt-dlp
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0'
}

# IDs de los canales permitidos y usuarios permitidos
ALLOWED_CHANNELS = [746775897570410546, 1299496936382140426, 738501319748354108, 1111465812407103580]  # Reemplaza con tus IDs
ALLOWED_USERS = [303366133011185664, 209837114337132544, 218377427892568065]  # Reemplaza con tus IDs



# Configurar intents
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.voice_states = True  # Habilitar el manejo de canales de voz

# Crear el cliente del bot con comandos
bot = commands.Bot(command_prefix="!", intents=intents)

# Variable para almacenar el estado de transmisión
is_live = False



# ====================== TWITCH STREAM CHECK ======================

async def obtener_token_twitch():
    """Obtiene un nuevo token de acceso de Twitch."""
    url = "https://id.twitch.tv/oauth2/token"
    payload = {
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    response = requests.post(url, data=payload)
    if response.status_code == 200:
        data = response.json()
        return data["access_token"]
    else:
        print(f"Error al obtener el token de Twitch: {response.json()}")
        return None


async def check_twitch_live():
    """Verifica si el canal de Twitch está en vivo y envía una notificación en Discord."""
    global is_live
    await bot.wait_until_ready()

    # Obtener el token de acceso
    token = await obtener_token_twitch()
    if not token:
        print("No se pudo obtener el token de acceso.")
        return

    # URL de la API de Twitch para obtener información del stream
    url = f"https://api.twitch.tv/helix/streams?user_login={TWITCH_CHANNEL_NAME}"
    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}"
    }

    while not bot.is_closed():
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                # Si hay datos en la respuesta, el canal está en vivo
                if data["data"]:
                    if not is_live:  # Solo notificar si no lo hemos hecho ya
                        is_live = True
                        stream_info = data["data"][0]
                        title = stream_info["title"]
                        game_name = stream_info.get("game_name", "Desconocido")
                        stream_url = f"https://www.twitch.tv/{TWITCH_CHANNEL_NAME}"

                        # Enviar la notificación en Discord
                        canal = bot.get_channel(DISCORD_NOTIFICATION_CHANNEL_ID)
                        if canal:
                            await canal.send(
                                f"@everyone 🔴 **{TWITCH_CHANNEL_NAME} está en vivo ahora!**\n"
                                f"🎮 **Título:** {title}\n"
                                f"🕹️ **Jugando:** {game_name}\n"
                                f"📺 **Mira aquí:** {stream_url}"
                            )
                else:
                    if is_live:
                        is_live = False  # El canal dejó de transmitir
            else:
                print(f"Error al consultar Twitch: {response.status_code} - {response.json()}")
        except Exception as e:
            print(f"Error durante la verificación de Twitch: {e}")

        # Esperar 60 segundos antes de volver a consultar
        await asyncio.sleep(60)


# ====================== VOICE COMMANDS ======================

global music_queue, is_playing
# Cola de reproducción (una cola compartida para almacenar las canciones)
music_queue = deque()
# Variable para manejar si se está reproduciendo una canción
is_playing = False

def search_youtube(query):
    """Busca una canción en YouTube utilizando yt-dlp."""
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        try:
            info = ydl.extract_info(query, download=False)
            if 'entries' in info:
                return info['entries'][0]
            return info
        except Exception as e:
            print(f"Error al buscar en YouTube: {e}")
            return None


async def play_next(ctx):
    global is_playing

    if music_queue:
        next_song = music_queue.popleft()
        url = next_song['url']
        title = next_song.get('title', 'Desconocido')

        # Reproducir la siguiente canción
        ctx.voice_client.play(
            FFmpegPCMAudio(url, **FFMPEG_OPTIONS), 
            after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
        )
        await ctx.send(f"▶️ Reproduciendo: {title}")
        is_playing = True
    else:
        is_playing = False
        await ctx.send("🎶 La lista de reproducción ha terminado.")


@bot.command(name="mPlay")
async def play(ctx, *, search: str):
    """Comando para agregar canciones a la cola y reproducirlas."""
    global is_playing
    # Verificar si el usuario está en un canal de voz
    if not ctx.author.voice:
        await ctx.send("❌ ¡Debes estar en un canal de voz para usar este comando!")
        return

    voice_channel = ctx.author.voice.channel

    # Conectarse al canal de voz si no está conectado
    if ctx.voice_client is None:
        await voice_channel.connect()

    voice_client = ctx.voice_client

    # Buscar la canción en YouTube
    info = search_youtube(search)
    if not info:
        await ctx.send("❌ No se pudo encontrar la canción. Intenta con otro nombre.")
        return

    url = info['url']
    title = info.get('title', 'Desconocido')

    # Agregar la canción a la cola
    music_queue.append(info)
    await ctx.send(f"✅ **{title}** se ha agregado a la lista de reproducción.")

    # Si no se está reproduciendo música, iniciar la reproducción
    if not is_playing:
        await play_next(ctx)


@bot.command(name="skip")
async def skip(ctx):
    """Comando para saltar a la siguiente canción."""
    # Verifica si el bot está conectado a un canal de voz y reproduciendo música
    if not ctx.voice_client:
        await ctx.send("❌ No estoy conectado a ningún canal de voz.")
        return

    if not is_playing:
        await ctx.send("❌ No se está reproduciendo ninguna canción actualmente.")
        return

    # Verifica si hay más canciones en la cola
    if not music_queue:
        await ctx.send("❌ No hay más canciones en la cola para saltar.")
        return

    # Detener la canción actual y pasar a la siguiente
    try:
        ctx.voice_client.stop()  # Detener la canción actual
        await play_next(ctx)     # Reproducir la siguiente canción
    except Exception as e:
        await ctx.send(f"❌ Ocurrió un error al intentar saltar la canción: {e}")


@bot.command(name="queue")
async def queue(ctx):
    if not music_queue:
        await ctx.send("🎶 La lista de reproducción está vacía.")
    else:
        queue_list = "\n".join(
            [f"**{i + 1}.** {song.get('title', 'Desconocido')}" for i, song in enumerate(music_queue)]
        )
        await ctx.send(f"🎵 **Lista de reproducción:**\n{queue_list}")


@bot.command(name="limpiar")
async def clear_queue(ctx):
    """Comando para limpiar la cola de reproducción."""
    global music_queue

    # Verifica si hay canciones en la cola
    if music_queue:
        music_queue.clear()  # Limpia la cola
        await ctx.send("✅ La lista de reproducción ha sido limpiada.")
    else:
        await ctx.send("🎶 La lista de reproducción ya está vacía.")


@bot.command(name="pause")
async def pause(ctx):
    """Comando para pausar la canción actual."""
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ La canción ha sido pausada.")
    else:
        await ctx.send("❌ No hay música reproduciéndose actualmente.")


@bot.command(name="resume")
async def resume(ctx):
    """Comando para reanudar la canción pausada."""
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ La canción ha sido reanudada.")
    else:
        await ctx.send("❌ No hay música pausada actualmente.")


@bot.command(name="stop")
async def stop(ctx):
    """Comando para detener la canción y desconectar al bot."""
    if ctx.voice_client:
        ctx.voice_client.stop()
        await ctx.voice_client.disconnect()
        await ctx.send("❌ La música ha sido detenida y me desconecté del canal.")
    else:
        await ctx.send("❌ No estoy conectado a ningún canal de voz.")


@bot.command(name="leave")
async def leave(ctx):
    """Comando para desconectarse del canal de voz."""
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("✅ Desconectado del canal de voz.")
    else:
        await ctx.send("❌ No estoy conectado a ningún canal de voz.")


@bot.command(name="musica")
async def music_commands(ctx):
    """Comando que muestra todos los comandos de música disponibles."""
    commands = """
    🎶 **Comandos de Música:**

    !mPlay [canción]  ➡️ **Reproduce una canción de YouTube**.
    !queue                  ➡️ **Muestra la lista de reproducción**.
    !skip                   ➡️ **Salta a la siguiente canción**.
    !limpiar                ➡️ **Limpia la lista de reproducción**.
    !leave                  ➡️ **Se va del canal de voz y limpia la lista**.
    !pause                  ➡️ **Pausa la canción actual**.
    !resume                 ➡️ **Reanuda la canción pausada**.
    !stop                   ➡️ **Detiene la música y desconecta al bot**.
    """
    await ctx.send(commands)


# ====================== EVENTS ======================


@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")
    bot.loop.create_task(check_twitch_live())  # Iniciar la verificación periódica


# Evento para manejar mensajes
@bot.event
async def on_message(message):
    # Evitar que el bot responda a sí mismo
    if message.author.bot:
        return

    # Comprobar si el mensaje es en un canal permitido
    if message.channel.id in ALLOWED_CHANNELS:
        content = message.content.lower()

        # Respuesta a palabras clave
        if "hola" in content:
            await message.channel.send("¿Qué haces loquita?")
        elif "adios" in content:
            await message.channel.send("¡Nos vemos luego, loquita!")

        # Buscar números específicos en el mensaje
        pattern = r'\b(4|11|13)([.,!?]|\s|$)'  # Coincide con 4, 11 o 13 aislados
        matches = re.findall(pattern, content)

        # Procesar cada coincidencia válida
        if matches:
            for match in matches:
                num = match[0]  # Captura el número
                if num == "4":
                    await message.channel.send("en 4 te puse, loquita.")
                elif num == "11":
                    await message.channel.send("11? Chupamelo entonces.")
                elif num == "13":
                    await message.channel.send("13? Dijiste 13... agarrame la que me crece.")


    # Procesar comandos del bot
    await bot.process_commands(message)


@bot.command(name="d20")
async def roll_d20(ctx):
    """Lanza un dado de 20 caras y devuelve un número junto con una frase temática."""
    roll = random.randint(1, 20)  # Genera un número entre 1 y 20

    # Definir frases según el resultado
    phrases = {
        1: "🎲 **1** - Una lástima, tenemos un fiambre en el pasillo 7. 💀",
        2: "🎲 **2** - Hay una torta y una pija. Te comiste las 2. ¡Qué desastre! 😵",
        3: "🎲 **3** - Tu intento fue mediocre, por no decir que mejor ni lo intentes... 😬",
        4: "🎲 **4** - Apenas logras evitar un desastre. Pero no esperes mucho inutil. 😅",
        5: "🎲 **5** - Bueno... al menos no fue un 1. 🤷‍♂️",
        6: "🎲 **6** - Podría ser peor, pero claramente tenes un dia de mierda. 😒",
        7: "🎲 **7** - Algo mejor, pero apenas destaca. 😐",
        8: "🎲 **8** - Un golpe decente, pero aún falta algo...como manos. 🤔",
        9: "🎲 **9** - Te acercas a la media(de tamaño), ¡ánimo! 🧐",
        10: "🎲 **10** - Justo en el medio, ni bueno ni malo. en tu ojete ⚖️",
        11: "🎲 **11** - Un golpe pasable, mientras mas me la mamas mas me crece. 😊",
        12: "🎲 **12** - Buen intento. 👍",
        13: "🎲 **13** - Nada mal, podrías ganarte unos aplausos. 👏",
        14: "🎲 **14** - ¡Buen trabajo! Vas mejorando. 🌟",
        15: "🎲 **15** - Impresionante, estás casi en la cima. ✨",
        16: "🎲 **16** - ¡Qué locura!. 💪",
        17: "🎲 **17** - Solta a la menor, digo que bien un 17!. 🥳",
        18: "🎲 **18** - ¡Una obra maestra Casi perfecto.! 🔥",
        19: "🎲 **19** - Increíble, casi un 20 un tipazo. 🦸‍♂️",
        20: "🎲 **20** - ¡CRÍTICO! ¡Que ojete! Sos toro 🏆"
    }

    # Obtener la frase correspondiente al resultado
    phrase = phrases.get(roll, "Algo salió mal... ¿Cómo lograste este resultado? 🤔")

    # Responder en el canal
    await ctx.send(phrase)


@bot.command(name="ayuda")
async def help_commands(ctx):
    """Lista todos los comandos disponibles."""
    commands = """
    🔧 **Comandos Generales:**
    !musica   ➡️ Muestra todos los comandos de música.
    !d20      ➡️ Lanza un dado de 20 caras con una frase.
    """
    await ctx.send(commands)


@tasks.loop(hours=24)
async def friday_reminder():
    """Envía un recordatorio todos los viernes."""
    now = datetime.now()
    if now.weekday() == 4:  # 4 representa viernes (lunes=0, domingo=6)
        channel = bot.get_channel(738501319748354108)  # Reemplaza TU_CANAL_ID con el ID del canal
        if channel:
            await channel.send("¿Qué día es hoy? Creo que es mejor preguntarle a https://x.com/EsViernesLokita")

@bot.event
async def on_ready():
    """Evento que se ejecuta cuando el bot está listo."""
    print(f"Bot conectado como {bot.user}")
    # Iniciar el recordatorio
    friday_reminder.start()



# Comando: Apagar el bot (solo para usuarios permitidos)
@bot.command()
async def apagar(ctx):
    if ctx.author.id in ALLOWED_USERS:
        await ctx.send("Parece que ya no me necesitan. ¡Adiós!")
        await bot.close()  # Cierra la conexión del bot
    else:
        await ctx.send("No tienes permiso para apagarme.")


# Comando: Twitch
@bot.command()
async def twitch(ctx):
    await ctx.send(f"¡Hola! Puedes visitar el canal de Twitch aquí: https://www.twitch.tv/{TWITCH_CHANNEL_NAME}")


# Comando: Status
@bot.command()
async def status(ctx):
    await ctx.send("Estoy funcionando perfectamente, gracias por preguntar.")

# Iniciar el bot y mantener activo.
webserver.keep_alive()
bot.run(DISCORD_TOKEN)
