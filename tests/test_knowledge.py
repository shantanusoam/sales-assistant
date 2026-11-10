from pathlib import Path

from backend.app.knowledge import LexicalRetriever, load_chunks


def test_chunking_and_retrieval(tmp_path: Path):
    (tmp_path / "price.md").write_text("# Pricing\nAsk about budget and existing manual process cost. Never invent discounts.")
    (tmp_path / "setup.md").write_text("# Setup\nDiscuss team training and implementation planning.")
    chunks = load_chunks(tmp_path, length=100, overlap=10)
    assert len(chunks) >= 2
    results = LexicalRetriever(chunks).retrieve("budget discount cost", 2)
    assert results
    assert "Price" in results[0].title
    assert not LexicalRetriever(chunks).retrieve("vuvuzela shoelaces")

    # Hinglish / Devanagari query expansion matches English pricing playbook
    hi_results = LexicalRetriever(chunks).retrieve("आपका solution थोड़ा महंगा है और mehenga keemat", 2)
    assert hi_results
    assert "Price" in hi_results[0].title
