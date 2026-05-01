import logging
from dataclasses import dataclass
from typing import List, Optional

import chromadb
import httpx

from .config import (
    CHROMA_CARDS,
    CHROMA_DIR,
    CHROMA_RULES,
    CHROMA_STRATEGY,
    EMBED_MODEL,
    OLLAMA_HOST,
)

log = logging.getLogger(__name__)


@dataclass
class Retrieved:
    text: str
    metadata: dict
    score: float
    source: str


def get_client() -> chromadb.PersistentClient:
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(CHROMA_DIR))


def get_or_create(client: chromadb.PersistentClient, name: str):
    return client.get_or_create_collection(
        name=name, metadata={"hnsw:space": "cosine"}
    )


def embed_one(text: str) -> List[float]:
    with httpx.Client(timeout=60.0) as c:
        r = c.post(
            f"{OLLAMA_HOST}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
        )
        r.raise_for_status()
        return r.json()["embedding"]


def _query(col, qv: List[float], k: int, where: Optional[dict]):
    kwargs: dict = {"query_embeddings": [qv], "n_results": k}
    if where:
        kwargs["where"] = where
    try:
        return col.query(**kwargs)
    except Exception as e:
        if where:
            log.warning("Filtered query failed (%s); retrying without filter", e)
            return col.query(query_embeddings=[qv], n_results=k)
        raise


def retrieve(
    query: str,
    k_cards: int = 8,
    k_rules: int = 6,
    k_strategy: int = 4,
    standard_only: bool = False,
) -> List[Retrieved]:
    client = get_client()
    qv = embed_one(query)
    out: List[Retrieved] = []
    # Filters apply only to the cards collection.
    cards_where = {"standard_legal": True} if standard_only else None
    plan = [
        (CHROMA_RULES, k_rules, "RULES", None),
        (CHROMA_CARDS, k_cards, "CARD", cards_where),
        (CHROMA_STRATEGY, k_strategy, "STRATEGY", None),
    ]
    for cname, k, source, where in plan:
        try:
            col = client.get_collection(cname)
        except Exception:
            continue
        try:
            res = _query(col, qv, k, where)
        except Exception as e:
            log.warning("query failed on %s: %s", cname, e)
            continue
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        for doc, meta, dist in zip(docs, metas, dists):
            score = max(0.0, 1.0 - float(dist))
            out.append(
                Retrieved(
                    text=doc,
                    metadata=meta or {},
                    score=score,
                    source=source,
                )
            )
    out.sort(key=lambda r: r.score, reverse=True)
    return out


def format_context(items: List[Retrieved], max_chars: int = 14000) -> str:
    parts: List[str] = []
    used = 0
    for r in items:
        if r.source == "RULES":
            head = f"[RULES] CR {r.metadata.get('rule_number', '')}"
        elif r.source == "CARD":
            name = r.metadata.get("name", "")
            sset = (r.metadata.get("set", "") or "").upper()
            head = f"[CARD] {name} ({sset})"
        else:
            head = f"[STRATEGY] {r.metadata.get('title', '')}"
        block = f"{head}\n{r.text}\n"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n---\n".join(parts)
