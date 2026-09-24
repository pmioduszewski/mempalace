"""The hybrid re-rank must see a reasonable candidate pool even for small limits.

Regression: the vector stage fetched only n_results * 3 rows, so a top-4 search
looked at 12 candidates and never saw a drawer the re-rank would rank first.
"""

import mempalace.searcher as searcher


def test_pool_has_a_floor_for_small_limits():
    assert searcher._rerank_pool_size(4) >= 50
    assert searcher._rerank_pool_size(1) >= 50


def test_pool_still_scales_for_large_limits():
    assert searcher._rerank_pool_size(40) == 120


def test_vector_query_uses_the_pool_floor(monkeypatch, palace_path, seeded_collection):
    seen = {}
    real_get = searcher.get_collection

    def spy_get_collection(*a, **k):
        col = real_get(*a, **k)
        orig_query = col.query

        def query(**kwargs):
            seen.setdefault("n_results", kwargs.get("n_results"))
            return orig_query(**kwargs)

        col.query = query
        return col

    monkeypatch.setattr(searcher, "get_collection", spy_get_collection)
    searcher.search_memories("anything", palace_path, n_results=4)
    assert seen["n_results"] >= 50


def test_hybrid_rerank_sees_the_whole_pool(monkeypatch, palace_path, seeded_collection):
    """The BM25 re-rank must run over the pool, not over the vector top-n."""
    seen = {}
    real = searcher._hybrid_rank

    def spy(hits, query):
        seen["pool"] = len(hits)
        return real(hits, query)

    monkeypatch.setattr(searcher, "_hybrid_rank", spy)
    res = searcher.search_memories("anything", palace_path, n_results=1)
    assert len(res["results"]) <= 1
    assert seen["pool"] > 1
