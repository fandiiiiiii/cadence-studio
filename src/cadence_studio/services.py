"""Process-wide service container (one local workbench, one data dir)."""

from __future__ import annotations

from .config import CONFIG
from .db import DB
from .hf_endpoints import HFEndpointManager
from .inference import AudioInferenceClient
from .llm import LLMClient
from .pipeline import WorkManager


class Services:
    def __init__(self) -> None:
        self.config = CONFIG
        self.db = DB
        self.endpoints = HFEndpointManager(self.config)
        self.inference = AudioInferenceClient(self.config, self.endpoints)
        self.llm = LLMClient(self.config)
        self.manager = WorkManager(self.config, self.db, self.endpoints, self.inference, self.llm)


SERVICES = Services()
