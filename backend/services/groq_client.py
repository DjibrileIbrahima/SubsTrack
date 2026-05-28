import logging
import os

logger = logging.getLogger(__name__)

_client = None
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")


def _get_client():
    global _client
    if _client is not None:
        return _client
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    try:
        from groq import Groq
        _client = Groq(api_key=api_key)
        return _client
    except ImportError:
        logger.warning("groq package not installed")
        return None


def groq_model_call(system_prompt: str, user_prompt: str) -> str:
    """Sync model_call for use with run_subscription_pipeline."""
    client = _get_client()
    if client is None:
        raise RuntimeError("Groq client not available — set GROQ_API_KEY")

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=300,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content
