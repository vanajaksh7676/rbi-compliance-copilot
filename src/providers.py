"""One place to choose which AI service the project uses. Settings come from .env:

    EMBED_PROVIDER=openai      # or fastembed (free, runs on your CPU, slow on an i3)
    LLM_PROVIDER=openai        # or groq (free tier)
    OPENAI_API_KEY=...
    OPENAI_MODEL=...           # copy the exact model ID from your OpenAI dashboard
    OPENAI_EMBED_MODEL=text-embedding-3-small
    GROQ_API_KEY=...           # only needed when LLM_PROVIDER=groq
    GROQ_MODEL=openai/gpt-oss-120b
"""
import os

from dotenv import load_dotenv

load_dotenv()

EMBED_PROVIDER = os.getenv("EMBED_PROVIDER", "openai")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"

_clients = {}


def _openai():
    if "openai" not in _clients:
        from openai import OpenAI
        _clients["openai"] = OpenAI(max_retries=5)  # reads OPENAI_API_KEY from the environment
    return _clients["openai"]


def _fastembed():
    if "fastembed" not in _clients:
        from fastembed import TextEmbedding
        _clients["fastembed"] = TextEmbedding(FASTEMBED_MODEL, threads=os.cpu_count())
    return _clients["fastembed"]


def embedding_name() -> str:
    """Which embedding model is in use. Saved next to the vectors so they're never mixed up."""
    model = OPENAI_EMBED_MODEL if EMBED_PROVIDER == "openai" else FASTEMBED_MODEL
    return f"{EMBED_PROVIDER}:{model}"


def embed_passages(texts: list[str]) -> list[list[float]]:
    if EMBED_PROVIDER == "openai":
        reply = _openai().embeddings.create(model=OPENAI_EMBED_MODEL, input=texts)
        return [item.embedding for item in reply.data]
    return [v.tolist() for v in _fastembed().passage_embed(texts)]


def embed_query(text: str) -> list[float]:
    if EMBED_PROVIDER == "openai":
        return embed_passages([text])[0]
    return next(iter(_fastembed().query_embed(text))).tolist()


def chat(system: str, user: str) -> tuple[str, int]:
    """Send one question to the LLM. Returns (answer text, tokens used)."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if LLM_PROVIDER == "openai":
        model = os.getenv("OPENAI_MODEL")
        if not model:
            raise SystemExit("Set OPENAI_MODEL in .env: copy the exact model ID from your OpenAI dashboard.")
        reply = _openai().chat.completions.create(model=model, messages=messages,reasoning_effort="low")
    else:
        from groq import Groq
        if "groq" not in _clients:
            _clients["groq"] = Groq(max_retries=5)  # reads GROQ_API_KEY
        reply = _clients["groq"].chat.completions.create(
            model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"), messages=messages,
            temperature=0, reasoning_effort="low")
    return reply.choices[0].message.content, reply.usage.total_tokens
