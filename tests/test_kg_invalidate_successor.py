"""Tests for mark_superseded / current_supersessions (C1) and
tool_kg_invalidate optional successor args (C2)."""

# ── C1: KnowledgeGraph.mark_superseded + current_supersessions ────────────


def test_mark_superseded_inserts_triple(kg):
    kg.mark_superseded("Oldbrand", "Newbrand", reason="rebrand")
    sup = kg.current_supersessions()
    assert sup["oldbrand"]["new"] == "Newbrand"
    assert sup["oldbrand"]["reason"] == "rebrand"


def test_current_supersessions_empty_by_default(seeded_kg):
    assert seeded_kg.current_supersessions() == {}


def test_mark_superseded_no_reason(kg):
    kg.mark_superseded("OldCo", "NewCo")
    sup = kg.current_supersessions()
    assert "oldco" in sup
    assert sup["oldco"]["new"] == "NewCo"
    assert sup["oldco"]["reason"] is None


def test_mark_superseded_with_when(kg):
    kg.mark_superseded("Alpha", "Beta", reason="pivot", when="2026-01-01")
    sup = kg.current_supersessions()
    assert "alpha" in sup


def test_invalidated_superseded_by_not_in_current(kg):
    """After the superseded_by triple is invalidated, it should not appear."""
    kg.mark_superseded("Old", "New", reason="r")
    assert "old" in kg.current_supersessions()
    kg.invalidate("Old", "superseded_by", "New")
    assert kg.current_supersessions() == {}


# ── C2: tool_kg_invalidate optional successor args ────────────────────────


def test_invalidate_with_successor_records_link(monkeypatch, config, palace_path, kg):
    import mempalace.mcp_server as mcp_server

    monkeypatch.setattr(mcp_server, "_config", config)
    monkeypatch.setattr(mcp_server, "_call_kg", lambda op: op(kg))
    out = mcp_server.tool_kg_invalidate(
        "Oldbrand",
        "is_brand",
        "active",
        successor_subject="Newbrand",
        successor_reason="rebrand",
    )
    assert out["superseded_by"] == "Newbrand"
    assert kg.current_supersessions()["oldbrand"]["new"] == "Newbrand"


def test_invalidate_without_successor_is_unchanged(monkeypatch, config, palace_path, kg):
    import mempalace.mcp_server as mcp_server

    monkeypatch.setattr(mcp_server, "_config", config)
    monkeypatch.setattr(mcp_server, "_call_kg", lambda op: op(kg))
    out = mcp_server.tool_kg_invalidate("Oldbrand", "is_brand", "active")
    assert "superseded_by" not in out
    assert kg.current_supersessions() == {}
