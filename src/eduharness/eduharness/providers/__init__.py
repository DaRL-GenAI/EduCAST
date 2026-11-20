from .openai_provider import OpenAIProvider
from .usage import UsageTracker


def get_provider(cfg, usage: UsageTracker | None = None):
    if not cfg.api_key:
        raise RuntimeError("This stage requires OPENAI_API_KEY")
    return OpenAIProvider(cfg, usage=usage)


__all__ = ["OpenAIProvider", "UsageTracker", "get_provider"]
