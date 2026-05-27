# PokéVault — Pokémon Card Inventory

A beautiful Flask + SQLite3 web app to track your Pokémon card collection, powered by the **Pokémon TCG API** for live card search with real images and market prices.

## Quick Start

```bash
# 1. Install dependencies
pip install flask

# 2. (Optional but recommended) Set your free API key for higher rate limits
#    Get one free at: https://dev.pokemontcg.io
export POKEMONTCG_API_KEY="your-key-here"

# 3. Run
python app.py
```

Open **http://localhost:5000**

## How to Add Cards

1. Click **"+ Add Card"**
2. Type any Pokémon name — live results appear instantly with real card art
3. Click the card you want
4. Choose condition & quantity
5. Hit **"Add to Vault"** — market price is auto-filled from TCGPlayer data

## Features

- **Live card search** via pokemontcg.io API — real images, set info, HP, subtypes
- **Market prices** pulled automatically from TCGPlayer
- **Visual card gallery** with holographic hover effects and 3D tilt
- **Quantity counter** — hover a card to increment/decrement
- **Filter & search** your collection by name, type, or rarity
- **SQLite3 database** — all data stored locally in `pokemon_inventory.db`
- **Duplicate detection** — adding the same card+condition again just increments quantity

## Project Structure

```
pokemon-inventory/
├── app.py                   # Flask app + SQLite3 + API proxy
├── requirements.txt
├── pokemon_inventory.db     # Auto-created on first run
├── templates/index.html     # Main UI
└── static/
    ├── css/style.css
    └── js/main.js
```

## API Key (optional)

Without a key, the API allows ~1000 requests/day. With a free key you get much higher limits.
Sign up at https://dev.pokemontcg.io — it's free.
