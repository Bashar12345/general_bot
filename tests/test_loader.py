from langchain.schema import Document

from vac_bot import loader


def test_collect_documents_combines_url_pdf_and_static_docs(monkeypatch):
    monkeypatch.setattr(loader, "load_urls_from_db", lambda: [{"id": 1, "url": "https://example.com"}])
    monkeypatch.setattr(loader, "load_pdfs_from_db", lambda: [{"id": 2, "filename": "news.pdf", "filepath": "/tmp/news.pdf"}])
    monkeypatch.setattr(loader, "scrape_url", lambda url: ("url body", "Example Title"))
    monkeypatch.setattr(loader, "extract_pdf_text", lambda filepath: "pdf body")
    monkeypatch.setattr(loader, "get_next_version", lambda source_type, source_id: 7)
    monkeypatch.setattr(loader, "STATIC_FAQ", [{"question": "faq q", "answer": "faq a"}], raising=False)

    chunks, raw_docs, errors = loader.collect_documents()

    assert errors == []
    assert [doc.metadata["source_type"] for doc in raw_docs] == ["url", "pdf", "static"]
    assert [doc.metadata["source"] for doc in raw_docs] == [
        "https://example.com",
        "pdf:news.pdf",
        "static",
    ]
    assert all("chunk_index" in chunk.metadata for chunk in chunks)
    assert chunks[0].metadata["chunk_index"] == 0


def test_rebuild_vectordb_posts_payload_and_marks_indexed(monkeypatch):
    chunks = [
        Document(page_content="url chunk", metadata={"source_type": "url", "source_id": "11", "source": "https://example.com"}),
        Document(page_content="pdf chunk", metadata={"source_type": "pdf", "source_id": "22", "source": "pdf:news.pdf"}),
    ]
    raw_docs = [
        Document(page_content="url raw", metadata={"source_type": "url", "source_id": "11"}),
        Document(page_content="pdf raw", metadata={"source_type": "pdf", "source_id": "22"}),
    ]

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "ok", "count": 2}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["payload"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    mark_calls = []

    def fake_mark_indexed(source_type, source_ids):
        mark_calls.append((source_type, sorted(source_ids)))

    monkeypatch.setattr(loader, "collect_documents", lambda: (chunks, raw_docs, ["warn"]))
    monkeypatch.setattr(loader.requests, "post", fake_post)
    monkeypatch.setattr("db.mark_indexed", fake_mark_indexed)

    result = loader.rebuild_vectordb()

    assert captured["url"] == "http://vectordb:5001/rebuild"
    assert captured["timeout"] == 300
    assert len(captured["payload"]["documents"]) == 2
    assert result["status"] == "ok"
    assert result["warnings"] == ["warn"]
    assert mark_calls == [("url", ["11"]), ("pdf", [22])]


def test_vectordb_retriever_filters_high_distance_matches(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "documents": [
                    {"page_content": "keep me", "metadata": {"source": "news"}, "score": 0.32},
                    {"page_content": "drop me", "metadata": {"source": "static"}, "score": 0.91},
                ]
            }

    monkeypatch.setattr(loader.requests, "post", lambda *args, **kwargs: FakeResponse())

    retriever = loader.VectordbRetriever(k=2)
    docs = retriever._get_relevant_documents("ajker khobor bolo")

    assert [doc.page_content for doc in docs] == ["keep me"]
