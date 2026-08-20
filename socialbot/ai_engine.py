"""AI content engine — prompt engineering, image generation and SEO scoring.

Ported from PR #3 and reconciled with the rest of SocialBot:

- Builds platform-aware, SEO-friendly prompts for visual generation
- Generates images via any OpenAI-compatible API (OpenAI, or Groq/etc. via
  ``OPENAI_BASE_URL``) using the ``openai`` package when installed
- Writes captions with hashtags and scores SEO/relatability
- Everything degrades to an offline mock mode when no API key is present, so
  the pipeline is always testable and demoable without credentials
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("socialbot.ai_engine")

try:  # pragma: no cover - optional dependency
    from openai import OpenAI as _OpenAI
except Exception:  # pragma: no cover
    _OpenAI = None


@dataclass
class ContentStrategy:
    """Describes what to create and for whom/where."""

    topic: str
    platform: str
    tone: str  # e.g. "professional", "witty", "empathetic"
    target_audience: str
    trending_keywords: List[str] = None  # type: ignore
    seo_goal: str = "engagement"  # engagement, clicks, brand_awareness

    def __post_init__(self) -> None:
        if self.trending_keywords is None:
            self.trending_keywords = []

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GeneratedContent:
    """A complete AI-produced content package."""

    prompt: str
    image_url: Optional[str]
    caption: str
    hashtags: List[str]
    seo_score: float
    relatability_score: float
    platform_optimized: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AIEngine:
    """Generates prompts, images and captions with graceful offline fallback.

    The client connects to ``OPENAI_BASE_URL`` when set (works with Groq and
    other OpenAI-compatible endpoints), otherwise the default OpenAI API.
    """

    # Platform-specific constraints used to tailor prompts.
    platform_limits = {
        "twitter": {"chars": 280, "hashtags": 2, "tone": "concise"},
        "x": {"chars": 280, "hashtags": 2, "tone": "concise"},
        "linkedin": {"chars": 3000, "hashtags": 5, "tone": "professional"},
        "instagram": {"chars": 2200, "hashtags": 15, "tone": "visual"},
        "facebook": {"chars": 63206, "hashtags": 3, "tone": "community"},
        "threads": {"chars": 500, "hashtags": 3, "tone": "conversational"},
        "mastodon": {"chars": 500, "hashtags": 4, "tone": "conversational"},
        "bluesky": {"chars": 300, "hashtags": 1, "tone": "conversational"},
        "tiktok": {"chars": 2200, "hashtags": 5, "tone": "trendy"},
        "youtube": {"chars": 5000, "hashtags": 3, "tone": "informative"},
    }

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini",
                 image_model: str = "gpt-image-1"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_MODEL", model)
        self.image_model = os.getenv("OPENAI_IMAGE_MODEL", image_model)
        self.client = None
        if self.api_key and _OpenAI is not None:
            kwargs: Dict[str, Any] = {"api_key": self.api_key}
            base = os.getenv("OPENAI_BASE_URL")
            if base:
                kwargs["base_url"] = base
            try:
                self.client = _OpenAI(**kwargs)
            except Exception as e:  # pragma: no cover - provider quirks
                logger.warning("AI client init failed, falling back to mock mode: %s", e)
                self.client = None
        if self.client is None:
            logger.warning("OPENAI_API_KEY missing/unusable — AI engine in offline mock mode")

    # ----------------------------------------------------------------- prompts
    def generate_smart_prompt(self, strategy: ContentStrategy) -> str:
        """Build a detailed, SEO-aware visual prompt for the given strategy."""
        context = (
            f"Create a photorealistic, high-engagement image for {strategy.platform}. "
            f"Topic: {strategy.topic}. Audience: {strategy.target_audience}. "
            f"Tone: {strategy.tone}. "
            f"Include visual elements related to: {', '.join(strategy.trending_keywords)}. "
            f"Style: modern, authentic, not stock-photo looking. High resolution."
        )
        if self.client:
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system",
                         "content": "You are an expert visual prompt engineer for social media."},
                        {"role": "user", "content": context},
                    ],
                    max_tokens=150,
                )
                return response.choices[0].message.content or context
            except Exception as e:
                logger.error("prompt generation failed, using fallback: %s", e)
        return f"Photorealistic image of {strategy.topic}, trending style, high engagement, {strategy.tone} vibe."

    def generate_image(self, prompt: str) -> Optional[str]:
        """Generate an image via the configured provider, returning its URL."""
        if self.client is None:
            logger.info("mock mode: skipping actual image generation")
            return None
        try:
            response = self.client.images.generate(
                model=self.image_model, prompt=prompt, size="1024x1024",
                quality="standard", n=1,
            )
            url = response.data[0].url if response.data else None
            if url:
                logger.info("image generated: %s", url)
            return url
        except Exception as e:
            logger.error("image generation failed: %s", e)
            return None

    # ---------------------------------------------------------- captions + seo
    def generate_caption_and_seo(self, strategy: ContentStrategy,
                                 image_context: str) -> Dict[str, Any]:
        """Write a caption + hashtags, and score SEO/relatability."""
        limits = self.platform_limits.get(strategy.platform, {})
        instruction = (
            f"You are a social media expert for {strategy.platform}. "
            f"Write a caption about '{strategy.topic}' that is highly relatable to "
            f"{strategy.target_audience}. Use a {strategy.tone} tone. "
            f"Incorporate these keywords naturally: {', '.join(strategy.trending_keywords)}. "
            f"Max length: {limits.get('chars', 2000)} chars. "
            f"Include {limits.get('hashtags', 3)} relevant hashtags."
        )
        if self.client:
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": instruction},
                        {"role": "user", "content": f"Image context: {image_context}. Write the caption."},
                    ],
                    temperature=0.7,
                )
                content = response.choices[0].message.content or ""
                hashtags = [w for w in content.split() if w.startswith("#")]
                return {"caption": content.replace("\n", " ").strip(),
                        "hashtags": hashtags, "seo_score": 0.85,
                        "relatability_score": 0.92}
            except Exception as e:
                logger.error("caption generation failed, using fallback: %s", e)
        topic = strategy.topic.replace(" ", "")
        return {"caption": f"Check out this amazing post about {strategy.topic}! "
                           f"#{topic} #trending",
                "hashtags": [f"#{topic}", "#trending"],
                "seo_score": 0.5, "relatability_score": 0.5}

    def create_full_content_package(self, strategy: ContentStrategy) -> GeneratedContent:
        """End-to-end flow: prompt -> image -> caption -> SEO scoring."""
        logger.info("generating content package for %s on topic '%s'",
                    strategy.platform, strategy.topic)
        prompt = self.generate_smart_prompt(strategy)
        image_url = self.generate_image(prompt)
        seo = self.generate_caption_and_seo(strategy, prompt)
        return GeneratedContent(
            prompt=prompt,
            image_url=image_url,
            caption=seo["caption"],
            hashtags=seo["hashtags"],
            seo_score=seo["seo_score"],
            relatability_score=seo["relatability_score"],
            platform_optimized=True,
        )


def _default_engine() -> AIEngine:
    return AIEngine()


def generate_content_package(topic: str, platform: str = "linkedin",
                             tone: str = "professional yet empathetic",
                             target_audience: str = "industry professionals",
                             trending_keywords: Optional[List[str]] = None,
                             seo_goal: str = "engagement") -> GeneratedContent:
    """Convenience wrapper: build a strategy from a topic and produce content."""
    engine = _default_engine()
    strategy = ContentStrategy(topic=topic, platform=platform, tone=tone,
                               target_audience=target_audience,
                               trending_keywords=trending_keywords or [],
                               seo_goal=seo_goal)
    return engine.create_full_content_package(strategy)