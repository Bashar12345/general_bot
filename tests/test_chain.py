from vac_bot.chain import build_prompt


def test_build_prompt_keeps_strict_context_rules():
    prompt = build_prompt(
        {
            "bot_name": "VALR-Bot",
            "personality": "a concise assistant",
            "tone": "clear and professional",
            "purpose": "Answer from the knowledge base only.",
            "instructions": "Never guess.",
        }
    )

    system_message = prompt.format_messages(
        context="Known context",
        chat_history=[],
        input="ajker khobor bolo",
    )[0].content

    assert "You are VALR-Bot" in system_message
    assert "Answer from the knowledge base only." in system_message
    assert "Never guess." in system_message
    assert "Use the context below to answer" in system_message
    assert "Do not invent facts" in system_message
