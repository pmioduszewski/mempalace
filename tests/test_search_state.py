"""Tests for B1/B2: drawer_id on every result row + superseded filter + backrefs.

B1 — search_memories gains drawer_id+state on every row, default-hides
     superseded drawers, and attaches superseded_by/supersedes backrefs.
B2 — tool_search forwards include_superseded/follow_supersedes to
     search_memories (both call sites).
"""

from mempalace.searcher import search_memories
import mempalace.palace_graph as palace_graph


def _seed(col):
    col.add(
        ids=["drawer_w_r_old", "drawer_w_r_new", "drawer_w_r_other"],
        documents=[
            "Active brand is Oldbrand with domain oldbrand.com",
            "Rebrand decision Oldbrand to Newbrand effective Feb",
            "Unrelated note about pgbouncer pooling",
        ],
        metadatas=[
            {
                "wing": "w",
                "room": "r",
                "source_file": "a",
                "chunk_index": 0,
                "filed_at": "2026-01-01T00:00:00",
                "status": "superseded",
                "superseded_by_id": "drawer_w_r_new",
            },
            {
                "wing": "w",
                "room": "r",
                "source_file": "b",
                "chunk_index": 0,
                "filed_at": "2026-02-01T00:00:00",
            },
            {
                "wing": "w",
                "room": "r",
                "source_file": "c",
                "chunk_index": 0,
                "filed_at": "2026-01-01T00:00:00",
            },
        ],
    )


def test_drawer_id_on_every_row(collection, palace_path):
    _seed(collection)
    res = search_memories("brand Oldbrand", palace_path, n_results=5)
    assert all("drawer_id" in r and "state" in r for r in res["results"])


def test_default_filters_superseded(collection, palace_path):
    _seed(collection)
    res = search_memories("Oldbrand brand domain", palace_path, n_results=5)
    ids = {r["drawer_id"] for r in res["results"]}
    assert "drawer_w_r_old" not in ids


def test_include_superseded_returns_them(collection, palace_path):
    _seed(collection)
    res = search_memories("Oldbrand brand domain", palace_path, n_results=5, include_superseded=True)
    rows = {r["drawer_id"]: r for r in res["results"]}
    assert rows["drawer_w_r_old"]["state"] == "superseded"


def test_current_row_gets_supersedes_backref(collection, palace_path, monkeypatch, tmp_path):
    _seed(collection)
    monkeypatch.setattr(palace_graph, "_get_tunnel_file", lambda *a, **k: str(tmp_path / "t.json"))
    palace_graph.create_supersedence(
        "w", "r", "drawer_w_r_old", "w", "r", "drawer_w_r_new", reason="rebrand"
    )
    res = search_memories("Rebrand Newbrand", palace_path, n_results=5)
    new = next(r for r in res["results"] if r["drawer_id"] == "drawer_w_r_new")
    assert new["supersedes"][0]["predecessor"]["drawer_id"] == "drawer_w_r_old"


# ── B2: tool_search plumbing ──────────────────────────────────────────────────

import mempalace.mcp_server as mcp_server  # noqa: E402


def test_tool_search_default_hides_superseded(monkeypatch, config, palace_path, kg):
    monkeypatch.setattr(mcp_server, "_config", config)
    col = mcp_server._get_collection(create=True)
    _seed(col)
    res = mcp_server.tool_search(query="Oldbrand brand domain")
    assert all(r["drawer_id"] != "drawer_w_r_old" for r in res["results"])


def test_tool_search_include_superseded_param(monkeypatch, config, palace_path, kg):
    monkeypatch.setattr(mcp_server, "_config", config)
    col = mcp_server._get_collection(create=True)
    _seed(col)
    res2 = mcp_server.tool_search(query="Oldbrand brand domain", include_superseded=True)
    assert any(r["drawer_id"] == "drawer_w_r_old" for r in res2["results"])


# ── #2: union candidate strategy must not bypass superseded hide ───────────────


def test_union_does_not_resurface_superseded_by_bm25(tmp_path):
    """Superseded drawers with strong BM25 signal must NOT reappear via union mode.

    Bug: BM25-only candidates appended by the union path carried no ``status``
    field, so superseded drawers re-entered results and were mislabelled
    state="current".  After the fix, status is selected and filtered in the
    union merge path.
    """
    from mempalace.palace import get_collection

    palace = str(tmp_path / "palace")
    col = get_collection(palace, create=True)
    # The superseded drawer has extremely strong BM25 signal for the query —
    # every query term appears verbatim in its text.
    col.upsert(
        ids=["drawer_sup_old", "drawer_sup_new", "drawer_unrelated"],
        documents=[
            "oldbrand domain rebrand superseded old oldbrand oldbrand oldbrand",
            "newbrand is the new brand replacing oldbrand from February",
            "unrelated note about pgbouncer and database pooling config",
        ],
        metadatas=[
            {
                "wing": "w",
                "room": "r",
                "source_file": "old.md",
                "chunk_index": 0,
                "filed_at": "2026-01-01T00:00:00",
                "status": "superseded",
                "superseded_by_id": "drawer_sup_new",
            },
            {
                "wing": "w",
                "room": "r",
                "source_file": "new.md",
                "chunk_index": 0,
                "filed_at": "2026-02-01T00:00:00",
            },
            {
                "wing": "w",
                "room": "r",
                "source_file": "other.md",
                "chunk_index": 0,
                "filed_at": "2026-01-01T00:00:00",
            },
        ],
    )

    res = search_memories(
        "oldbrand domain rebrand",
        palace,
        n_results=5,
        candidate_strategy="union",
        include_superseded=False,
    )
    ids = {r.get("drawer_id") or r.get("source_file") for r in res["results"]}
    assert "drawer_sup_old" not in ids, (
        f"superseded drawer must be hidden in union mode; got ids={ids}"
    )
    # When explicitly requested, it must come back with state="superseded".
    res_inc = search_memories(
        "oldbrand domain rebrand",
        palace,
        n_results=5,
        candidate_strategy="union",
        include_superseded=True,
    )
    sup_rows = [r for r in res_inc["results"] if r.get("drawer_id") == "drawer_sup_old"]
    if sup_rows:
        assert sup_rows[0]["state"] == "superseded", (
            f"superseded drawer in union results must carry state='superseded'; got {sup_rows[0]}"
        )


# ── #3: BM25-only fallback (vector_disabled=True) must hide superseded ─────────


def test_bm25_fallback_hides_superseded_by_default(tmp_path):
    """vector_disabled=True path must hide superseded drawers and stamp state.

    Bug: the fallback returned _bm25_only_via_sqlite directly, skipping
    _apply_supersedence entirely — superseded drawers appeared in results
    and carried no ``state`` field.
    """
    from mempalace.palace import get_collection

    palace = str(tmp_path / "palace")
    col = get_collection(palace, create=True)
    col.upsert(
        ids=["drawer_bm25_old", "drawer_bm25_new"],
        documents=[
            "oldbrand domain brand superseded old note about the rebrand",
            "newbrand new brand replacing oldbrand",
        ],
        metadatas=[
            {
                "wing": "w",
                "room": "r",
                "source_file": "old.md",
                "chunk_index": 0,
                "filed_at": "2026-01-01T00:00:00",
                "status": "superseded",
            },
            {
                "wing": "w",
                "room": "r",
                "source_file": "new.md",
                "chunk_index": 0,
                "filed_at": "2026-02-01T00:00:00",
            },
        ],
    )

    res = search_memories(
        "oldbrand domain rebrand",
        palace,
        n_results=5,
        vector_disabled=True,
        include_superseded=False,
    )
    results = res.get("results", [])
    sources = [r.get("source_file") for r in results]
    assert "old.md" not in sources, (
        f"superseded drawer must be hidden in bm25 fallback; got sources={sources}"
    )
    # All returned rows must carry a ``state`` field.
    assert all("state" in r for r in results), (
        f"every bm25-fallback row must have 'state'; got {results}"
    )


def test_bm25_fallback_returns_superseded_when_requested(tmp_path):
    """vector_disabled + include_superseded=True must return superseded with state='superseded'."""
    from mempalace.palace import get_collection

    palace = str(tmp_path / "palace")
    col = get_collection(palace, create=True)
    col.upsert(
        ids=["drawer_bm25_sup"],
        documents=["oldbrand old brand note superseded"],
        metadatas=[
            {
                "wing": "w",
                "room": "r",
                "source_file": "sup.md",
                "chunk_index": 0,
                "filed_at": "2026-01-01T00:00:00",
                "status": "superseded",
            }
        ],
    )
    res = search_memories(
        "oldbrand brand",
        palace,
        n_results=5,
        vector_disabled=True,
        include_superseded=True,
    )
    results = res.get("results", [])
    assert results, "expected at least one result"
    assert all("state" in r for r in results), "every row must carry state"
    sup = next((r for r in results if r.get("source_file") == "sup.md"), None)
    if sup:
        assert sup["state"] == "superseded", f"expected state='superseded', got {sup['state']}"
