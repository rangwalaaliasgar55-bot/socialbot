"""AI content generation — captions, hashtags and post ideas.

Works fully offline with a template engine (no key needed). If an
OpenAI-compatible API key is configured (OpenAI, Groq, OpenRouter, Ollama,
LM Studio…), it is used instead for real LLM drafts.
"""
from __future__ import annotations

import os
import random
import re
from typing import Any, Dict, List, Optional

import requests

HOOKS = [
    "Here's the thing about {topic}:",
    "Unpopular opinion: {topic} changes everything.",
    "3 lessons I learned about {topic}:",
    "Stop scrolling — {topic} matters more than you think.",
    "Everyone gets {topic} wrong. Here's how to get it right:",
    "After years of {topic}, here's my honest take:",
    "{topic} in one line: simple beats clever.",
    "The fastest way to improve your {topic} today:",
]

BODIES = [
    "Most people overcomplicate it. Start small, stay consistent, and measure what actually moves the needle.",
    "It's not about doing more — it's about doing the right things repeatedly. Systems > motivation.",
    "Small daily improvements compound into results nobody can ignore.",
    "The basics are undefeated: show up, add value, listen, iterate.",
    "Consistency beats intensity. Every single time.",
]

CTAS = [
    "What's your experience? 👇",
    "Agree or disagree?",
    "Save this for later 🔖",
    "Follow for more on {topic}.",
    "Retweet if this helped 🔄",
    "Drop a 🔥 if you're building in this space.",
]

HASHTAG_POOL = {
    "default": ["#buildinpublic", "#growth", "#startups", "#automation", "#productivity",
                "#marketing", "#contentcreation", "#tech", "#ai", "#community"],
}

AI_API_KEY_ENV = "SOCIALBOT_AI_API_KEY"
AI_BASE_URL_ENV = "SOCIALBOT_AI_BASE_URL"
AI_MODEL_ENV = "SOCIALBOT_AI_MODEL"


def _topic_words(topic: str) -> List[str]:
    return [w for w in re.findall(r"[A-Za-z0-9]+", topic) if len(w) > 2]


def hashtags_for(topic: str, n: int = 3) -> List[str]:
    words = [f"#{w.lower().strip('.')}" for w in _topic_words(topic)[:2]]
    pool = list(HASHTAG_POOL["default"])
    random.shuffle(pool)
    return (words + pool)[: n + len(words)][: max(3, n + 1)]


def generate_offline(topic: str, n: int = 3, tone: str = "friendly") -> List[Dict[str, str]]:
    """Template-based drafts — deterministic-ish, always available."""
    drafts = []
    used: set = set()
    for _ in range(n):
        hook = random.choice(HOOKS)
        while hook in used and len(used) < len(HOOKS):
            hook = random.choice(HOOKS)
        used.add(hook)
        body = random.choice(BODIES)
        cta = random.choice(CTAS)
        text = f"{hook.format(topic=topic)}\n\n{body}\n\n{cta.format(topic=topic)}"
        drafts.append({"text": text, "hashtags": hashtags_for(topic, 3), "engine": "template",
                       "tone": tone})
    return drafts


def llm_available() -> bool:
    return bool(os.environ.get(AI_API_KEY_ENV))


def generate_llm(topic: str, n: int = 3, tone: str = "friendly") -> List[Dict[str, str]]:
    base = os.environ.get(AI_BASE_URL_ENV, "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get(AI_MODEL_ENV, "gpt-4o-mini")
    key = os.environ.get(AI_API_KEY_ENV, "")
    prompt = (f"Write {n} short social media posts about '{topic}' in a {tone} tone. "
              "Vary the hooks (question, bold claim, list). Include line breaks, at most 2 "
              "hashtags each, no markdown. Return them separated by '---'.")
    resp = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model,
              "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.9},
        timeout=30)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    drafts = []
    for chunk in re.split(r"\n*---+\n*", content):
        text = chunk.strip()
        if text:
            tags = re.findall(r"#\w+", text)
            drafts.append({"text": text, "hashtags": tags[:3], "engine": f"llm:{model}",
                           "tone": tone})
    return drafts[:n]


def generate(topic: str, n: int = 3, tone: str = "friendly") -> List[Dict[str, str]]:
    """Generate *n* drafts. Uses an LLM when configured, templates otherwise."""
    if llm_available():
        try:
            return generate_llm(topic, n, tone)
        except Exception:
            pass  # fall back to offline drafts
    return generate_offline(topic, n, tone)
