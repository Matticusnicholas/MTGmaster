import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CHROMA_DIR = DATA_DIR / "chroma"
STRATEGY_DIR = DATA_DIR / "strategy"

# Ollama
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("MTGMASTER_EMBED_MODEL", "nomic-embed-text")
DEFAULT_CHAT_MODEL = os.environ.get("MTGMASTER_CHAT_MODEL", "llama3.1:8b")

# Data sources
SCRYFALL_BULK_INDEX = "https://api.scryfall.com/bulk-data"
WOTC_RULES_INFO_PAGE = "https://magic.wizards.com/en/rules"

# Chroma collection names
CHROMA_CARDS = "mtg_cards"
CHROMA_RULES = "mtg_rules"
CHROMA_STRATEGY = "mtg_strategy"

# Server
WEB_HOST = os.environ.get("MTGMASTER_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("MTGMASTER_PORT", "8765"))
