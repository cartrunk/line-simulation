from __future__ import annotations
import time
from typing import List

import chromadb
from chromadb.utils import embedding_functions

from .config import MEMORY_PERSIST_DIR, SURPRISE_THRESHOLD
from .types import AetherState, MemorySnapshot
from .llm import llm_complete


class MemoryFabric:
    def __init__(self, persist_dir: str = MEMORY_PERSIST_DIR):
        self._chroma = chromadb.PersistentClient(path=persist_dir)
        self._ef = embedding_functions.DefaultEmbeddingFunction()
        self._recall = self._chroma.get_or_create_collection(
            name="recall",
            embedding_function=self._ef,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def empty_snapshot(self) -> MemorySnapshot:
        return MemorySnapshot(
            core="No information stored yet.",
            user_profile="Unknown user.",
        )

    async def recall_top_k(self, k: int) -> List[str]:
        count = self._recall.count()
        if count == 0:
            return []
        results = self._recall.get(limit=min(k, count))
        return results["documents"] or []

    def compute_surprise(self, observation: str, snapshot: MemorySnapshot) -> float:
        """
        Novelty score 0-1.
        Uses cosine distance to nearest stored memory.
        Returns 1.0 when memory is empty (everything is novel).
        """
        if self._recall.count() == 0:
            return 1.0
        results = self._recall.query(
            query_texts=[observation],
            n_results=min(5, self._recall.count()),
        )
        distances = results.get("distances", [[]])[0]
        if not distances:
            return 1.0
        # chromadb L2 distance; clamp to [0, 1]
        return min(1.0, min(distances) / 2.0)

    async def update(self, state: AetherState, observation: str) -> None:
        surprise = self.compute_surprise(observation, state["memory_snapshot"])
        state["surprise_score"] = surprise

        should_write = (
            surprise > SURPRISE_THRESHOLD
            or len(state["action_history"]) % 5 == 0
        )
        if not should_write:
            return

        summary = await self._reflect(observation, state)

        # Tier 1 – Core block (always in context)
        state["memory_snapshot"]["core"] = await self._refresh_core(summary, state)

        # Tier 2 – Vector recall store
        self._recall.upsert(
            ids=[f"{time.time():.6f}"],
            documents=[summary],
            metadatas=[{"ts": time.time()}],
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _reflect(self, observation: str, state: AetherState) -> str:
        prompt = (
            f"Reflect on this new observation in under 200 words:\n\n"
            f"{observation}\n\n"
            f"Current memory core:\n{state['memory_snapshot']['core']}\n\n"
            f"Summarise only:\n"
            f"- key facts to store\n"
            f"- any contradictions with existing knowledge\n"
            f"- updated user profile delta"
        )
        return await llm_complete(prompt)

    async def _refresh_core(self, new_summary: str, state: AetherState) -> str:
        prompt = (
            f"You maintain a compact always-in-context memory block (max 300 words).\n\n"
            f"Current core:\n{state['memory_snapshot']['core']}\n\n"
            f"New information:\n{new_summary}\n\n"
            f"Rewrite the core block integrating the new information. Be concise."
        )
        return await llm_complete(prompt)
