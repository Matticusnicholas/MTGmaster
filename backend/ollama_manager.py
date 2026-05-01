import logging
import shutil
import subprocess
import time
from typing import List, Optional

import httpx

from .config import OLLAMA_HOST

log = logging.getLogger(__name__)


class OllamaManager:
    """Spawns and probes a local `ollama serve` process and lists available models."""

    def __init__(self, host: str = OLLAMA_HOST):
        self.host = host
        self.proc: Optional[subprocess.Popen] = None

    def is_running(self) -> bool:
        try:
            r = httpx.get(f"{self.host}/api/tags", timeout=1.0)
            return r.status_code == 200
        except Exception:
            return False

    def start(self, wait_seconds: float = 20.0) -> bool:
        if self.is_running():
            log.info("Ollama already running at %s", self.host)
            return True
        if not shutil.which("ollama"):
            raise RuntimeError(
                "ollama CLI not found on PATH. Install Ollama from https://ollama.com"
            )
        log.info("Spawning `ollama serve`")
        self.proc = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if self.is_running():
                log.info("Ollama is up")
                return True
            time.sleep(0.3)
        log.error("Ollama did not respond within %.1fs", wait_seconds)
        return False

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            log.info("Stopping spawned Ollama process")
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def list_models(self) -> List[str]:
        try:
            r = httpx.get(f"{self.host}/api/tags", timeout=5.0)
            r.raise_for_status()
            return sorted(m["name"] for m in r.json().get("models", []))
        except Exception as e:
            log.warning("Could not list models: %s", e)
            return []
