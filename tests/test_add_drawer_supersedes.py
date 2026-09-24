"""Tests for add_drawer supersedence hook + mark_superseded + list_supersedence."""

import mempalace.mcp_server as mcp_server


def _wire(monkeypatch, config):
    monkeypatch.setattr(mcp_server, "_config", config)


def test_supersedes_creates_edge_and_patches_metadata(
    monkeypatch, config, palace_path, kg, tmp_path
):
    _wire(monkeypatch, config)
    monkeypatch.setattr(
        mcp_server.palace_graph, "_get_tunnel_file", lambda *a, **k: str(tmp_path / "tunnels.json")
    )
    old = mcp_server.tool_add_drawer("brand", "decisions", "Active brand: Oldbrand. Domain oldbrand.com")
    new = mcp_server.tool_add_drawer(
        "brand",
        "decisions",
        "Rebrand: Oldbrand -> Newbrand",
        supersedes_drawer_id=old["drawer_id"],
        supersedes_reason="rebrand Oldbrand->Newbrand",
    )
    assert new["supersedence_edge_id"].startswith("sup_")
    fetched = mcp_server.tool_get_drawer(old["drawer_id"])
    assert fetched["metadata"]["status"] == "superseded"
    assert fetched["metadata"]["superseded_by_id"] == new["drawer_id"]


def test_supersedes_missing_predecessor_warns_no_edge(
    monkeypatch, config, palace_path, kg, tmp_path
):
    _wire(monkeypatch, config)
    monkeypatch.setattr(
        mcp_server.palace_graph, "_get_tunnel_file", lambda *a, **k: str(tmp_path / "tunnels.json")
    )
    res = mcp_server.tool_add_drawer(
        "brand", "decisions", "x", supersedes_drawer_id="drawer_does_not_exist"
    )
    assert res["success"] is True
    assert "warning" in res
    assert "supersedence_edge_id" not in res


def test_mark_superseded_links_two_existing(monkeypatch, config, palace_path, kg, tmp_path):
    _wire(monkeypatch, config)
    monkeypatch.setattr(
        mcp_server.palace_graph, "_get_tunnel_file", lambda *a, **k: str(tmp_path / "tunnels.json")
    )
    a = mcp_server.tool_add_drawer("w", "r", "old fact")
    b = mcp_server.tool_add_drawer("w", "r", "new fact")
    edge = mcp_server.tool_mark_superseded(a["drawer_id"], b["drawer_id"], reason="r")
    assert edge["kind"] == "supersedes"
    listed = mcp_server.tool_list_supersedence(a["drawer_id"])
    assert listed["superseded_by"][0]["successor"]["drawer_id"] == b["drawer_id"]


# ── #4: chunked/oversized predecessors must be fully hidden after supersedence ──


def test_chunked_predecessor_chunks_are_hidden_after_supersedence(
    monkeypatch, config, palace_path, kg, tmp_path
):
    """Superseding a chunked predecessor must stamp ALL its chunk rows as superseded.

    Bug: _apply_drawer_supersedence only patched the bare pred_id row (which
    doesn't exist on the oversized path — chunked drawers have no row at the
    logical id).  The individual {pred_id}_chunk_* rows had no status and
    remained visible as "current" after supersedence.

    After the fix, every chunk row with parent_drawer_id==pred_id must carry
    status=superseded and be excluded from default search results.
    """
    _wire(monkeypatch, config)
    monkeypatch.setattr(
        mcp_server.palace_graph, "_get_tunnel_file", lambda *a, **k: str(tmp_path / "tunnels.json")
    )

    col = mcp_server._get_collection(create=True)

    # Manually insert chunk rows simulating an oversized drawer.
    # Chunk rows have parent_drawer_id = logical drawer id but are stored
    # under {drawer_id}_chunk_000000 etc.
    pred_logical = "drawer_chunked_pred_abc"
    chunk_ids = [f"{pred_logical}_chunk_{i:06d}" for i in range(3)]
    col.upsert(
        ids=chunk_ids,
        documents=[
            "Old oldbrand brand notes chunk zero content here.",
            "Old oldbrand brand notes chunk one more detail.",
            "Old oldbrand brand notes chunk two final part.",
        ],
        metadatas=[
            {
                "wing": "brand",
                "room": "decisions",
                "source_file": "old_brand.md",
                "chunk_index": i,
                "parent_drawer_id": pred_logical,
                "filed_at": "2026-01-01T00:00:00",
            }
            for i in range(3)
        ],
    )

    # Also insert the predecessor bare row (optional — some callers use it as
    # a handle but it may be absent on the pure-chunked path).
    col.upsert(
        ids=[pred_logical],
        documents=["Old oldbrand brand notes (logical handle)"],
        metadatas=[
            {
                "wing": "brand",
                "room": "decisions",
                "source_file": "old_brand.md",
                "chunk_index": 0,
                "filed_at": "2026-01-01T00:00:00",
            }
        ],
    )

    # Add a successor drawer.
    new = mcp_server.tool_add_drawer("brand", "decisions", "New newbrand brand guidance")

    # Supersede: this must stamp all chunks, not just the bare logical row.
    mcp_server.tool_mark_superseded(pred_logical, new["drawer_id"], reason="rebrand")

    # Verify chunk rows now carry status=superseded.
    chunk_result = col.get(ids=chunk_ids, include=["metadatas"])
    for cid, meta in zip(chunk_result["ids"], chunk_result["metadatas"]):
        assert (meta or {}).get("status") == "superseded", (
            f"chunk {cid} must carry status=superseded after supersedence; got meta={meta}"
        )

    # Verify chunks are hidden in default search.
    from mempalace.searcher import search_memories

    res = search_memories("oldbrand brand notes", palace_path, n_results=10, include_superseded=False)
    returned_sources = {r.get("source_file") for r in res["results"]}
    assert "old_brand.md" not in returned_sources, (
        f"chunk rows from superseded predecessor must be hidden; got sources={returned_sources}"
    )


# ── Reachability: supersedence must work through the MCP tools/call path ──
# The handler supported it for months, but the tool schema did not declare the
# argument, and the dispatcher drops undeclared arguments. These tests go
# through handle_request so that gap cannot reopen.


def _call_add_drawer(arguments):
    import json

    resp = mcp_server.handle_request(
        {
            "method": "tools/call",
            "id": 1,
            "params": {"name": "mempalace_add_drawer", "arguments": arguments},
        }
    )
    assert "error" not in resp, resp
    return json.loads(resp["result"]["content"][0]["text"])


def test_add_drawer_schema_declares_supersedence():
    props = mcp_server.TOOLS["mempalace_add_drawer"]["input_schema"]["properties"]
    assert props["supersedes_drawer_ids"]["type"] == "array"
    assert "supersedes_reason" in props


def test_tools_call_add_drawer_supersedes_many_in_one_call(
    monkeypatch, config, palace_path, kg, tmp_path
):
    _wire(monkeypatch, config)
    monkeypatch.setattr(
        mcp_server.palace_graph, "_get_tunnel_file", lambda *a, **k: str(tmp_path / "tunnels.json")
    )
    a = mcp_server.tool_add_drawer("tooling", "email", "mailbox X is not connected")
    b = mcp_server.tool_add_drawer("tooling", "email", "search across all mailboxes crashes")
    new = _call_add_drawer(
        {
            "wing": "tooling",
            "room": "email",
            "content": "mailbox X works; search across all mailboxes fixed",
            "supersedes_drawer_ids": [a["drawer_id"], b["drawer_id"]],
            "supersedes_reason": "fixed and verified",
        }
    )
    assert new["success"] is True
    assert len(new["supersedence_edge_ids"]) == 2
    for old in (a, b):
        meta = mcp_server.tool_get_drawer(old["drawer_id"])["metadata"]
        assert meta["status"] == "superseded"
        assert meta["superseded_by_id"] == new["drawer_id"]


def test_pure_chunked_predecessor_superseded_by_logical_id(
    monkeypatch, config, palace_path, kg, tmp_path
):
    """Real palace shape: a long drawer has ONLY chunk rows, no row at its
    logical id. Superseding by the logical id must work and hide every chunk."""
    _wire(monkeypatch, config)
    monkeypatch.setattr(
        mcp_server.palace_graph, "_get_tunnel_file", lambda *a, **k: str(tmp_path / "tunnels.json")
    )
    col = mcp_server._get_collection(create=True)
    pred_logical = "drawer_pure_chunked_xyz"
    chunk_ids = [f"{pred_logical}_chunk_{i:06d}" for i in range(2)]
    col.upsert(
        ids=chunk_ids,
        documents=["stale rule part one", "stale rule part two"],
        metadatas=[
            {"wing": "notes", "room": "rules", "chunk_index": i, "parent_drawer_id": pred_logical}
            for i in range(2)
        ],
    )
    new = mcp_server.tool_add_drawer("notes", "rules", "current rule")
    edge = mcp_server.tool_mark_superseded(pred_logical, new["drawer_id"], reason="updated")
    assert edge["kind"] == "supersedes"
    metas = col.get(ids=chunk_ids, include=["metadatas"])["metadatas"]
    assert all(m["status"] == "superseded" for m in metas)
    assert all(m["superseded_by_id"] == new["drawer_id"] for m in metas)
