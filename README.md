# MTGMaster

A local web app that pairs **Ollama** with a **RAG database of every Magic: The Gathering card and the entire Comprehensive Rules** so a local LLM can answer MTG questions without hallucinating card text or rules.

## What v1.0 does

- **Auto-starts Ollama** when the app launches (spawns `ollama serve` if it isn't already running).
- **Picks any locally installed Ollama model** from a dropdown in the UI.
- Retrieval-Augmented Generation over three corpora, all embedded and stored locally:
  - **Cards** — every unique Magic card from the [Scryfall `oracle_cards` bulk data](https://scryfall.com/docs/api/bulk-data) (~30k cards), with mana cost, type line, oracle text, P/T, keywords, and per-format legalities (including current Standard).
  - **Comprehensive Rules** — the full WotC rulebook, parsed and chunked by rule number (e.g. `702.21a`).
  - **Strategy / metagame** — drop your own Markdown notes into `data/strategy/` and they get embedded too.
- A strict **system prompt** that forces the LLM to ground every claim in retrieved context, quote rule numbers and oracle text verbatim, and refuse to invent card text.

## Why this exists

LLMs hallucinate badly on Magic — they confidently make up oracle text, mana costs, and rule numbers. The fix is to never let the model reason from its weights alone: every answer is grounded in retrieved card text and rule passages, with citations shown next to the response.

## Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) installed and on your `PATH`
- A chat model and an embedding model pulled locally:

```
ollama pull llama3.1:8b          # or any chat model you like
ollama pull nomic-embed-text     # required for embeddings
```

## Setup

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
chmod +x scripts/*.sh
```

## Ingest the knowledge base

This downloads Scryfall's oracle bulk data (~100 MB) and the latest Comprehensive Rules, then embeds everything into a local Chroma DB at `data/chroma/`.

```
./scripts/ingest.sh --all                          # everything
./scripts/ingest.sh --rules                        # rules only
./scripts/ingest.sh --cards --standard-only        # Standard-legal cards only (fast)
./scripts/ingest.sh --cards --limit 2000           # smoke test
./scripts/ingest.sh --strategy                     # any .md / .txt under data/strategy/
```

Embedding all ~30k cards on a CPU takes a while. Start with `--standard-only` for a fast first run, then expand later.

## Run

```
./scripts/run.sh
# open http://127.0.0.1:8765
```

The backend will start `ollama serve` for you if it isn't already running.

## Data sources

- **Cards**: [Scryfall bulk data](https://scryfall.com/docs/api/bulk-data) — `oracle_cards` endpoint. One entry per unique card, with full oracle text and per-format legalities.
- **Rules**: [Magic Comprehensive Rules](https://magic.wizards.com/en/rules) — the official txt file from Wizards of the Coast. The ingester scrapes the rules page for the latest version.
- **Strategy**: Bring your own. Drop `.md`/`.txt` files into `data/strategy/`.

## Project layout

```
backend/
  main.py            FastAPI app + lifespan that boots Ollama
  ollama_manager.py  Spawns and probes `ollama serve`, lists models
  rag.py             Chroma retrieval and context formatting
  ingest.py          Scryfall + Comp Rules + strategy ingestion
  prompts.py         System prompt with anti-hallucination rules
  config.py          Paths, model names, URLs
frontend/            Vanilla HTML/JS chat UI with model picker + citations
scripts/             run.sh, ingest.sh
data/                Generated: raw downloads + Chroma store
```

## Roadmap (post-1.0)

- Tournament metagame ingestion (mtgtop8 archetypes per format).
- Re-ranking with a small cross-encoder.
- Card image previews via Scryfall image URIs.
- Format-aware filters in the UI (e.g. "Standard only" toggle that filters retrieval by metadata).
- Tool calls so the model can look up specific cards by name when its retrieval misses.
