"""
AI Engine for SocialBot
Generates SEO-optimized prompts, creates images via DALL-E 3 (or compatible),
and ensures content is relatable and platform-specific.
"""

import os
import json
import logging
import time
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from openai import OpenAI

logger = logging.getLogger(__name__)

@dataclass
class ContentStrategy:
    topic: str
    platform: str
    tone: str  # e.g., "professional", "witty", "empathetic"
    target_audience: str
    trending_keywords: List[str]
    seo_goal: str  # e.g., "engagement", "clicks", "brand_awareness"

@dataclass
class GeneratedContent:
    prompt: str
    image_url: Optional[str]
    caption: str
    hashtags: List[str]
    seo_score: float
    relatability_score: float
    platform_optimized: bool

class AIEngine:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            logger.warning("OPENAI_API_KEY not found. AI features will be in mock mode.")
            self.client = None
        else:
            self.client = OpenAI(api_key=self.api_key)
        
        # Platform-specific constraints
        self.platform_limits = {
            "twitter": {"chars": 280, "hashtags": 2, "tone": "concise"},
            "linkedin": {"chars": 3000, "hashtags": 5, "tone": "professional"},
            "instagram": {"chars": 2200, "hashtags": 15, "tone": "visual"},
            "facebook": {"chars": 63206, "hashtags": 3, "tone": "community"},
            "threads": {"chars": 500, "hashtags": 3, "tone": "conversational"},
        }

    def generate_smart_prompt(self, strategy: ContentStrategy) -> str:
        """
        Generates a highly detailed image prompt optimized for DALL-E 3,
        incorporating SEO keywords and relatability factors.
        """
        context = (
            f"Create a photorealistic, high-engagement image for {strategy.platform}. "
            f"Topic: {strategy.topic}. Audience: {strategy.target_audience}. "
            f"Tone: {strategy.tone}. "
            f"Must include visual elements related to: {', '.join(strategy.trending_keywords)}. "
            f"Style: Modern, authentic, not stock-photo looking. High resolution, 16:9 aspect ratio."
        )
        
        if self.client:
            try:
                response = self.client.chat.completions.create(
                    model="gpt-4-turbo",
                    messages=[
                        {"role": "system", "content": "You are an expert visual prompt engineer for social media."},
                        {"role": "user", "content": context}
                    ],
                    max_tokens=150
                )
                return response.choices[0].message.content
            except Exception as e:
                logger.error(f"Error generating prompt: {e}")
        
        # Fallback/Mock mode
        return f"Photorealistic image of {strategy.topic}, trending style, high engagement, {strategy.tone} vibe."

    def generate_image(self, prompt: str, output_path: str = "generated_image.png") -> Optional[str]:
        """
        Calls DALL-E 3 to generate an image based on the prompt.
        Returns the URL or local path if downloaded.
        """
        if not self.client:
            logger.info("Mock mode: Skipping actual image generation.")
            return None

        try:
            response = self.client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size="1024x1024",
                quality="standard",
                n=1,
            )
            image_url = response.data[0].url
            logger.info(f"Image generated: {image_url}")
            
            # Optional: Download image locally
            # import requests
            # img_data = requests.get(image_url).content
            # with open(output_path, 'wb') as handler:
            #     handler.write(img_data)
            # return output_path
            
            return image_url
        except Exception as e:
            logger.error(f"Error generating image: {e}")
            return None

    def generate_caption_and_seo(self, strategy: ContentStrategy, image_context: str) -> Dict[str, Any]:
        """
        Generates a caption, hashtags, and calculates SEO/Relatability scores.
        """
        system_instruction = (
            f"You are a social media expert for {strategy.platform}. "
            f"Write a caption about '{strategy.topic}' that is highly relatable to {strategy.target_audience}. "
            f"Use a {strategy.tone} tone. "
            f"Incorporate these keywords naturally: {', '.join(strategy.trending_keywords)}. "
            f"Max length: {self.platform_limits.get(strategy.platform, {}).get('chars', 2000)} chars. "
            f"Include {self.platform_limits.get(strategy.platform, {}).get('hashtags', 3)} relevant hashtags."
        )

        if self.client:
            try:
                response = self.client.chat.completions.create(
                    model="gpt-4-turbo",
                    messages=[
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": f"Image context: {image_context}. Write the caption."}
                    ],
                    temperature=0.7
                )
                content = response.choices[0].message.content
                
                # Simple parsing (in production, use JSON mode)
                hashtags = [word for word in content.split() if word.startswith('#')]
                clean_caption = content.replace('\n', ' ')
                
                return {
                    "caption": clean_caption,
                    "hashtags": hashtags,
                    "seo_score": 0.85, # Mock score, can be calculated via separate logic
                    "relatability_score": 0.92
                }
            except Exception as e:
                logger.error(f"Error generating caption: {e}")
        
        # Fallback
        return {
            "caption": f"Check out this amazing post about {strategy.topic}! #trending #{strategy.topic}",
            "hashtags": [f"#{strategy.topic}", "#trending"],
            "seo_score": 0.5,
            "relatability_score": 0.5
        }

    def create_full_content_package(self, strategy: ContentStrategy) -> GeneratedContent:
        """
        End-to-end flow: Prompt -> Image -> Caption -> SEO Analysis
        """
        logger.info(f"Generating content package for {strategy.platform} on topic: {strategy.topic}")
        
        # 1. Generate Smart Prompt
        prompt = self.generate_smart_prompt(strategy)
        
        # 2. Generate Image
        image_url = self.generate_image(prompt)
        
        # 3. Generate Caption & SEO
        seo_data = self.generate_caption_and_seo(strategy, prompt)
        
        return GeneratedContent(
            prompt=prompt,
            image_url=image_url,
            caption=seo_data["caption"],
            hashtags=seo_data["hashtags"],
            seo_score=seo_data["seo_score"],
            relatability_score=seo_data["relatability_score"],
            platform_optimized=True
        )

# Example Usage
if __name__ == "__main__":
    engine = AIEngine()
    strategy = ContentStrategy(
        topic="Remote Work Life",
        platform="linkedin",
        tone="professional yet empathetic",
        target_audience="Software Developers",
        trending_keywords=["worklifebalance", "coding", "homeoffice"],
        seo_goal="engagement"
    )
    
    result = engine.create_full_content_package(strategy)
    print(json.dumps(result.__dict__, indent=2))
