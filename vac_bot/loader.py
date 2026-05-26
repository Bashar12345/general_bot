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

def load_urls_from_db():
    conn = get_conn()
    rows = conn.execute("SELECT id, url FROM urls").fetchall()
    conn.close()
    return [{"id": r["id"], "url": r["url"]} for r in rows]

def load_pdfs_from_db():
    conn = get_conn()
    rows = conn.execute("SELECT id, filename, filepath FROM documents").fetchall()
    conn.close()
    return [{"id": r["id"], "filename": r["filename"], "filepath": r["filepath"]} for r in rows]

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
    for page in reader.pages:
        t = page.extract_text()
        if t:
            pages.append(t)
    return "\n".join(pages)

def collect_documents():
    all_docs = []
    errors = []
    now = datetime.now(timezone.utc).isoformat()

    url_entries = load_urls_from_db()
    for entry in url_entries:
        try:
            text, title = scrape_url(entry["url"])
            version = get_next_version("url", entry["url"])
            if text.strip():
                all_docs.append(Document(
                    page_content=text,
                    metadata={
                        "source": entry["url"],
                        "source_type": "url",
                        "title": title or entry["url"],
                        "timestamp": now,
                        "version": version,
                        "source_id": str(entry["id"]),
                    }
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

    pdf_entries = load_pdfs_from_db()
    for entry in pdf_entries:
        try:
            text = extract_pdf_text(entry["filepath"])
            version = get_next_version("pdf", entry["id"])
            if text.strip():
                all_docs.append(Document(
                    page_content=text,
                    metadata={
                        "source": f"pdf:{entry['filename']}",
                        "source_type": "pdf",
                        "title": entry["filename"],
                        "timestamp": now,
                        "version": version,
                        "source_id": str(entry["id"]),
                    }
                ))
                print(f"Extracted PDF: {entry['filename']} ({len(text)} chars)")
            else:
                msg = f"PDF ({entry['filename']}) extracted but empty"
                print(msg)
                errors.append(msg)
        except Exception as e:
            msg = f"PDF failed ({entry['filename']}): {e}"
            print(msg)
            errors.append(msg)

    for i, faq in enumerate(STATIC_FAQ):
        all_docs.append(Document(
            page_content=f"Q: {faq['question']}\nA: {faq['answer']}",
            metadata={
                "source": "static",
                "source_type": "static",
                "title": faq["question"][:80],
                "timestamp": now,
                "version": 1,
                "source_id": f"static_{i}",
            }
        ))

    if not all_docs:
        for i, faq in enumerate(STATIC_FAQ):
            all_docs.append(Document(
                page_content=f"Q: {faq['question']}\nA: {faq['answer']}",
                metadata={
                    "source": "static",
                    "source_type": "static",
                    "title": faq["question"][:80],
                    "timestamp": now,
                    "version": 1,
                    "source_id": f"static_{i}",
                }
            ))

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
    )
    chunks = splitter.split_documents(all_docs)

    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = i

    return chunks, all_docs, errors

def rebuild_vectordb():
    chunks, raw, errors = collect_documents()
    payload = {
        "documents": [
            {"page_content": d.page_content, "metadata": d.metadata}
            for d in chunks
        ]
    }
    print(f"Sending {len(chunks)} chunks to vectordb...")
    resp = requests.post(f"{VEKTORDB_URL}/rebuild", json=payload, timeout=300)
    resp.raise_for_status()
    result = resp.json()
    result["warnings"] = errors

    from db import mark_indexed
    url_ids = list(set(d.metadata.get("source_id") for d in raw if d.metadata.get("source_type") == "url" and d.metadata.get("source_id")))
    pdf_ids = list(set(int(d.metadata["source_id"]) for d in raw if d.metadata.get("source_type") == "pdf" and d.metadata.get("source_id")))
    if url_ids:
        mark_indexed("url", url_ids)
    if pdf_ids:
        mark_indexed("pdf", pdf_ids)

    print(f"Vectordb rebuilt: {result}")
    return result

class VectordbRetriever(BaseRetriever):
    k: int = 5
    max_distance: float = 0.75

    def _get_relevant_documents(self, query: str):
        try:
            resp = requests.post(
                f"{VEKTORDB_URL}/search",
                json={"query": query, "k": self.k},
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            docs = []
            for d in data.get("documents", []):
                score = d.get("score")
                if score is not None and score > self.max_distance:
                    continue
                docs.append(Document(page_content=d["page_content"], metadata=d.get("metadata", {})))
            if not docs:
                print(f"Vectordb returned no confident matches for: {query}")
            return docs
        except Exception as e:
            print(f"Vectordb search failed: {e}")
            return []

    async def _aget_relevant_documents(self, query: str):
        return self._get_relevant_documents(query)