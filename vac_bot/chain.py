from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder, PromptTemplate
from langchain_core.runnables import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
import os
from pathlib import Path
from datetime import datetime, timezone
import json
import re
from .loader import VectordbRetriever
from db import get_settings

store = {}
BASE = Path(__file__).resolve().parent.parent
ATTRIBUTION_LOG = BASE / "attribution_events.jsonl"
_citation_pattern = re.compile(r"\[(\d+)\]")
_chains = {}

def build_prompt(settings):
    bot_name = settings.get("bot_name", "VALR-Bot")
    personality = settings.get("personality", "a helpful assistant")
    tone = settings.get("tone", "professional and clear")
    purpose = settings.get("purpose", "")
    instructions = settings.get("instructions", "")

    parts = [f"You are {bot_name} — {personality}."]
    if purpose:
        parts.append(f"\n\n{purpose}")
    parts.append(f"\n\nSpeak like: {tone}.")
    if instructions:
        parts.append(f"\n\n{instructions}")
    parts.append("\n\nUse the context below to answer. If the context is empty or does not contain relevant information to answer the question, do not make up an answer. Instead, follow the instructions above to redirect the user.")
    parts.append("\n\nContext:\n{context}")
    parts.append(
        "\n\nRules: answer only from the Context and the conversation history. "
        "If the Context does not directly contain the answer, say you are not sure and point to the knowledge base instead of guessing. "
        "Do not invent facts, news, or company details that are not in the Context. "
        "Every factual claim must include one or more inline citation markers like [1] or [2]. "
        "Use only citation numbers that appear in the Context."
    )

    return ChatPromptTemplate.from_messages([
        ("system", "".join(parts)),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])

def _build_document_prompt():
    return PromptTemplate.from_template("[{citation_id}] {page_content}")

def _extract_citation_ids(answer: str):
    return [int(match) for match in _citation_pattern.findall(answer or "")]

def _best_excerpt(text: str, query: str, max_chars: int = 360):
    if not text:
        return ""

    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.replace("\n", " ")) if part.strip()]
    if not sentences:
        return text[:max_chars].strip()

    query_terms = {term.lower() for term in re.findall(r"[A-Za-z0-9']+", query or "") if len(term) > 3}
    scored = []
    for index, sentence in enumerate(sentences):
        sentence_lower = sentence.lower()
        score = sum(1 for term in query_terms if term in sentence_lower)
        scored.append((score, index, sentence))

    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = []
    seen = set()
    for score, index, sentence in scored:
        if index in seen:
            continue
        selected.append((index, sentence))
        seen.add(index)
        if len(selected) >= 2:
            break

    selected.sort(key=lambda item: item[0])
    excerpt = " ".join(sentence for _, sentence in selected).strip()
    if not excerpt:
        excerpt = " ".join(sentences[:2]).strip()
    return excerpt[:max_chars].rstrip()

def _source_payload(doc, query: str, used: bool):
    metadata = doc.metadata or {}
    return {
        "citation_id": metadata.get("citation_id"),
        "used": used,
        "source_file": metadata.get("source_file") or metadata.get("source") or metadata.get("title"),
        "source_link": metadata.get("source_link") or metadata.get("source_file") or metadata.get("source"),
        "source_type": metadata.get("source_type"),
        "source_id": metadata.get("source_id"),
        "title": metadata.get("title"),
        "section_heading": metadata.get("section_heading"),
        "page_number": metadata.get("page_number"),
        "char_start": metadata.get("char_start"),
        "char_end": metadata.get("char_end"),
        "indexed_at": metadata.get("indexed_at"),
        "chunk_index": metadata.get("chunk_index"),
        "retrieval_score": metadata.get("retrieval_score"),
        "similarity_score": metadata.get("similarity_score"),
        "distance": metadata.get("distance"),
        "excerpt": _best_excerpt(doc.page_content, query),
        "page_content": doc.page_content,
    }

def _append_attribution_log(events):
    if not events:
        return
    try:
        ATTRIBUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ATTRIBUTION_LOG.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass

_build_error = None
_chain = None
PROVIDER_OPTIONS = {
    "openai":      {"label": "OpenAI",        "env_key": "OPENAI_API_KEY"},
    "azure_openai": {"label": "Azure OpenAI",  "env_key": "AZURE_OPENAI_API_KEY"},
    "anthropic":   {"label": "Anthropic",      "env_key": "ANTHROPIC_API_KEY"},
    "google":      {"label": "Google Gemini", "env_key": "GOOGLE_API_KEY"},
    "groq":        {"label": "Groq",           "env_key": "GROQ_API_KEY"},
    "openai_compat": {"label": "OpenAI-Compatible", "env_key": "CUSTOM_API_KEY"},
}

def _resolve_api_key(settings: dict) -> str:
    key = (settings.get("llm_api_key") or "").strip()
    if key:
        return key
    provider = (settings.get("llm_provider") or "openai").strip()
    info = PROVIDER_OPTIONS.get(provider, PROVIDER_OPTIONS["openai"])
    return os.getenv(info["env_key"], "")

def _build_llm(settings: dict) -> BaseChatModel:
    provider = (settings.get("llm_provider") or "openai").strip()
    model = (settings.get("llm_model") or "gpt-4o-mini").strip()
    api_key = _resolve_api_key(settings)
    base_url = (settings.get("llm_base_url") or "").strip() or None
    kwargs = {"temperature": 0, "model": model}
    if api_key:
        kwargs["api_key"] = api_key

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(**kwargs)
    elif provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        kwargs.pop("api_key", None)
        kwargs["google_api_key"] = api_key
        return ChatGoogleGenerativeAI(**kwargs)
    elif provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(**kwargs)
    elif provider == "azure_openai":
        from langchain_openai import AzureChatOpenAI
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", base_url or "")
        return AzureChatOpenAI(azure_endpoint=endpoint, api_version=api_version, **kwargs)
    else:
        from langchain_openai import ChatOpenAI
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOpenAI(**kwargs)

def _tenant_key(tenant_id):
    return str(tenant_id) if tenant_id is not None else "default"

def _history_key(tenant_id, sid):
    return (_tenant_key(tenant_id), sid)

def _ensure_chain(tenant_id=None):
    global _build_error
    tenant_key = _tenant_key(tenant_id)
    if tenant_key in _chains:
        return _chains[tenant_key]
    try:
        settings = get_settings()
        retriever = VectordbRetriever(k=5, tenant_id=tenant_key)
        llm = _build_llm(settings)
        qa_prompt = build_prompt(settings)
        question_answer_chain = create_stuff_documents_chain(
            llm,
            qa_prompt,
            document_prompt=_build_document_prompt(),
        )
        rag_chain = create_retrieval_chain(retriever, question_answer_chain)
        chain = RunnableWithMessageHistory(
            rag_chain,
            lambda sid: store.setdefault(_history_key(tenant_id, sid), ChatMessageHistory()),
            input_messages_key="input",
            history_messages_key="chat_history",
            output_messages_key="answer",
        )
        _chains[tenant_key] = chain
        return chain
    except Exception as e:
        _build_error = e
        raise

def rebuild_chain():
    global _build_error
    _chains.clear()
    _build_error = None

def count_tokens(text):
    if not text:
        return 0
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        pass
    return len(text.split())

async def ask(q: str, sid: str = "1", tenant_id=None):
    chain = _ensure_chain(tenant_id)
    result = await chain.ainvoke({"input": q}, {"configurable": {"session_id": sid}})
    answer = result["answer"]
    source_docs = result.get("context", [])
    used_citation_ids = sorted(set(_extract_citation_ids(answer)))
    citations = []
    attribution_events = []
    for doc in source_docs:
        citation = _source_payload(doc, q, doc.metadata.get("citation_id") in used_citation_ids)
        citations.append(citation)
        if citation["used"]:
            attribution_events.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": sid,
                "query": q,
                "citation_id": citation["citation_id"],
                "source_id": citation["source_id"],
                "source_file": citation["source_file"],
                "source_link": citation["source_link"],
                "source_type": citation["source_type"],
                "page_number": citation["page_number"],
                "char_start": citation["char_start"],
                "char_end": citation["char_end"],
                "retrieval_score": citation["retrieval_score"],
                "similarity_score": citation["similarity_score"],
                "distance": citation["distance"],
            })

    _append_attribution_log(attribution_events)
    context = " ".join(doc.page_content for doc in source_docs)
    return {
        "answer": answer,
        "citations": citations,
        "source_documents": citations,
        "used_citation_ids": used_citation_ids,
        "attribution_events": attribution_events,
        "input_tokens": count_tokens(q + context),
        "output_tokens": count_tokens(answer),
        "total_tokens": count_tokens(q + context + answer),
    }
