"""Build the persistent Chroma vector index from /playbooks using OpenAI embeddings."""
from __future__ import annotations

from backend.app.config import Settings
from backend.app.knowledge import load_chunks


def main() -> None:
    import chromadb
    from openai import OpenAI

    settings = Settings()
    if not settings.openai_api_key:
        raise SystemExit("Set OPENAI_API_KEY in .env to ingest vectors. Without it, lexical demo mode works.")
    snippets = load_chunks(settings.playbook_dir)
    if not snippets:
        raise SystemExit("No markdown in playbooks/. Add company playbooks before ingesting.")
    client = OpenAI(api_key=settings.openai_api_key, timeout=30, max_retries=1)
    store = chromadb.PersistentClient(path=str(settings.chroma_dir))
    collection = store.get_or_create_collection(name="sales_playbooks", embedding_function=None)
    # Rebuild cleanly so outdated guidance isn't accidentally retrieved.
    try:
        existing_ids = collection.get(include=[])["ids"]
        if existing_ids:
            collection.delete(ids=existing_ids)
    except Exception:
        raise SystemExit("Could not clear the previous vector index; the operation was stopped.")
    batch_size = 30
    for pos in range(0, len(snippets), batch_size):
        batch = snippets[pos : pos + batch_size]
        response = client.embeddings.create(
            model=settings.openai_embedding_model,
            input=[s.text for s in batch],
        )
        vectors = [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
        collection.upsert(
            ids=[s.id for s in batch],
            embeddings=vectors,
            documents=[s.text for s in batch],
            metadatas=[{"title": s.title} for s in batch],
        )
        print(f"Indexed {min(pos + len(batch), len(snippets))}/{len(snippets)} snippets")
    print(f"Index ready in {settings.chroma_dir}")


if __name__ == "__main__":
    main()
