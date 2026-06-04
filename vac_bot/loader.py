from pathlib import Path
import os
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
from langchain_core.retrievers import BaseRetriever
from .static_faq import STATIC_FAQ
from db import get_conn, get_next_version

BASE = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

VEKTORDB_URL = os.getenv("VEKTORDB_URL", "http://vectordb:5001")

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _tenant_headers(tenant_id):
    if tenant_id is None:
        return {}
    return {"X-Tenant-Id": str(tenant_id)}

def load_urls_from_db(tenant_id=None):
    conn = get_conn()
    if tenant_id is None:
        rows = conn.execute("SELECT id, url FROM urls").fetchall()
    else:
        rows = conn.execute("SELECT id, url FROM urls WHERE tenant_id=?", (tenant_id,)).fetchall()
    conn.close()
    return [{"id": r["id"], "url": r["url"]} for r in rows]

def load_pdfs_from_db(tenant_id=None):
    conn = get_conn()
    if tenant_id is None:
        rows = conn.execute("SELECT id, filename, filepath FROM documents WHERE doc_type IS NULL OR doc_type='' OR doc_type='pdf'").fetchall()
    else:
        rows = conn.execute("SELECT id, filename, filepath FROM documents WHERE tenant_id=? AND (doc_type IS NULL OR doc_type='' OR doc_type='pdf')", (tenant_id,)).fetchall()
    conn.close()
    return [{"id": r["id"], "filename": r["filename"], "filepath": r["filepath"]} for r in rows]

def load_multimodal_from_db(tenant_id=None, doc_type=None):
    conn = get_conn()
    query = "SELECT id, filename, filepath, doc_type FROM documents"
    params = []
    conditions = []
    if tenant_id is not None:
        conditions.append("tenant_id=?")
        params.append(tenant_id)
    if doc_type is not None:
        conditions.append("doc_type=?")
        params.append(doc_type)
    else:
        conditions.append("doc_type IN ('image','table','slides','scanned')")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY id"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [{"id": r["id"], "filename": r["filename"], "filepath": r["filepath"], "doc_type": r["doc_type"]} for r in rows]

def scrape_url(url, timeout=30):
    resp = requests.get(url, headers=REQUEST_HEADERS, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "lxml")

        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()

        content = None
        for selector in [
            "article",
            "main",
            "[role='main']",
            ".post-content",
            ".article-content",
            ".entry-content",
            "#content",
            "#main",
            ".content",
            ".body",
        ]:
            elem = soup.select_one(selector)
            if elem and len(elem.get_text(strip=True)) > 200:
                content = elem
                break

        if content is None:
            content = soup.body or soup

        text = content.get_text(separator="\n", strip=True)
        return text, title
    except ImportError:
        from langchain_community.document_loaders import WebBaseLoader
        loader = WebBaseLoader([url])
        docs = loader.load()
        title = url
        text = docs[0].page_content if docs else ""
        return text, title

def extract_pdf_text(filepath):
    from pypdf import PdfReader
    reader = PdfReader(filepath)
    pages = []
    for page_number, page in enumerate(reader.pages, start=1):
        t = page.extract_text()
        if t:
            pages.append({"page_number": page_number, "text": t})
    return pages

def chunk_source_text(text, base_metadata, splitter, indexed_at):
    chunks = []
    chunk_texts = splitter.split_text(text)
    cursor = 0
    overlap = getattr(splitter, "_chunk_overlap", 0) or 0

    for chunk_index, chunk_text in enumerate(chunk_texts):
        search_start = max(0, cursor - overlap)
        start = text.find(chunk_text, search_start)
        if start < 0:
            start = search_start
        end = min(len(text), start + len(chunk_text))
        cursor = end

        metadata = dict(base_metadata)
        metadata.update({
            "chunk_index": chunk_index,
            "char_start": start,
            "char_end": end,
            "indexed_at": indexed_at,
        })
        chunks.append(Document(page_content=chunk_text, metadata=metadata))

    return chunks

def collect_documents(tenant_id=None):
    all_docs = []
    errors = []
    now = datetime.now(timezone.utc).isoformat()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
    )

    url_entries = load_urls_from_db(tenant_id=tenant_id)
    for entry in url_entries:
        try:
            text, title = scrape_url(entry["url"])
            version = get_next_version("url", entry["url"])
            if text.strip():
                all_docs.extend(chunk_source_text(
                    text,
                    {
                        "source": entry["url"],
                        "source_link": entry["url"],
                        "source_file": entry["url"],
                        "source_type": "url",
                        "title": title or entry["url"],
                        "section_heading": title or entry["url"],
                        "page_number": None,
                        "timestamp": now,
                        "version": version,
                        "source_id": str(entry["id"]),
                    },
                    splitter,
                    now,
                ))
                print(f"Scraped URL: {entry['url']} ({len(text)} chars)")
            else:
                msg = f"URL returned empty content: {entry['url']}"
                print(msg)
                errors.append(msg)
        except Exception as e:
            msg = f"URL scrape failed ({entry['url']}): {e}"
            print(msg)
            errors.append(msg)

    pdf_entries = load_pdfs_from_db(tenant_id=tenant_id)
    for entry in pdf_entries:
        try:
            version = get_next_version("pdf", entry["id"])
            pages = extract_pdf_text(entry["filepath"])
            pdf_chunks = []
            for page in pages:
                page_text = page["text"]
                if not page_text.strip():
                    continue
                pdf_chunks.extend(chunk_source_text(
                    page_text,
                    {
                        "source": f"pdf:{entry['filename']}",
                        "source_link": entry["filepath"],
                        "source_file": entry["filepath"],
                        "source_type": "pdf",
                        "title": entry["filename"],
                        "section_heading": entry["filename"],
                        "page_number": page["page_number"],
                        "timestamp": now,
                        "version": version,
                        "source_id": str(entry["id"]),
                    },
                    splitter,
                    now,
                ))
            if pdf_chunks:
                all_docs.extend(pdf_chunks)
                print(f"Extracted PDF: {entry['filename']} ({len(pdf_chunks)} chunks)")
            else:
                msg = f"PDF ({entry['filename']}) extracted but empty"
                print(msg)
                errors.append(msg)
        except Exception as e:
            msg = f"PDF failed ({entry['filename']}): {e}"
            print(msg)
            errors.append(msg)

    for i, faq in enumerate(STATIC_FAQ):
        text = f"Q: {faq['question']}\nA: {faq['answer']}"
        all_docs.extend(chunk_source_text(
            text,
            {
                "source": "static",
                "source_link": "static_faq",
                "source_file": "static_faq",
                "source_type": "static",
                "title": faq["question"][:80],
                "section_heading": faq["question"][:80],
                "page_number": None,
                "timestamp": now,
                "version": 1,
                "source_id": f"static_{i}",
            },
            splitter,
            now,
        ))

    multimodal_entries = load_multimodal_from_db(tenant_id=tenant_id)
    for entry in multimodal_entries:
        try:
            version = get_next_version(entry["doc_type"], entry["id"])
            base_meta = {
                "source": f"{entry['doc_type']}:{entry['filename']}",
                "source_link": entry["filepath"],
                "source_file": entry["filepath"],
                "source_type": entry["doc_type"],
                "title": entry["filename"],
                "section_heading": entry["filename"],
                "page_number": None,
                "timestamp": now,
                "version": version,
                "source_id": str(entry["id"]),
            }

            if entry["doc_type"] == "image":
                from vac_bot.multimodal import extract_image_text
                text = extract_image_text(entry["filepath"])
                if text.strip():
                    all_docs.extend(chunk_source_text(text, dict(base_meta), splitter, now))
                    print(f"Extracted image: {entry['filename']} ({len(text)} chars)")

            elif entry["doc_type"] == "table":
                from vac_bot.multimodal import extract_table_text
                text = extract_table_text(entry["filepath"])
                if text.strip():
                    all_docs.extend(chunk_source_text(text, dict(base_meta), splitter, now))
                    print(f"Extracted table: {entry['filename']} ({len(text)} chars)")

            elif entry["doc_type"] == "slides":
                from vac_bot.multimodal import extract_slides_text
                slides = extract_slides_text(entry["filepath"])
                for slide in slides:
                    meta = dict(base_meta)
                    meta["page_number"] = slide["slide_number"]
                    meta["section_heading"] = f"{entry['filename']} — Slide {slide['slide_number']}"
                    all_docs.extend(chunk_source_text(slide["text"], meta, splitter, now))
                print(f"Extracted slides: {entry['filename']} ({len(slides)} slides)")

            elif entry["doc_type"] == "scanned":
                from vac_bot.multimodal import extract_scanned_pdf_text
                pages = extract_scanned_pdf_text(entry["filepath"])
                for page in pages:
                    meta = dict(base_meta)
                    meta["page_number"] = page["page_number"]
                    meta["section_heading"] = f"{entry['filename']} — Page {page['page_number']}"
                    all_docs.extend(chunk_source_text(page["text"], meta, splitter, now))
                print(f"Extracted scanned PDF: {entry['filename']} ({len(pages)} pages)")

        except Exception as e:
            msg = f"{entry['doc_type']} failed ({entry['filename']}): {e}"
            print(msg)
            errors.append(msg)

    return all_docs, errors

def rebuild_vectordb(tenant_id=None):
    chunks, errors = collect_documents(tenant_id=tenant_id)
    payload = {
        "documents": [
            {"page_content": d.page_content, "metadata": d.metadata}
            for d in chunks
        ]
    }
    print(f"Sending {len(chunks)} chunks to vectordb...")
    resp = requests.post(
        f"{VEKTORDB_URL}/rebuild",
        json=payload,
        headers=_tenant_headers(tenant_id),
        timeout=300,
    )
    resp.raise_for_status()
    result = resp.json()
    result["warnings"] = errors

    try:
        from db import mark_indexed
        url_ids = sorted({d.metadata.get("source_id") for d in chunks if d.metadata.get("source_type") == "url" and d.metadata.get("source_id")})
        pdf_ids = sorted({int(d.metadata.get("source_id")) for d in chunks if d.metadata.get("source_type") == "pdf" and d.metadata.get("source_id")})
        if url_ids:
            mark_indexed("url", url_ids)
        if pdf_ids:
            mark_indexed("pdf", pdf_ids)
        for dt in ("image", "table", "slides", "scanned"):
            ids = sorted({int(d.metadata.get("source_id")) for d in chunks if d.metadata.get("source_type") == dt and d.metadata.get("source_id")})
            if ids:
                mark_indexed(dt, ids)
    except Exception:
        pass

    print(f"Vectordb rebuilt: {result}")
    return result

class VectordbRetriever(BaseRetriever):
    k: int = 5
    max_distance: float = 0.75
    tenant_id: str | int | None = None

    def _get_relevant_documents(self, query: str):
        try:
            resp = requests.post(
                f"{VEKTORDB_URL}/search",
                json={"query": query, "k": self.k},
                headers=_tenant_headers(self.tenant_id),
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            docs = []
            for d in data.get("documents", []):
                score = d.get("score")
                if score is not None and score > self.max_distance:
                    continue
                metadata = dict(d.get("metadata", {}))
                metadata["retrieval_score"] = score
                if isinstance(score, (int, float)):
                    metadata["distance"] = float(score)
                    metadata["similarity_score"] = max(0.0, 1.0 - float(score))
                docs.append(Document(page_content=d["page_content"], metadata=metadata))
            for citation_id, doc in enumerate(docs, start=1):
                doc.metadata["citation_id"] = citation_id
            if not docs:
                print(f"Vectordb returned no confident matches for: {query}")
            return docs
        except Exception as e:
            print(f"Vectordb search failed: {e}")
            return []

    async def _aget_relevant_documents(self, query: str):
        return self._get_relevant_documents(query)