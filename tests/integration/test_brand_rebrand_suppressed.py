"""Integration test: retired-brand suppress + annotate scenario.

Uses real tool_add_drawer (with supersedes_drawer_id), tool_kg_invalidate
(with successor_subject), and tool_search; asserts:
  (a) the replaced predecessor drawer is SUPPRESSED by default
  (b) the renewal-email drawer SURVIVES
  (c) the email row is ANNOTATED with the superseded entity
"""

import mempalace.mcp_server as mcp_server
import mempalace.palace_graph as palace_graph
import mempalace.searcher as searcher


def test_brand_rebrand_suppress_and_annotate(monkeypatch, config, palace_path, kg, tmp_path):
    monkeypatch.setattr(mcp_server, "_config", config)
    monkeypatch.setattr(mcp_server, "_call_kg", lambda op: op(kg))
    monkeypatch.setattr(
        palace_graph, "_get_tunnel_file", lambda *a, **k: str(tmp_path / "tunnels.json")
    )
    monkeypatch.setattr(searcher, "_kg_path_for_palace", lambda p: kg.db_path, raising=False)

    a = mcp_server.tool_add_drawer("brand", "decisions", "Active brand: Oldbrand. Domain: oldbrand.com")
    _b = mcp_server.tool_add_drawer(
        "brand",
        "decisions",
        "Rebrand decision: Oldbrand -> Newbrand, effective 2026-02-01",
        supersedes_drawer_id=a["drawer_id"],
        supersedes_reason="rebrand Oldbrand->Newbrand",
    )
    c = mcp_server.tool_add_drawer(
        "email", "inbox", "Reminder: renew oldbrand.com domain by 2026-12-15."
    )
    mcp_server.tool_kg_invalidate(
        "Oldbrand", "is_brand", "active", successor_subject="Newbrand", successor_reason="rebrand"
    )

    res = mcp_server.tool_search(query="Oldbrand domain renewal", limit=10)
    ids = {r["drawer_id"] for r in res["results"]}

    # replaced-fact: predecessor drawer A is suppressed by default
    assert a["drawer_id"] not in ids
    # renewal email C survives
    assert c["drawer_id"] in ids
    # entity-level: C's row flagged because it mentions superseded "Oldbrand"/"oldbrand.com"
    crow = next(r for r in res["results"] if r["drawer_id"] == c["drawer_id"])
    assert any("newbrand" in e["new"].lower() for e in crow.get("superseded_entities", []))
