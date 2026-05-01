import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import DEFAULT_CHAT_MODEL, EMBED_MODEL, OLLAMA_HOST
from .ollama_manager import OllamaManager
from .prompts import SYSTEM_PROMPT
from .rag import format_context, retrieve

log = logging.getLogger(__name__)
ollama = OllamaManager()
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting Ollama (will spawn `ollama serve` if not running)")
    try:
        ok = ollama.start()
    except Exception as e:
        log.error("Ollama start failed: %s", e)
        ok = False
    if not ok:
        log.error(
            "Ollama is not reachable; the UI will load but chat will fail until "
            "`ollama serve` is running."
        )
    yield
    ollama.stop()


app = FastAPI(title="MTGMaster", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    use_rag: bool = True
    k_cards: int = 8
    k_rules: int = 6
    k_strategy: int = 4


@app.get("/api/health")
def health():
    return {"ollama": ollama.is_running()}


@app.get("/api/models")
def models():
    if not ollama.is_running():
        return {
            "models": [],
            "default": DEFAULT_CHAT_MODEL,
            "embed": EMBED_MODEL,
        }
    return {
        "models": ollama.list_models(),
        "default": DEFAULT_CHAT_MODEL,
        "embed": EMBED_MODEL,
    }


@app.post("/api/chat")
def chat(req: ChatRequest):
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages cannot be empty")
    last = req.messages[-1]
    user_q = last.content if last.role == "user" else ""

    context_block = ""
    citations: list = []
    if req.use_rag and user_q.strip():
        try:
            hits = retrieve(
                user_q,
                k_cards=req.k_cards,
                k_rules=req.k_rules,
                k_strategy=req.k_strategy,
            )
            context_block = format_context(hits)
            citations = [
                {
                    "source": h.source,
                    "label": (
                        h.metadata.get("name")
                        or h.metadata.get("rule_number")
                        or h.metadata.get("title", "")
                    ),
                    "score": round(h.score, 3),
                }
                for h in hits[:12]
            ]
        except Exception as e:
            log.warning("RAG retrieval failed: %s", e)

    sys_msg = SYSTEM_PROMPT
    if context_block:
        sys_msg += (
            "\n\n=== RETRIEVED CONTEXT (use this; cite [RULES] / [CARD] / [STRATEGY]) ===\n"
            + context_block
        )
    elif req.use_rag:
        sys_msg += (
            "\n\n(No context retrieved. If the user is asking about cards or rules, "
            "say you don't have sources rather than guessing.)"
        )

    payload = {
        "model": req.model,
        "messages": [{"role": "system", "content": sys_msg}]
        + [m.model_dump() for m in req.messages],
        "stream": True,
        "options": {"temperature": 0.2},
    }

    def gen():
        yield "data: " + json.dumps(
            {"type": "citations", "data": citations}
        ) + "\n\n"
        try:
            with httpx.stream(
                "POST",
                f"{OLLAMA_HOST}/api/chat",
                json=payload,
                timeout=None,
            ) as r:
                if r.status_code != 200:
                    body = r.read().decode("utf-8", errors="ignore")
                    yield "data: " + json.dumps(
                        {"type": "error", "data": f"Ollama {r.status_code}: {body}"}
                    ) + "\n\n"
                    return
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if "message" in obj and "content" in obj["message"]:
                        yield "data: " + json.dumps(
                            {"type": "token", "data": obj["message"]["content"]}
                        ) + "\n\n"
                    if obj.get("done"):
                        yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                        return
        except Exception as e:
            yield "data: " + json.dumps(
                {"type": "error", "data": f"Stream failed: {e}"}
            ) + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
