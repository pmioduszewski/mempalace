"""Tests for entity-level supersedence annotation at retrieval (Task D1).

Verifies:
  1. A result row whose text mentions a KG-superseded entity name gets
     ``superseded_entities`` annotated with {old, new, reason}.
  2. When no KG is present (path points to a non-existent file),
     no ``superseded_entities`` key appears on any row and no exception
     leaks out of ``search_memories``.
  3. ``_kg_path_for_palace`` returns a usable string path WITHOUT
     monkeypatching — exercises the real resolver (regression for the
     AttributeError-on-class-attribute bug that caused annotation to
     silently no-op in production).
  4. With a KG co-located in the palace dir, annotation works without
     monkeypatching ``_kg_path_for_palace``.
  5. Short entity ids (< 3 chars) are skipped and do not produce noisy
     word-boundary matches.
"""

import os

from mempalace.knowledge_graph import KnowledgeGraph
from mempalace.searcher import search_memories, _kg_path_for_palace
import mempalace.searcher as searcher


def test_superseded_entity_annotates_row(collection, palace_path, monkeypatch, tmp_path):
    """Row mentioning a KG-superseded entity name gets superseded_entities."""
    collection.add(
        ids=["drawer_email_1"],
        documents=["Reminder: renew your oldbrand.com domain by 2026-12-15"],
        metadatas=[
            {
                "wing": "email",
                "room": "inbox",
                "source_file": "m",
                "chunk_index": 0,
                "filed_at": "2026-06-01T00:00:00",
            }
        ],
    )
    kgp = str(tmp_path / "kg.sqlite3")
    kg = KnowledgeGraph(db_path=kgp)
    kg.mark_superseded("oldbrand.com", "newbrand.com", reason="rebrand")
    kg.close()

    monkeypatch.setattr(searcher, "_kg_path_for_palace", lambda p: kgp, raising=False)

    res = search_memories("renew domain oldbrand", palace_path, n_results=5)
    row = res["results"][0]
    assert any(
        e["old"] == "oldbrand.com" and e["new"] == "newbrand.com"
        for e in row.get("superseded_entities", [])
    ), f"Expected annotation not found in row: {row}"


def test_no_kg_no_annotation(collection, palace_path):
    """When no KG file exists, rows have no superseded_entities key and no exception leaks."""
    collection.add(
        ids=["d1"],
        documents=["plain note"],
        metadatas=[
            {
                "wing": "w",
                "room": "r",
                "source_file": "f",
                "chunk_index": 0,
                "filed_at": "2026-01-01T00:00:00",
            }
        ],
    )
    res = search_memories("note", palace_path, n_results=5)
    assert "superseded_entities" not in res["results"][0]


# ── #1 regression: _kg_path_for_palace must return a real string without ──────
# monkeypatching (the class-attribute bug caused AttributeError which was
# swallowed, so annotation silently no-op'd in production).


def test_kg_path_for_palace_returns_string_without_raising(tmp_path):
    """_kg_path_for_palace must return a non-empty string and never raise.

    This test exercises the REAL resolver — no monkeypatching.  Before the fix,
    ``KnowledgeGraph.DEFAULT_KG_PATH`` raised AttributeError (DEFAULT_KG_PATH is
    a module global, not a class attribute) which was swallowed by the broad
    except in _annotate_superseded_entities, making annotation silently dead.
    """
    palace = str(tmp_path / "palace")
    os.makedirs(palace, exist_ok=True)
    result = _kg_path_for_palace(palace)
    assert isinstance(result, str), f"expected str, got {type(result)}: {result!r}"
    assert len(result) > 0, "path must not be empty"


def test_annotation_works_with_co_located_kg(tmp_path):
    """Annotation works when the KG lives inside the palace dir (no monkeypatching).

    This is the production layout when the MCP server is started with --palace.
    Before the fix, _kg_path_for_palace raised AttributeError → annotation
    never ran regardless of the KG location.
    """
    import chromadb

    palace = str(tmp_path / "palace")
    os.makedirs(palace, exist_ok=True)

    # Create a minimal ChromaDB palace with one matching drawer.
    client = chromadb.PersistentClient(path=palace)
    col = client.get_or_create_collection("mempalace_drawers", metadata={"hnsw:space": "cosine"})
    col.add(
        ids=["drawer_test_1"],
        documents=["Contact the oldcorp.com team about the migration"],
        metadatas=[
            {
                "wing": "email",
                "room": "inbox",
                "source_file": "msg.md",
                "chunk_index": 0,
                "filed_at": "2026-06-01T00:00:00",
            }
        ],
    )

    # Co-locate the KG inside the palace dir — the real path the MCP server uses.
    kg_path = os.path.join(palace, "knowledge_graph.sqlite3")
    kg = KnowledgeGraph(db_path=kg_path)
    kg.mark_superseded("oldcorp.com", "newcorp.com", reason="acquisition")
    kg.close()

    # No monkeypatching — _kg_path_for_palace must discover the co-located KG.
    res = search_memories("oldcorp migration contact", palace, n_results=5)
    assert res.get("results"), "expected at least one result"
    row = res["results"][0]
    assert "superseded_entities" in row, (
        f"annotation must fire for co-located KG without monkeypatching; row={row}"
    )
    assert any(
        e["old"] == "oldcorp.com" and e["new"] == "newcorp.com" for e in row["superseded_entities"]
    ), f"wrong annotation content: {row['superseded_entities']}"


# ── #6: short entity ids must be skipped ──────────────────────────────────────


def test_short_entity_id_not_annotated(collection, palace_path, monkeypatch, tmp_path):
    """Entity ids shorter than 3 chars must be skipped to avoid noisy matches.

    A superseded entity named 'is' would match almost every English sentence.
    The guard ensures we skip such ids silently.
    """
    collection.add(
        ids=["drawer_short_1"],
        documents=["This is a note about the project status."],
        metadatas=[
            {
                "wing": "notes",
                "room": "general",
                "source_file": "n.md",
                "chunk_index": 0,
                "filed_at": "2026-01-01T00:00:00",
            }
        ],
    )
    kgp = str(tmp_path / "kg_short.sqlite3")
    kg = KnowledgeGraph(db_path=kgp)
    # Register a 2-char entity id — should be skipped by the annotation guard.
    kg.mark_superseded("is", "was", reason="tense correction")
    kg.close()

    monkeypatch.setattr(searcher, "_kg_path_for_palace", lambda p: kgp, raising=False)

    res = search_memories("project status note", palace_path, n_results=5)
    assert res.get("results"), "expected at least one result"
    row = res["results"][0]
    # 'is' is < 3 chars so it must NOT be annotated.
    assert "superseded_entities" not in row, (
        f"short entity id 'is' must be skipped; got superseded_entities={row.get('superseded_entities')}"
    )
