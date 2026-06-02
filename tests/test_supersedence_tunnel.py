"""Tests for directed supersedence edges in mempalace.palace_graph."""

from unittest.mock import MagicMock, patch

with patch.dict("sys.modules", {"chromadb": MagicMock()}):
    import mempalace.palace_graph as palace_graph


def _tmp_tunnels(monkeypatch, tmp_path):
    f = tmp_path / "tunnels.json"
    monkeypatch.setattr(palace_graph, "_get_tunnel_file", lambda *a, **k: str(f))
    monkeypatch.setattr(palace_graph, "_legacy_tunnel_file", lambda: str(tmp_path / "legacy.json"))
    monkeypatch.setattr(palace_graph, "_get_collection", lambda *a, **k: None)
    return f


class TestSupersedenceEdge:
    def test_directed_id_is_asymmetric(self, tmp_path, monkeypatch):
        _tmp_tunnels(monkeypatch, tmp_path)
        a = palace_graph.create_supersedence("w", "r", "old_d", "w", "r", "new_d", reason="x")
        b = palace_graph.create_supersedence("w", "r", "new_d", "w", "r", "old_d", reason="x")
        assert a["id"] != b["id"]
        assert a["id"].startswith("sup_")
        assert a["kind"] == "supersedes"
        assert a["predecessor"]["drawer_id"] == "old_d"
        assert a["successor"]["drawer_id"] == "new_d"

    def test_same_edge_twice_dedups_and_updates_reason(self, tmp_path, monkeypatch):
        _tmp_tunnels(monkeypatch, tmp_path)
        palace_graph.create_supersedence("w", "r", "old_d", "w", "r", "new_d", reason="v1")
        palace_graph.create_supersedence("w", "r", "old_d", "w", "r", "new_d", reason="v2")
        edges = [t for t in palace_graph._load_tunnels() if t.get("kind") == "supersedes"]
        assert len(edges) == 1
        assert edges[0]["reason"] == "v2"

    def test_coexists_with_explicit_and_topic(self, tmp_path, monkeypatch):
        _tmp_tunnels(monkeypatch, tmp_path)
        palace_graph.create_supersedence("w", "r", "old_d", "w", "r", "new_d", reason="x")
        # explicit tunnel write (col stub returns None → existence check allowed)
        palace_graph.create_tunnel("w", "r", "w2", "r2", label="rel", kind="explicit")
        kinds = {t.get("kind") for t in palace_graph._load_tunnels()}
        assert {"supersedes", "explicit"} <= kinds

    def test_list_supersedence_both_directions(self, tmp_path, monkeypatch):
        _tmp_tunnels(monkeypatch, tmp_path)
        palace_graph.create_supersedence("w", "r", "A", "w", "r", "B", reason="x")
        palace_graph.create_supersedence("w", "r", "B", "w", "r", "C", reason="y")
        out = palace_graph.list_supersedence("B")
        assert [e["successor"]["drawer_id"] for e in out["superseded_by"]] == ["C"]
        assert [e["predecessor"]["drawer_id"] for e in out["supersedes"]] == ["A"]

    def test_missing_drawer_id_raises(self, tmp_path, monkeypatch):
        _tmp_tunnels(monkeypatch, tmp_path)
        import pytest

        with pytest.raises(ValueError):
            palace_graph.create_supersedence("w", "r", "", "w", "r", "B", reason="x")
