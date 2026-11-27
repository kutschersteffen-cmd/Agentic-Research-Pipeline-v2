from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import DocType, DocumentChunk


def _chunk(text, doc_type=DocType.ANNUAL_REPORT_10K, **kwargs):
    return DocumentChunk(doc_id="d1", company_id="c1", doc_type=doc_type, text=text, char_start=0, char_end=len(text), **kwargs)


def test_no_query_terms_returns_unranked_capped_list():
    chunks = [_chunk("alpha"), _chunk("beta"), _chunk("gamma")]
    result = select_relevant_chunks(chunks, [], max_chunks=2)
    assert result == chunks[:2]


def test_ranks_by_relevance_and_drops_zero_score_chunks():
    chunks = [
        _chunk("The company reported strong revenue growth in the automotive segment."),
        _chunk("Green capex increased significantly due to solar investments."),
        _chunk("Total employee headcount rose by five percent this year."),
        _chunk("Capital expenditure on renewable energy projects doubled."),
    ]
    result = select_relevant_chunks(chunks, ["green", "capex", "renewable"], max_chunks=10)
    texts = [c.text for c in result]
    assert texts[0] == chunks[1].text  # "Green capex..." should rank first
    assert chunks[2].text not in texts  # headcount chunk has zero term overlap, dropped


def test_doc_type_filter_excludes_other_types():
    chunks = [
        _chunk("green capex info", doc_type=DocType.ANNUAL_REPORT_10K),
        _chunk("green capex info", doc_type=DocType.SUSTAINABILITY_REPORT),
    ]
    result = select_relevant_chunks(chunks, ["capex"], doc_type_filter=[DocType.SUSTAINABILITY_REPORT])
    assert len(result) == 1
    assert result[0].doc_type == DocType.SUSTAINABILITY_REPORT


def test_require_hit_false_keeps_zero_score_chunks():
    chunks = [_chunk("totally unrelated text"), _chunk("green capex mentioned here")]
    result = select_relevant_chunks(chunks, ["capex"], require_hit=False)
    assert len(result) == 2


def test_fallback_to_all_when_nothing_matches():
    chunks = [_chunk("alpha text"), _chunk("beta text")]
    result = select_relevant_chunks(chunks, ["nonexistent-term-xyz"], fallback_to_all=True)
    assert len(result) == 2


def test_no_fallback_returns_empty_when_nothing_matches():
    chunks = [_chunk("alpha text"), _chunk("beta text")]
    result = select_relevant_chunks(chunks, ["nonexistent-term-xyz"], fallback_to_all=False)
    assert result == []


def test_empty_chunks_returns_empty():
    assert select_relevant_chunks([], ["anything"]) == []


def test_rerank_candidates_reorders_by_scorer_not_bm25(monkeypatch):
    from arp.retrieval import rerank

    chunks = [_chunk("capex capex capex"), _chunk("capex capex"), _chunk("capex"), _chunk("capex other other")]
    texts_seen = []

    def scorer(query, texts):
        texts_seen.append((query, list(texts)))
        return [0.1, 0.2, 0.9][: len(texts)]  # favours the 3rd-ranked chunk

    monkeypatch.setattr(rerank, "_score", scorer)
    result = select_relevant_chunks(chunks, ["capex"], max_chunks=2, rerank_candidates=3)
    assert len(texts_seen) == 1 and len(texts_seen[0][1]) == 3  # only the top rerank_candidates are scored
    assert texts_seen[0][0] == "capex"
    assert result[0].text == "capex"
    assert len(result) == 2


def test_rerank_applies_to_fallback_to_all_bm25(monkeypatch):
    from arp.retrieval import rerank

    chunks = [_chunk("alpha"), _chunk("beta"), _chunk("gamma")]
    monkeypatch.setattr(rerank, "_score", lambda q, texts: [0.1, 0.2, 0.9])
    result = select_relevant_chunks(
        chunks, ["nonexistent-term-xyz"], max_chunks=2, fallback_to_all=True, rerank_candidates=3
    )
    assert [c.text for c in result] == ["gamma", "beta"]


def test_rerank_applies_to_fallback_to_all_hybrid(monkeypatch):
    from arp.retrieval import rerank, select_evidence

    chunks = [_chunk("alpha"), _chunk("beta"), _chunk("gamma")]
    monkeypatch.setattr(select_evidence, "_vector_ranking", lambda candidates, query_text, store: [])
    monkeypatch.setattr(rerank, "_score", lambda q, texts: [0.1, 0.2, 0.9])
    result = select_relevant_chunks(
        chunks, ["nonexistent-term-xyz"], max_chunks=2, fallback_to_all=True, rerank_candidates=3,
        hybrid_retrieval_enabled=True, content_store=object(),
    )
    assert [c.text for c in result] == ["gamma", "beta"]


def test_rerank_unset_leaves_order_untouched(monkeypatch):
    from arp.retrieval import rerank

    monkeypatch.setattr(rerank, "_score", lambda q, texts: (_ for _ in ()).throw(AssertionError("scorer called")))
    chunks = [_chunk("capex capex"), _chunk("capex")]
    assert select_relevant_chunks(chunks, ["capex"], max_chunks=2)[0].text == "capex capex"


def test_concurrent_vector_rankings_embed_each_chunk_once(monkeypatch):
    import threading
    import time
    from collections import Counter

    import numpy as np

    from arp.retrieval import embeddings
    from arp.retrieval.select_evidence import _vector_ranking

    class _DictStore:  # the store's contract: lookup returns what was stored, storing a key again is harmless
        def __init__(self):
            self.rows = {}

        def lookup_embeddings(self, chunk_ids, model):
            return {i: self.rows[(i, model)] for i in chunk_ids if (i, model) in self.rows}

        def store_embeddings(self, vectors, model):
            for i, v in vectors.items():
                self.rows.setdefault((i, model), v)

    embedded = Counter()

    def _embed(texts):
        embedded.update(texts)
        time.sleep(0.05)  # long enough for the other field's lookup to see the same missing chunks
        return [np.ones(3, dtype=np.float32) for _ in texts]

    monkeypatch.setattr(embeddings, "embed_texts", _embed)
    chunks, store = [_chunk("alpha"), _chunk("beta")], _DictStore()
    barrier = threading.Barrier(2)

    def _rank():
        barrier.wait()
        _vector_ranking(chunks, "query", store)

    threads = [threading.Thread(target=_rank) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert (embedded["alpha"], embedded["beta"]) == (1, 1)


def test_reports_an_unranked_fallback_only(monkeypatch):
    from arp.retrieval import rerank

    monkeypatch.setattr(rerank, "_score", lambda q, texts: [0.0] * len(texts))
    chunks, calls = [_chunk("alpha"), _chunk("beta")], []
    flag = lambda: calls.append(1)  # noqa: E731
    select_relevant_chunks(chunks, ["zzz"], fallback_to_all=True, on_unranked_fallback=flag)
    assert calls == [1]
    select_relevant_chunks(chunks, ["alpha"], fallback_to_all=True, on_unranked_fallback=flag)  # a hit: BM25 ranked
    select_relevant_chunks(chunks, ["zzz"], fallback_to_all=True, rerank_candidates=2, on_unranked_fallback=flag)
    assert calls == [1]
