from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from .loader import VectordbRetriever
from db import get_settings

store = {}

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
        "Do not invent facts, news, or company details that are not in the Context."
    )

    return ChatPromptTemplate.from_messages([
        ("system", "".join(parts)),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])

_build_error = None
_chain = None
def _ensure_chain():
    global _chain, _build_error
    if _chain is not None:
        return
    try:
        settings = get_settings()
        retriever = VectordbRetriever(k=5)
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        qa_prompt = build_prompt(settings)
        question_answer_chain = create_stuff_documents_chain(llm, qa_prompt)
        rag_chain = create_retrieval_chain(retriever, question_answer_chain)
        _chain = RunnableWithMessageHistory(
            rag_chain,
            lambda sid: store.setdefault(sid, ChatMessageHistory()),
            input_messages_key="input",
            history_messages_key="chat_history",
            output_messages_key="answer",
        )
    except Exception as e:
        _build_error = e
        raise

def rebuild_chain():
    global _chain, _build_error
    _chain = None
    _build_error = None

_enc = None
def count_tokens(text):
    global _enc
    if _enc is None:
        import tiktoken
        _enc = tiktoken.encoding_for_model("gpt-4o-mini")
    return len(_enc.encode(text)) if text else 0

async def ask(q: str, sid: str = "1"):
    if _chain is None:
        _ensure_chain()
    result = await _chain.ainvoke({"input": q}, {"configurable": {"session_id": sid}})
    answer = result["answer"]
    context = " ".join(doc.page_content for doc in result.get("context", []))
    return {
        "answer": answer,
        "input_tokens": count_tokens(q + context),
        "output_tokens": count_tokens(answer),
        "total_tokens": count_tokens(q + context + answer),
    }
