import os
import shutil
import re
from pathlib import Path
from flask import Flask, request, jsonify
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain.schema import Document
from dotenv import load_dotenv
import chromadb
from chromadb.config import Settings
from chromadb.telemetry.product import ProductTelemetryClient, ProductTelemetryEvent
from overrides import override

load_dotenv()

app = Flask(__name__)
BASE = Path(__file__).resolve().parent
CHROMA_DIR = BASE / "chroma"
CHROMA_DIR.mkdir(exist_ok=True)

COLLECTION_NAME = "langchain"
embeddings = OpenAIEmbeddings()
_db = None
_dbs = {}
_client = None


class NoOpProductTelemetryClient(ProductTelemetryClient):
    @override
    def capture(self, event: ProductTelemetryEvent) -> None:
        return


_chroma_settings = Settings(
    anonymized_telemetry=False,
    is_persistent=True,
    persist_directory=str(CHROMA_DIR),
    chroma_product_telemetry_impl="app.NoOpProductTelemetryClient",
    chroma_telemetry_impl="app.NoOpProductTelemetryClient",
)

def _get_or_create_client():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=_chroma_settings,
        )
    return _client


def _tenant_id_from_request():
    tenant_id = request.headers.get("X-Tenant-Id")
    if tenant_id is None or not str(tenant_id).strip():
        return None
    return str(tenant_id).strip()


def _collection_name_for_tenant(tenant_id=None):
    if tenant_id is None:
        return COLLECTION_NAME
    safe_tenant_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(tenant_id).strip())
    return f"kb_{safe_tenant_id}"

def _load_or_create_db(tenant_id=None):
    global _db, _client, _dbs
    sqlite_file = CHROMA_DIR / "chroma.sqlite3"
    if sqlite_file.exists() and sqlite_file.stat().st_size == 0:
        sqlite_file.unlink()
        print("Removed 0-byte chroma.sqlite3")
    try:
        client = _get_or_create_client()
        collection_name = _collection_name_for_tenant(tenant_id)
        client.get_or_create_collection(name=collection_name)
        _db = Chroma(
            embedding_function=embeddings,
            client=client,
            collection_name=collection_name,
        )
        _dbs[collection_name] = _db
        print(f"ChromaDB ready at {CHROMA_DIR}")
    except Exception as e:
        print(f"Creating fresh ChromaDB collection failed: {e}")
    return _db

def get_db(tenant_id=None):
    global _db, _dbs
    collection_name = _collection_name_for_tenant(tenant_id)
    if tenant_id is None and _db is not None:
        return _db
    if collection_name in _dbs:
        return _dbs[collection_name]
    return _load_or_create_db(tenant_id)


def _clear_collection_for_tenant(tenant_id=None):
    global _db, _dbs
    collection_name = _collection_name_for_tenant(tenant_id)
    try:
        client = _get_or_create_client()
        client.delete_collection(name=collection_name)
    except Exception:
        pass
    _dbs.pop(collection_name, None)
    if tenant_id is None:
        _db = None
    _load_or_create_db(tenant_id)

def _clear_chroma_dir():
    global _db, _client
    _db = None
    if _client is not None:
        _client.clear_system_cache()
    _client = None

    if CHROMA_DIR.exists():
        try:
            for item in CHROMA_DIR.iterdir():
                if item.is_dir():
                    shutil.rmtree(str(item))
                else:
                    item.unlink()
        except OSError as e:
            print(f"Could not clear DB dir: {e}")
    CHROMA_DIR.mkdir(exist_ok=True)

@app.route("/health")
def health():
    db = get_db(_tenant_id_from_request())
    if db is None:
        return jsonify({"status": "error", "index_loaded": False})
    return jsonify({"status": "ok", "index_loaded": True})

@app.route("/search", methods=["POST"])
def search():
    data = request.json or {}
    query = data.get("query", "")
    k = data.get("k", 5)
    tenant_id = _tenant_id_from_request()
    db = get_db(tenant_id)
    if db is None:
        print("Search called but DB is not available")
        return jsonify({"documents": []})
    try:
        docs = db.similarity_search_with_score(query, k=k)
        return jsonify({
            "documents": [
                {"page_content": d[0].page_content, "metadata": d[0].metadata, "score": float(d[1])}
                for d in docs
            ]
        })
    except Exception as e:
        print(f"Search failed: {e}")
        return jsonify({"documents": [], "error": str(e)}), 500

@app.route("/rebuild", methods=["POST"])
def rebuild():
    # Properly reset chromadb client internals before tearing down directory 
    if chromadb.api.client.SharedSystemClient._identifier_to_system:
        chromadb.api.client.SharedSystemClient.clear_system_cache()
        
    tenant_id = _tenant_id_from_request()
    
    data = request.json or {}
    docs_data = data.get("documents", [])
    docs = [Document(page_content=d["page_content"], metadata=d.get("metadata", {})) for d in docs_data]
    
    global _db
    if not docs:
        _load_or_create_db(tenant_id)
        return jsonify({"status": "ok", "count": 0, "warning": "no documents provided"})
        
    client = _get_or_create_client()
    try:
        collection_name = _collection_name_for_tenant(tenant_id)
        client.get_or_create_collection(name=collection_name)
        _db = Chroma.from_documents(
            docs, embeddings,
            client=client,
            collection_name=collection_name,
        )
        _dbs[collection_name] = _db
        print(f"Rebuilt ChromaDB index with {len(docs)} chunks")
        return jsonify({"status": "ok", "count": len(docs)})
    except Exception as e:
        print(f"Failed Chroma DB rebuild from documents {e}")
        return jsonify({"status": "error", "count": 0}), 500

@app.route("/clear", methods=["POST"])
def clear():
    if chromadb.api.client.SharedSystemClient._identifier_to_system:
        chromadb.api.client.SharedSystemClient.clear_system_cache()
    tenant_id = _tenant_id_from_request()
    if tenant_id is None:
        _clear_chroma_dir()
        _load_or_create_db()
    else:
        _clear_collection_for_tenant(tenant_id)
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)
