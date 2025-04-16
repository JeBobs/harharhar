# Har Har Har

Yet another Discord chat bot that lets you create “characters” (system prompts + models), leveraging the ChatGPT API (or equivalent, such as [exo](https://github.com/exo-explore/exo))

---

## Features

- **Contextual Chat**  
  Maintains a rolling chat history per channel so the AI “remembers” what was said.

- **Typing Indicator**  
  Shows “Bot is typing…” while waiting for the AI’s response.

- **Model Management**  
  - `!listmodels` — list supported models  
  - `!setmodel <model>` — switch active model

- **Context Save & Load**  
  - `!savecontext <name>` — snapshot current chat + active character  
  - `!loadcontext <name>` — restore a named snapshot  
  - `!reset` — clear conversation history

- **Character System**  
  Store reusable “characters” (system prompts + model):  
  - `!newcharacter <name> <model> <prompt>` — create a character  
  - `!deletecharacter <name>` — remove a character  
  - `!loadcharacter <name>` — reset chat with that character’s prompt & model  
  - `!listcharacters` — list all saved characters

- **Image Acknowledgement**  
  If a user attaches an image, the bot notes `[User attached an image]` in the AI prompt. (Image recognition model support coming soon)

---

## Setup Guide

```bash
git clone https://github.com/your‑username/harharhar.git
cd harharhar
python3 -m venv venv
source venv/bin/activate
# or `source venv/bin/activate.fish` if you use Fish shell
pip install -r requirements.txt
cp ./config.template.yaml ./private/config.yaml
```

Then, configure `private/config.yaml` with your Discord bot token, desired channel, API endpoint, and other settings you may want to adjust.

## Character Creation

Users can create characters through Discord, but you can also create characters by defining their characteristics in `private/characters.yaml`. For example,

```yaml
Sherlock:
  model: "llama-3.1-8b"
  prompt: "You are Sherlock Holmes, extremely observant detective..."
  error_500_message: "Bear with me, I'm deducing..."
```