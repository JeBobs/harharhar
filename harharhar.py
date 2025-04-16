import discord
import aiohttp
import asyncio
import os
import shutil
import sys
import json
import yaml

CONFIG_FILE = "private/config.yaml"
TEMPLATE_FILE = "private/config.template.yaml"
CHARACTERS_FILE = "private/characters.yaml"
CONTEXTS_DIR = "private/contexts"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        if os.path.exists(TEMPLATE_FILE):
            shutil.copy(TEMPLATE_FILE, CONFIG_FILE)
            print(f"No config found. A new one has been created at '{CONFIG_FILE}'.")
            print("Please edit it with your real settings, then restart the bot.")
            sys.exit(0)
        else:
            print(f"Template '{TEMPLATE_FILE}' not found. Cannot create config.")
            sys.exit(1)

    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f)

def load_characters(filename=CHARACTERS_FILE):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return yaml.safe_load(f) or {}
    return {}

def save_characters(characters, filename=CHARACTERS_FILE):
    with open(filename, "w") as f:
        yaml.safe_dump(characters, f)

config = load_config()

# BOT_TOKEN is used at startup and cannot be changed at runtime!!
BOT_TOKEN = config["BOT_TOKEN"]
TARGET_CHANNEL_ID = config["TARGET_CHANNEL_ID"]
CHAT_COMPLETIONS_ENDPOINT = config["CHAT_COMPLETIONS_ENDPOINT"]
SUPPORTED_MODELS = config["SUPPORTED_MODELS"]
DEFAULT_MODEL = config["DEFAULT_MODEL"]
API_TIMEOUT = config.get("API_TIMEOUT", 30)
ERROR_500_MESSAGE = config.get("ERROR_500_MESSAGE",
    "Wait a second everyone, please hold your messages while I think...")
RETRY_DELAY = config.get("RETRY_DELAY", 5)

if not os.path.exists(CONTEXTS_DIR):
    os.makedirs(CONTEXTS_DIR)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# Global dictionaries to store conversation history and current model per channel.
conversation_history = {}
channel_model = {}  # Maps channel id to its active model
channel_character = {}  # maps channel_id -> character_name

def save_context(channel_id, context_name, conversation, character):
    filename = os.path.join(CONTEXTS_DIR, f"{context_name}.yaml")
    data = {
        "channel_id": channel_id,
        "character": character,
        "conversation": conversation
    }
    with open(filename, "w") as f:
        yaml.safe_dump(data, f)

def load_context(context_name):
    filename = os.path.join(CONTEXTS_DIR, f"{context_name}.yaml")
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return yaml.safe_load(f)
    return None

async def fetch_response(messages, model, temperature=0.7):
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(CHAT_COMPLETIONS_ENDPOINT, json=payload, headers=headers) as resp:
            text = await resp.text()  # Retrieve the response text for fallback purposes.
            try:
                data = await resp.json(content_type=None)
            except (aiohttp.ContentTypeError, json.JSONDecodeError):
                try:
                    decoder = json.JSONDecoder()
                    data, _ = decoder.raw_decode(text)
                except Exception:
                    return text.strip().replace("<|eot_id|>", "").replace("</s>", "").strip()
            # Check if the decoded data is a dict; if not, just return it as text.
            if not isinstance(data, dict):
                return str(data).strip().replace("<|eot_id|>", "").replace("</s>", "").strip()
            try:
                reply = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                reply = ""
            return reply.replace("<|eot_id|>", "").replace("</s>", "").strip()

def split_message(message, limit=2000):
    return [message[i:i+limit] for i in range(0, len(message), limit)]

@client.event
async def on_message(message):
    global TARGET_CHANNEL_ID, CHAT_COMPLETIONS_ENDPOINT, SUPPORTED_MODELS, DEFAULT_MODEL, API_TIMEOUT, ERROR_500_MESSAGE, RETRY_DELAY

    if message.channel.id != TARGET_CHANNEL_ID or message.author == client.user:
        return

    channel_id = message.channel.id
    if channel_id not in conversation_history:
        conversation_history[channel_id] = []
    if channel_id not in channel_model:
        channel_model[channel_id] = DEFAULT_MODEL

    content = message.content.strip()

    # Command: !reloadconfig – reloads the config from the YAML file.
    if content.lower() == "!reloadconfig":
        try:
            new_config = load_config()
            TARGET_CHANNEL_ID = new_config["TARGET_CHANNEL_ID"]
            CHAT_COMPLETIONS_ENDPOINT = new_config["CHAT_COMPLETIONS_ENDPOINT"]
            SUPPORTED_MODELS = new_config["SUPPORTED_MODELS"]
            DEFAULT_MODEL = new_config["DEFAULT_MODEL"]
            API_TIMEOUT = new_config.get("API_TIMEOUT", 30)
            ERROR_500_MESSAGE = config.get("ERROR_500_MESSAGE",
                            "Wait a second everyone, please hold your messages while I think...")
            RETRY_DELAY = config.get("RETRY_DELAY", 5)
            await message.channel.send("Configuration reloaded successfully!")
        except Exception as e:
            await message.channel.send(f"Failed to reload config: {str(e)}")
        return

    # Command: !listmodels – list available models.
    if content.lower() == "!listmodels":
        model_list = "\n".join(SUPPORTED_MODELS)
        await message.channel.send(f"**Available models:**\n{model_list}")
        return

    # Command: !setmodel <model> – change the active model.
    if content.lower().startswith("!setmodel "):
        parts = content.split(" ", 1)
        if len(parts) > 1:
            selected_model = parts[1].strip()
            if selected_model in SUPPORTED_MODELS:
                channel_model[channel_id] = selected_model
                await message.channel.send(f"Model set to: **{selected_model}**")
            else:
                await message.channel.send(f"Model '{selected_model}' not supported. Use !listmodels for available options.")
        return

    # Command: !reset – clear the conversation context.
    if content.lower() == "!reset":
        conversation_history[channel_id] = []
        await message.channel.send("Conversation context reset.")
        return

    # Command: !savecontext <name> – save the current conversation context and active character.
    if content.lower().startswith("!savecontext "):
        parts = content.split(" ", 1)
        if len(parts) > 1:
            context_name = parts[1].strip()
            filename = os.path.join(CONTEXTS_DIR, f"{context_name}.yaml")
            if os.path.exists(filename):
                await message.channel.send(f"Context '{context_name}' already exists. Type 'yes' to overwrite within 15 seconds.")
                def check(m):
                    return m.author == message.author and m.channel == message.channel and m.content.lower() == "yes"
                try:
                    await client.wait_for("message", timeout=15, check=check)
                except asyncio.TimeoutError:
                    await message.channel.send("Save canceled due to timeout.")
                    return
            try:
                current_character = channel_model[channel_id]  # The active character/model used
                save_context(channel_id, context_name, conversation_history[channel_id], current_character)
                await message.channel.send(f"Context saved as '{context_name}'.")
            except Exception as e:
                await message.channel.send(f"Error saving context: {str(e)}")
        return

    # Command: !loadcontext <name> – load a saved conversation context.
    if content.lower().startswith("!loadcontext "):
        parts = content.split(" ", 1)
        if len(parts) > 1:
            context_name = parts[1].strip()
            loaded_data = load_context(context_name)
            if loaded_data is not None:
                # Optionally verify that the stored channel id matches the current channel.
                saved_channel = loaded_data.get("channel_id")
                if saved_channel != channel_id:
                    await message.channel.send("Warning: This context was saved in a different channel. Proceeding to load anyway.")
                conversation_history[channel_id] = loaded_data.get("conversation", [])
                if "character" in loaded_data:
                    channel_model[channel_id] = loaded_data["character"]
                await message.channel.send(f"Context loaded from '{context_name}'.")
            else:
                await message.channel.send(f"Context '{context_name}' not found.")
        return

    # ----- Character management commands -----

    # Command: !newcharacter <name> <model> <prompt>
    if content.lower().startswith("!newcharacter "):
        # Split into four parts: command, name, model, and prompt (rest of the line).
        parts = content.split(" ", 3)
        if len(parts) < 4:
            await message.channel.send("Usage: !newcharacter <name> <model> <prompt>")
            return
        char_name = parts[1].strip()
        char_model = parts[2].strip()
        char_prompt = parts[3].strip()
        if char_model not in SUPPORTED_MODELS:
            await message.channel.send(f"Model '{char_model}' not supported. Use !listmodels for available options.")
            return
        characters = load_characters()
        characters[char_name] = {"model": char_model, "prompt": char_prompt}
        save_characters(characters)
        await message.channel.send(f"Character '{char_name}' created.")
        return

    # Command: !deletecharacter <name>
    if content.lower().startswith("!deletecharacter "):
        parts = content.split(" ", 1)
        if len(parts) < 2:
            await message.channel.send("Usage: !deletecharacter <name>")
            return
        char_name = parts[1].strip()
        characters = load_characters()
        if char_name in characters:
            del characters[char_name]
            save_characters(characters)
            await message.channel.send(f"Character '{char_name}' deleted.")
        else:
            await message.channel.send(f"Character '{char_name}' not found.")
        return

    # Command: !loadcharacter <name>
    if content.lower().startswith("!loadcharacter "):
        parts = content.split(" ", 1)
        if len(parts) < 2:
            await message.channel.send("Usage: !loadcharacter <name>")
            return
        char_name = parts[1].strip()
        characters = load_characters()
        if char_name in characters:
            char_data = characters[char_name]
            # Reset conversation and load the system message.
            conversation_history[channel_id] = [{"role": "system", "content": char_data["prompt"]}]
            # Set the channel's active model to the character's model.
            channel_model[channel_id] = char_data["model"]
            channel_character[channel_id] = char_name
            await message.channel.send(f"Character '{char_name}' loaded. Chat reset with system prompt.")
        else:
            await message.channel.send(f"Character '{char_name}' not found.")
        return
    
    # Command: !listcharacters – list available characters (name and model only).
    if content.lower() == "!listcharacters":
        characters = load_characters()
        if not characters:
            await message.channel.send("No characters available.")
        else:
            lines = [f"{name}: {data['model']}" for name, data in characters.items()]
            await message.channel.send("**Available Characters:**\n" + "\n".join(lines))
        return

    # ----- End of character management commands -----

        # Command: !help – list all commands and their usage
    if content.lower().startswith("!help"):
        help_text = """
**Available Commands**
• `!help`  
  Display this help message.

• `!reloadconfig`  
  Reloads bot settings from the config file.

• `!listmodels`  
  Show all supported models.

• `!setmodel <model>`  
  Switch the current channel’s model.  

• `!reset`  
  Clear the current conversation history.

• `!savecontext <name>`  
  Save this channel’s conversation (plus active character) under `<name>`.

• `!loadcontext <name>`  
  Restore a previously saved conversation named `<name>`.

• `!newcharacter <name> <model> <prompt>`  
  Create a new character using `<model>` and initial character `<prompt>`.

• `!deletecharacter <name>`  
  Remove the character `<name>` from the character list.

• `!loadcharacter <name>`  
  Reset chat and load the character `<name>` (initial character prompt + model).

• `!listcharacters`  
  List all saved characters and their models.
"""
        await message.channel.send(help_text)
        return

    # Check for image attachments and add a note.
    image_extensions = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
    if message.attachments and any(att.filename.lower().endswith(image_extensions) for att in message.attachments):
        content += "\n[User attached an image]"

    # Build the user's identity (username, nickname if available, and Discord user ID).
    username = message.author.name
    user_id = message.author.id
    nickname = message.author.nick if getattr(message.author, "nick", None) else None
    if nickname:
        user_identity = f"{username} ({nickname}) [ID: {user_id}]"
    else:
        user_identity = f"{username} [ID: {user_id}]"

    # If this is a reply, include the original message context.
    if message.reference is not None and message.reference.resolved is not None:
        ref_msg = message.reference.resolved
        if isinstance(ref_msg, discord.Message):
            ref_username = ref_msg.author.name
            ref_content = ref_msg.content.strip()
            content = f"(in reply to {ref_username}: {ref_content})\n{content}"

    # Final message to the AI includes the user identity.
    user_message = f"{user_identity}: {content}"
    conversation_history[channel_id].append({"role": "user", "content": user_message})
    current_model = channel_model.get(channel_id, DEFAULT_MODEL)

    # Send a typing indicator and try to get a response.
    try:
        async with message.channel.typing():
            response = await asyncio.wait_for(
                fetch_response(conversation_history[channel_id], current_model),
                timeout=API_TIMEOUT
            )
    except asyncio.TimeoutError:
        response = "The API is taking too long to respond."
    except Exception as e:
        response = f"An error occurred: {str(e)}"

    # Check if the response is just "500" and, if so, buffer the message and retry.
    if response.strip() == "500":
        # load all characters to see if this one has an override
        characters = load_characters()
        char_name = channel_character.get(channel_id)
        if char_name and characters.get(char_name, {}).get("error_500_message"):
            err_msg = characters[char_name]["error_500_message"]
        else:
            err_msg = ERROR_500_MESSAGE
    
        await message.channel.send(err_msg)
        await asyncio.sleep(5)
        try:
            async with message.channel.typing():
                response = await asyncio.wait_for(
                    fetch_response(conversation_history[channel_id], current_model),
                    timeout=API_TIMEOUT
                )
        except asyncio.TimeoutError:
            response = "The API is taking too long to respond (on retry)."
        except Exception as e:
            response = f"An error occurred on retry: {str(e)}"
    
    if response:
        conversation_history[channel_id].append({"role": "assistant", "content": response})
        for chunk in split_message(response):
            await message.channel.send(chunk)
    else:
        await message.channel.send("Received empty response from API.")

client.run(BOT_TOKEN)