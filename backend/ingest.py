import argparse
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import httpx
import ijson
from tqdm import tqdm

from .config import (
    CHROMA_CARDS,
    CHROMA_RULES,
    CHROMA_STRATEGY,
    EMBED_MODEL,
    OLLAMA_HOST,
    RAW_DIR,
    SCRYFALL_BULK_INDEX,
    STRATEGY_DIR,
    WOTC_RULES_INFO_PAGE,
)
from .rag import get_client, get_or_create

log = logging.getLogger(__name__)

UA = "MTGMaster/1.0 (+https://github.com/matticusnicholas/mtgmaster)"
SKIP_LAYOUTS = {"art_series", "token", "double_faced_token", "emblem"}

# Formats we explicitly designate. Order is preserved in the card text so
# the LLM sees Standard first.
FORMATS = (
    "standard",
    "pioneer",
    "modern",
    "legacy",
    "vintage",
    "commander",
    "pauper",
    "explorer",
    "historic",
    "brawl",
    "alchemy",
    "timeless",
    "oathbreaker",
)


def http_get_json(url: str) -> dict:
    with httpx.Client(
        timeout=60.0, follow_redirects=True, headers={"User-Agent": UA}
    ) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


def download_file(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream(
        "GET", url, follow_redirects=True, timeout=None, headers={"User-Agent": UA}
    ) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        with open(dest, "wb") as f, tqdm(
            total=total, unit="B", unit_scale=True, desc=dest.name
        ) as pbar:
            for chunk in r.iter_bytes():
                f.write(chunk)
                pbar.update(len(chunk))
    return dest


def fetch_scryfall_oracle() -> Path:
    log.info("Resolving Scryfall bulk data index")
    index = http_get_json(SCRYFALL_BULK_INDEX)
    target = next((b for b in index["data"] if b["type"] == "oracle_cards"), None)
    if not target:
        raise RuntimeError("Could not find oracle_cards in Scryfall bulk index")
    dest = RAW_DIR / "oracle_cards.json"
    if dest.exists() and dest.stat().st_size > 1_000_000:
        log.info("Using cached %s", dest)
        return dest
    log.info("Downloading %s", target["download_uri"])
    return download_file(target["download_uri"], dest)


def fetch_comp_rules() -> Path:
    dest = RAW_DIR / "comprehensive_rules.txt"
    if dest.exists() and dest.stat().st_size > 100_000:
        return dest
    candidates: List[str] = []
    log.info("Scraping %s for the latest rules txt", WOTC_RULES_INFO_PAGE)
    try:
        with httpx.Client(
            timeout=30.0, follow_redirects=True, headers={"User-Agent": UA}
        ) as c:
            r = c.get(WOTC_RULES_INFO_PAGE)
            for m in re.finditer(
                r'href="([^"]+MagicCompRules[^"]+\.txt)"', r.text
            ):
                candidates.append(m.group(1))
    except Exception as e:
        log.warning("Could not scrape rules page: %s", e)
    candidates.extend(
        [
            "https://media.wizards.com/2025/downloads/MagicCompRules.txt",
            "https://media.wizards.com/2024/downloads/MagicCompRules%2020241108.txt",
        ]
    )
    last_err: Optional[Exception] = None
    for url in candidates:
        try:
            log.info("Trying %s", url)
            return download_file(url, dest)
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(
        f"Failed to download Comprehensive Rules. Last error: {last_err}"
    )


def format_legality_lines(legalities: dict) -> str:
    """Human-readable per-format legality string used in card document text.

    Produces lines like:
        Formats:
          Standard: legal
          Pioneer:  legal
          Modern:   not_legal
          Legacy:   banned
    """
    rows = []
    width = max(len(f) for f in FORMATS) + 1
    for fmt in FORMATS:
        status = legalities.get(fmt, "not_legal")
        rows.append(f"  {fmt.capitalize().ljust(width)} {status}")
    return "Formats:\n" + "\n".join(rows)


def card_to_text(card: dict) -> str:
    name = card.get("name", "")
    cost = card.get("mana_cost", "")
    typ = card.get("type_line", "")
    oracle = card.get("oracle_text", "")
    pt = ""
    if "power" in card and "toughness" in card:
        pt = f"\nP/T: {card['power']}/{card['toughness']}"
    loyalty = f"\nLoyalty: {card['loyalty']}" if "loyalty" in card else ""
    keywords = ", ".join(card.get("keywords") or [])
    legalities = card.get("legalities") or {}
    faces = ""
    if "card_faces" in card:
        faces_lines = []
        for f in card["card_faces"]:
            faces_lines.append(
                "-- Face: {n} {c}\n{t}\n{o}".format(
                    n=f.get("name", ""),
                    c=f.get("mana_cost", ""),
                    t=f.get("type_line", ""),
                    o=f.get("oracle_text", ""),
                )
            )
        faces = "\n" + "\n".join(faces_lines)
    return (
        f"{name} {cost}\n{typ}\n{oracle}{pt}{loyalty}\n"
        f"Keywords: {keywords}\n{format_legality_lines(legalities)}{faces}"
    ).strip()


def card_meta(card: dict) -> dict:
    legalities = card.get("legalities") or {}
    meta: dict = {
        "name": card.get("name", ""),
        "set": card.get("set", ""),
        "type_line": card.get("type_line", ""),
        "cmc": float(card.get("cmc") or 0),
        "rarity": card.get("rarity", ""),
        "oracle_id": card.get("oracle_id", ""),
        "scryfall_uri": card.get("scryfall_uri", ""),
    }
    for fmt in FORMATS:
        status = legalities.get(fmt, "not_legal")
        meta[f"legal_{fmt}"] = status == "legal"
        meta[f"status_{fmt}"] = status  # legal | not_legal | banned | restricted
    # Backward-compat field used by older indexes and the Standard-only filter.
    meta["standard_legal"] = meta["legal_standard"]
    return meta


def iter_cards(path: Path) -> Iterable[dict]:
    with open(path, "rb") as f:
        for card in ijson.items(f, "item"):
            if card.get("layout") in SKIP_LAYOUTS:
                continue
            yield card


def parse_rules(path: Path) -> List[Tuple[str, str]]:
    text = (
        path.read_text(encoding="utf-8", errors="ignore")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    rule_re = re.compile(r"^(\d{3}(?:\.\d+)?[a-z]?)\.?\s", re.MULTILINE)
    matches = list(rule_re.finditer(text))
    raw: List[Tuple[str, str]] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        # Drop bare table-of-contents stubs ("100. General") but keep real
        # short rules like "702.21a Lifelink is a static ability."
        if len(body) < 25:
            continue
        first_line = body.split("\n", 1)[0]
        if len(body) <= len(first_line) + 1 and not first_line.rstrip().endswith(
            (".", "!", "?", ":", ")")
        ):
            continue
        raw.append((m.group(1), body))
    by_id: dict = {}
    for n, body in raw:
        if n not in by_id or len(body) > len(by_id[n]):
            by_id[n] = body
    return list(by_id.items())


def batch_embed(texts: List[str], workers: int = 8) -> List[List[float]]:
    out: List[Optional[List[float]]] = [None] * len(texts)

    def go(client: httpx.Client, i: int, t: str):
        r = client.post(
            f"{OLLAMA_HOST}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": t},
        )
        r.raise_for_status()
        return i, r.json()["embedding"]

    with httpx.Client(timeout=120.0) as client, ThreadPoolExecutor(
        max_workers=workers
    ) as pool:
        futs = [pool.submit(go, client, i, t) for i, t in enumerate(texts)]
        for f in tqdm(
            as_completed(futs), total=len(futs), desc="embed", leave=False
        ):
            i, vec = f.result()
            out[i] = vec
    if any(v is None for v in out):
        raise RuntimeError("Some embeddings failed")
    return out  # type: ignore[return-value]


def upsert_batch(col, ids, docs, metas, vecs, batch_size: int = 256):
    for i in range(0, len(ids), batch_size):
        col.upsert(
            ids=ids[i : i + batch_size],
            documents=docs[i : i + batch_size],
            metadatas=metas[i : i + batch_size],
            embeddings=vecs[i : i + batch_size],
        )


def ingest_cards(
    limit: Optional[int] = None,
    only_standard: bool = False,
    workers: int = 8,
) -> None:
    path = fetch_scryfall_oracle()
    client = get_client()
    col = get_or_create(client, CHROMA_CARDS)
    docs: List[str] = []
    metas: List[dict] = []
    ids: List[str] = []
    seen: set = set()
    for card in iter_cards(path):
        if only_standard and (card.get("legalities") or {}).get("standard") != "legal":
            continue
        oid = card.get("oracle_id")
        if not oid or oid in seen:
            continue
        seen.add(oid)
        ids.append(oid)
        docs.append(card_to_text(card))
        metas.append(card_meta(card))
        if limit and len(ids) >= limit:
            break
    log.info("Embedding %d cards (workers=%d)", len(ids), workers)
    CHUNK = 1024
    for start in range(0, len(ids), CHUNK):
        sl = slice(start, start + CHUNK)
        vecs = batch_embed(docs[sl], workers=workers)
        upsert_batch(col, ids[sl], docs[sl], metas[sl], vecs)
        log.info("Upserted %d / %d cards", min(start + CHUNK, len(ids)), len(ids))


def ingest_rules(workers: int = 8) -> None:
    path = fetch_comp_rules()
    client = get_client()
    col = get_or_create(client, CHROMA_RULES)
    chunks = parse_rules(path)
    log.info("Parsed %d unique rule entries", len(chunks))
    ids = [f"rule-{n}" for n, _ in chunks]
    docs = [body for _, body in chunks]
    metas = [{"rule_number": n} for n, _ in chunks]
    CHUNK = 1024
    for start in range(0, len(ids), CHUNK):
        sl = slice(start, start + CHUNK)
        vecs = batch_embed(docs[sl], workers=workers)
        upsert_batch(col, ids[sl], docs[sl], metas[sl], vecs)
        log.info("Upserted %d / %d rules", min(start + CHUNK, len(ids)), len(ids))


def ingest_strategy(workers: int = 4) -> None:
    if not STRATEGY_DIR.exists():
        log.info("No strategy dir at %s; skipping", STRATEGY_DIR)
        return
    files = list(STRATEGY_DIR.rglob("*.md")) + list(STRATEGY_DIR.rglob("*.txt"))
    files = [f for f in files if f.name.lower() != "readme.md"]
    if not files:
        log.info("No strategy files; skipping")
        return
    client = get_client()
    col = get_or_create(client, CHROMA_STRATEGY)
    ids: List[str] = []
    docs: List[str] = []
    metas: List[dict] = []
    for fp in files:
        text = fp.read_text(encoding="utf-8", errors="ignore")
        for i in range(0, len(text), 1500):
            chunk = text[i : i + 1500]
            if not chunk.strip():
                continue
            ids.append(f"{fp.stem}-{i}")
            docs.append(chunk)
            metas.append(
                {"title": fp.stem, "path": str(fp.relative_to(STRATEGY_DIR))}
            )
    if not ids:
        return
    log.info("Embedding %d strategy chunks", len(ids))
    vecs = batch_embed(docs, workers=workers)
    upsert_batch(col, ids, docs, metas, vecs)


def main() -> None:
    p = argparse.ArgumentParser(description="Ingest MTG knowledge into Chroma")
    p.add_argument("--cards", action="store_true", help="Embed Scryfall oracle cards")
    p.add_argument("--rules", action="store_true", help="Embed Comprehensive Rules")
    p.add_argument(
        "--strategy", action="store_true", help="Embed user strategy notes"
    )
    p.add_argument(
        "--all", action="store_true", help="Run rules + cards + strategy"
    )
    p.add_argument(
        "--standard-only",
        action="store_true",
        help="Only embed Standard-legal cards",
    )
    p.add_argument(
        "--limit", type=int, default=None, help="Cap card count (smoke tests)"
    )
    p.add_argument(
        "--workers", type=int, default=8, help="Concurrent embedding requests"
    )
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not (args.cards or args.rules or args.strategy or args.all):
        p.print_help()
        sys.exit(1)

    if args.all or args.rules:
        ingest_rules(workers=args.workers)
    if args.all or args.cards:
        ingest_cards(
            limit=args.limit,
            only_standard=args.standard_only,
            workers=args.workers,
        )
    if args.all or args.strategy:
        ingest_strategy(workers=args.workers)


if __name__ == "__main__":
    main()
