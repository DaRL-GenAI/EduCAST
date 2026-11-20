"""Topic -> teaching content (objectives + per-segment narration). Pure text."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..providers.base import Provider

SYSTEM = """\
You are an expert curriculum designer and lecturer. Given a topic and audience,
you produce the SPOKEN CONTENT of a short teaching video: a tight set of learning
objectives, then an ordered list of segments. Each segment is one coherent beat of
the lecture with a title and the exact narration a teacher would say aloud.

Rules:
- 4 to 8 segments. Each narration is 2-5 sentences, conversational, no markdown.
- Build understanding progressively: hook -> intuition -> mechanism -> example -> recap.
- Write only what is SPOKEN. Do not describe visuals here; that comes later.
"""


class _DraftSegment(BaseModel):
    title: str
    narration: str = Field(..., description="What the teacher says aloud, 2-5 sentences")


class TeachingContent(BaseModel):
    topic: str
    audience: str
    objectives: list[str] = Field(..., description="3-5 concrete learning outcomes")
    segments: list[_DraftSegment]


def write_content(provider: Provider, topic: str, audience: str) -> TeachingContent:
    prompt = (
        f"Topic: {topic}\nAudience: {audience}\n\n"
        "Write the learning objectives and the ordered spoken segments now."
    )
    content = provider.chat_json(prompt, TeachingContent, system=SYSTEM, max_tokens=4000)
    # Trust the topic/audience we passed in over whatever the model echoes back.
    content.topic = topic
    content.audience = audience
    return content
