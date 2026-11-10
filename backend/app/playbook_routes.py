"""Playbook management endpoints: inspect, create/update, and remove markdown playbooks with live reload."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .config import Settings
from .knowledge import KnowledgeBase


class PlaybookUpsertRequest(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    content: str = Field(min_length=10, max_length=20000)


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.casefold()).strip("_")
    return slug[:64] or "playbook"


def _doc_info(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    return {
        "slug": path.stem,
        "filename": path.name,
        "title": path.stem.replace("_", " ").replace("-", " ").title(),
        "content": raw,
        "size_bytes": len(raw.encode("utf-8")),
    }


def build_playbook_router(settings: Settings, knowledge: KnowledgeBase, require_auth) -> APIRouter:
    router = APIRouter(prefix="/api/playbooks", tags=["playbooks"])

    def require_admin(claims: dict) -> None:
        if claims["role"] != "admin":
            raise HTTPException(403, "Only an org admin can modify sales playbooks.")

    @router.get("")
    async def list_playbooks(_claims: dict = Depends(require_auth)) -> dict:
        directory = settings.playbook_dir
        files = sorted(directory.glob("*.md")) if directory.exists() else []
        return {
            "retrieval_mode": knowledge.mode,
            "total_chunks": len(knowledge.chunks),
            "playbooks": [_doc_info(p) for p in files],
        }

    @router.post("")
    async def upsert_playbook(payload: PlaybookUpsertRequest, claims: dict = Depends(require_auth)) -> dict:
        require_admin(claims)
        directory = settings.playbook_dir
        directory.mkdir(parents=True, exist_ok=True)
        slug = _slugify(payload.title)
        target = (directory / f"{slug}.md").resolve()
        if target.parent != directory.resolve():
            raise HTTPException(400, "Invalid playbook title.")
        body = payload.content.strip()
        if not body.startswith("#"):
            body = f"# {payload.title.strip()}\n\n{body}"
        target.write_text(body + "\n", encoding="utf-8")
        knowledge.reload()
        return {
            "playbook": _doc_info(target),
            "total_chunks": len(knowledge.chunks),
        }

    @router.delete("/{slug}")
    async def delete_playbook(slug: str, claims: dict = Depends(require_auth)) -> dict:
        require_admin(claims)
        safe_slug = re.sub(r"[^a-zA-Z0-9_-]", "", slug)
        if not safe_slug or safe_slug != slug:
            raise HTTPException(400, "Invalid playbook identifier.")
        directory = settings.playbook_dir.resolve()
        target = (directory / f"{safe_slug}.md").resolve()
        if target.parent != directory or not target.exists():
            raise HTTPException(404, "Playbook not found.")
        files = list(directory.glob("*.md"))
        if len(files) <= 1:
            raise HTTPException(400, "At least one sales playbook must remain active.")
        target.unlink()
        knowledge.reload()
        return {"deleted": True, "total_chunks": len(knowledge.chunks)}

    return router
