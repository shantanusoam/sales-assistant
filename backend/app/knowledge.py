"""Markdown chunking + lexical test fallback + optional Chroma/OpenAI vector RAG."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .config import Settings

logger = logging.getLogger(__name__)
STOP = frozenset("the a an and or for from on of in at to is are was were be been my your their our i you we it that this what why how do does can could would will with about have has had not but as so if do them those".split())


def terms(text: str) -> list[str]:
    return [t for t in re.findall(r"\w+", text.casefold()) if t not in STOP and len(t) >= 2]


@dataclass(frozen=True)
class Snippet:
    id: str
    title: str
    text: str
    score: float = 0.0

    def public(self) -> dict[str, str]:
        return {"title": self.title, "excerpt": self.text[:210]}


def load_chunks(directory: Path, length: int = 850, overlap: int = 140) -> list[Snippet]:
    """Sliding windows; stable IDs based on path and position."""
    chunks: list[Snippet] = []
    if not directory.exists():
        return chunks
    for path in sorted(directory.glob("**/*.md")):
        raw = path.read_text(encoding="utf-8")
        doc = re.sub(r"\s+", " ", raw).strip()
        title = path.stem.replace("_", " ").replace("-", " ").title()
        if not doc:
            continue
        pos = 0
        while pos < len(doc):
            end = min(len(doc), pos + length)
            if end < len(doc):
                word_break = doc.rfind(" ", max(pos + 100, end - 100), end)
                if word_break > pos:
                    end = word_break
            text = doc[pos:end].strip()
            if text:
                hash_id = hashlib.sha256(f"{path.name}|{pos}|{text}".encode()).hexdigest()[:20]
                chunks.append(Snippet(hash_id, title, text))
            if end == len(doc):
                break
            pos = max(pos + 1, end - overlap)
    return chunks


class LexicalRetriever:
    """Zero-key local retrieval to make the test mode useful; NOT vector RAG."""

    def __init__(self, chunks: list[Snippet]):
        self.chunks = chunks
        self.doc_terms = [Counter(terms(c.text)) for c in chunks]
        df = Counter(t for count in self.doc_terms for t in count)
        self.idf = {term: math.log(1 + (len(chunks) + 1) / (count + 1)) for term, count in df.items()}

    def retrieve(self, text: str, k: int = 3) -> list[Snippet]:
        query_terms = set(terms(text))
        ranked = []
        for chunk, count in zip(self.chunks, self.doc_terms):
            score = sum(math.log1p(count.get(term, 0)) * self.idf.get(term, 0) for term in query_terms)
            if score > 0:
                ranked.append(Snippet(chunk.id, chunk.title, chunk.text, score))
        return sorted(ranked, key=lambda s: s.score, reverse=True)[:k]


class KnowledgeBase:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.chunks = load_chunks(settings.playbook_dir)
        self.fallback = LexicalRetriever(self.chunks)
        self.collection = None
        self.embedder = None
        self.mode = "lexical-demo"
        if settings.openai_api_key:
            try:
                import chromadb  # loaded optionally, never downloads an embedding model
                from openai import AsyncOpenAI

                client = chromadb.PersistentClient(path=str(settings.chroma_dir))
                col = client.get_or_create_collection(name="sales_playbooks", embedding_function=None)
                if col.count() > 0:
                    self.collection = col
                    self.embedder = AsyncOpenAI(api_key=settings.openai_api_key, timeout=8.0, max_retries=0)
                    self.mode = "chroma-embeddings"
            except ImportError:
                logger.warning("Chroma is unavailable; using lexical demo retrieval.")
            except Exception:
                logger.exception("Cannot load vector index; using lexical demo retrieval.")

    async def retrieve(self, utterance: str, k: int = 3) -> list[Snippet]:
        if self.collection is not None and self.embedder is not None:
            try:
                result = await self.embedder.embeddings.create(
                    model=self.settings.openai_embedding_model,
                    input=utterance[:2000],
                )
                q = await asyncio.to_thread(
                    self.collection.query,
                    query_embeddings=[result.data[0].embedding],
                    n_results=k,
                    include=["metadatas", "documents", "distances"],
                )
                ids = q.get("ids", [[]])[0]
                titles = q.get("metadatas", [[]])[0]
                docs = q.get("documents", [[]])[0]
                distances = q.get("distances", [[]])[0]
                return [Snippet(uid, meta.get("title", "Playbook"), doc, 1 / (1 + dist))
                        for uid, meta, doc, dist in zip(ids, titles, docs, distances)]
            except Exception:
                logger.exception("Vector search failed; using lexical fallback.")
                self.collection = None
                self.embedder = None
                self.mode = "lexical-demo"
        return self.fallback.retrieve(utterance, k=k)
