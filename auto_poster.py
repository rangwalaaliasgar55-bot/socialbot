"""
Auto-Poster: Integrates AI Engine, Trend Analyzer, and Publisher
Automatically generates and posts content based on real-time trends.
"""

import os
import json
import logging
from typing import Optional, List
from datetime import datetime

from ai_engine import AIEngine, ContentStrategy, GeneratedContent
from trend_analyzer import RealTrendAnalyzer
import sys
sys.path.insert(0, '/workspace/socialbot')

# Import as package to handle relative imports
import socialbot.publisher as pub_module
from socialbot.storage import Store
from socialbot.http import HttpClient
from socialbot.agents import AgentCoordinator  # From multi-agent system

PostPublisher = pub_module.Publisher  # Use the Publisher class
AgentManager = AgentCoordinator  # Alias for compatibility

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AutoPoster:
    def __init__(self):
        self.ai_engine = AIEngine()
        self.trend_analyzer = RealTrendAnalyzer()
        
        # Initialize publisher with required dependencies
        store = Store()
        http_client = HttpClient()
        self.publisher = PostPublisher(store=store, http=http_client)
        
        # Initialize agent coordinator (it auto-registers on init)
        self.agent_manager = AgentManager()
        self.agent_id = self.agent_manager.agent_id  # Get the registered agent ID


    def create_and_post_trending_content(
        self, 
        platform: str, 
        auto_approve: bool = False
    ) -> Optional[dict]:
        """
        End-to-end flow:
        1. Fetch trending topics for platform
        2. Generate content strategy
        3. Create AI-generated image and caption
        4. Post to platform
        """
        logger.info(f"Starting auto-post workflow for {platform}")
        
        # Step 1: Get trending content strategy
        strategy_data = self.trend_analyzer.generate_content_strategy(platform)
        if "error" in strategy_data:
            logger.error(f"No strategy available: {strategy_data}")
            return None
        
        # Convert to ContentStrategy object
        strategy = ContentStrategy(
            topic=strategy_data["recommended_topic"],
            platform=platform,
            tone=strategy_data["tone"],
            target_audience=strategy_data["target_audience"],
            trending_keywords=strategy_data["trending_keywords"],
            seo_goal=strategy_data["seo_goal"]
        )
        
        logger.info(f"Generated strategy for topic: {strategy.topic}")
        
        # Step 2: Generate full content package (prompt + image + caption)
        content = self.ai_engine.create_full_content_package(strategy)
        
        if not content.image_url:
            logger.warning("No image generated, proceeding with text-only post")
        
        logger.info(f"Content generated - SEO Score: {content.seo_score}, Relatability: {content.relatability_score}")
        
        # Step 3: Prepare post data
        post_data = {
            "platform": platform,
            "message": f"{content.caption}\n\n{' '.join(content.hashtags)}",
            "media_urls": [content.image_url] if content.image_url else [],
            "metadata": {
                "ai_generated": True,
                "prompt_used": content.prompt,
                "seo_score": content.seo_score,
                "relatability_score": content.relatability_score,
                "trend_topic": strategy.topic,
                "generated_at": datetime.utcnow().isoformat()
            }
        }
        
        # Step 4: Use distributed lock to prevent duplicate posts (context manager)
        lock_key = f"post_lock:{platform}:{strategy.topic}"
        
        try:
            with self.agent_manager.acquire_lock(lock_key):
                # Step 5: Publish (or queue for approval)
                if auto_approve:
                    result = self.publisher.publish(post_data)
                    logger.info(f"Post published successfully: {result}")
                    
                    return {
                        "success": True,
                        "post_id": result.get("post_id"),
                        "platform": platform,
                        "topic": strategy.topic,
                        "image_url": content.image_url,
                        "caption_preview": content.caption[:100]
                    }
                else:
                    # Queue for manual approval
                    task_id = self.agent_manager.enqueue_task(
                        task_type="approve_post",
                        payload=post_data,
                        priority=5
                    )
                    logger.info(f"Post queued for approval (Task ID: {task_id})")
                    return {
                        "success": True,
                        "queued": True,
                        "task_id": task_id,
                        "platform": platform,
                        "topic": strategy.topic
                    }
                    
        except RuntimeError as e:
            if "Failed to acquire lock" in str(e):
                logger.warning(f"Could not acquire lock for {lock_key}. Another agent may be posting.")
                return None
            raise
        except Exception as e:
            logger.error(f"Error publishing post: {e}")
            return {"success": False, "error": str(e)}

    def batch_post_to_all_platforms(
        self, 
        topic: Optional[str] = None,
        platforms: Optional[List[str]] = None,
        auto_approve: bool = False
    ) -> dict:
        """
        Generate one piece of content and adapt it for multiple platforms.
        """
        if not platforms:
            platforms = ["twitter", "linkedin", "instagram", "facebook", "threads"]
        
        results = {}
        
        # Get a general trending topic if none specified
        if not topic:
            all_trends = self.trend_analyzer.get_trending_topics()
            if all_trends:
                topic = all_trends[0].topic
            else:
                topic = "Technology Trends"
        
        logger.info(f"Creating batch posts for topic: {topic}")
        
        for platform in platforms:
            logger.info(f"Processing platform: {platform}")
            result = self.create_and_post_trending_content(
                platform=platform,
                auto_approve=auto_approve
            )
            results[platform] = result
            
            # Small delay to avoid rate limits
            import time
            time.sleep(2)
        
        return {
            "topic": topic,
            "platforms_processed": len(platforms),
            "results": results
        }

# CLI Entry Point
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Auto-post trending content")
    parser.add_argument("--platform", default="linkedin", help="Target platform")
    parser.add_argument("--batch", action="store_true", help="Post to all platforms")
    parser.add_argument("--auto-approve", action="store_true", help="Skip approval queue")
    parser.add_argument("--topic", help="Specific topic to post about")
    
    args = parser.parse_args()
    
    autoposter = AutoPoster()
    
    if args.batch:
        result = autoposter.batch_post_to_all_platforms(
            topic=args.topic,
            auto_approve=args.auto_approve
        )
        print(json.dumps(result, indent=2))
    else:
        result = autoposter.create_and_post_trending_content(
            platform=args.platform,
            auto_approve=args.auto_approve
        )
        print(json.dumps(result, indent=2))
