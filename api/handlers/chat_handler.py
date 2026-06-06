import asyncio
import concurrent.futures
from api.dto import ChatRequest, ChatResponse
from api.interfaces import SessionProvider
from vac_bot.chain import ask


class ChatHandler:
    def __init__(self, session_provider: SessionProvider):
        self._session = session_provider

    def ask_question(self, req: ChatRequest) -> ChatResponse:
        if not req.question:
            return ChatResponse(success=False, error="Question is required")

        self._session.set("session_id", req.session_id)

        result = self._run_async(ask(req.question, req.session_id, tenant_id=req.tenant_id))
        return ChatResponse(
            success=True,
            answer=result.get("answer", ""),
            input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("output_tokens", 0),
            total_tokens=result.get("total_tokens", 0),
        )

    @staticmethod
    def _run_async(coro):
        try:
            asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        except RuntimeError:
            return asyncio.run(coro)
