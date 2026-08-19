"""
Real-time Trend Analyzer for SocialBot
Fetches trending topics, analyzes sentiment, and suggests content strategies.
Integrates with AI Engine for real-time content generation.
"""

import os
import json
import logging
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

@dataclass
class TrendData:
    topic: str
    volume: int
    growth_rate: float
    sentiment: str  # positive, neutral, negative
    platforms: List[str]
    related_keywords: List[str]

class RealTrendAnalyzer:
    def __init__(self):
        # In production, integrate with Twitter API, Reddit API, Google Trends, etc.
        self.twitter_bearer = os.getenv("TWITTER_BEARER_TOKEN")
        self.reddit_client_id = os.getenv("REDDIT_CLIENT_ID")
        self.reddit_secret = os.getenv("REDDIT_SECRET")
        
        # Mock trending topics for demonstration (replace with real API calls)
        self.mock_trends = [
            {
                "topic": "AI in Healthcare",
                "volume": 150000,
                "growth_rate": 0.45,
                "sentiment": "positive",
                "platforms": ["twitter", "linkedin"],
                "related_keywords": ["machinelearning", "healthtech", "innovation"]
            },
            {
                "topic": "Remote Work Tools",
                "volume": 89000,
                "growth_rate": 0.22,
                "sentiment": "neutral",
                "platforms": ["linkedin", "twitter", "facebook"],
                "related_keywords": ["productivity", "wfh", "collaboration"]
            },
            {
                "topic": "Sustainable Living",
                "volume": 210000,
                "growth_rate": 0.67,
                "sentiment": "positive",
                "platforms": ["instagram", "threads", "facebook"],
                "related_keywords": ["ecofriendly", "zerowaste", "climateaction"]
            }
        ]

    def fetch_twitter_trends(self, woeid: int = 1) -> List[Dict]:
        """Fetch real trends from Twitter/X"""
        if not self.twitter_bearer:
            logger.warning("Twitter API not configured. Using mock data.")
            return []
        
        try:
            headers = {"Authorization": f"Bearer {self.twitter_bearer}"}
            url = f"https://api.twitter.com/1.1/trends/place.json?id={woeid}"
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data[0].get("trends", []) if data else []
        except Exception as e:
            logger.error(f"Error fetching Twitter trends: {e}")
            return []

    def fetch_reddit_hot_topics(self, limit: int = 10) -> List[Dict]:
        """Fetch hot topics from Reddit"""
        if not self.reddit_client_id:
            logger.warning("Reddit API not configured. Using mock data.")
            return []
        
        try:
            # Get OAuth token
            auth = requests.auth.HTTPBasicAuth(self.reddit_client_id, self.reddit_secret)
            data = {"grant_type": "client_credentials"}
            res = requests.post("https://www.reddit.com/api/v1/access_token", auth=auth, data=data)
            token = res.json().get("access_token")
            
            if not token:
                return []
                
            headers = {"Authorization": f"Bearer {token}", "User-Agent": "SocialBot/1.0"}
            response = requests.get(
                "https://oauth.reddit.com/r/all/hot.json",
                headers=headers,
                params={"limit": limit},
                timeout=10
            )
            response.raise_for_status()
            posts = response.json().get("data", {}).get("children", [])
            
            # Extract topics
            topics = []
            for post in posts[:5]:
                topics.append({
                    "topic": post["data"]["title"],
                    "volume": post["data"]["ups"],
                    "growth_rate": 0.1,  # Simplified
                    "sentiment": "neutral",
                    "platforms": ["reddit"],
                    "related_keywords": post["data"].get("link_flair_text", "").split(",")
                })
            return topics
        except Exception as e:
            logger.error(f"Error fetching Reddit topics: {e}")
            return []

    def analyze_sentiment(self, text: str) -> str:
        """Simple sentiment analysis (integrate with NLP model in production)"""
        positive_words = ["great", "amazing", "love", "best", "awesome", "innovation"]
        negative_words = ["bad", "worst", "hate", "terrible", "fail"]
        
        text_lower = text.lower()
        pos_count = sum(1 for word in positive_words if word in text_lower)
        neg_count = sum(1 for word in negative_words if word in text_lower)
        
        if pos_count > neg_count:
            return "positive"
        elif neg_count > pos_count:
            return "negative"
        return "neutral"

    def get_trending_topics(self, platform: Optional[str] = None) -> List[TrendData]:
        """Aggregate trends from multiple sources"""
        all_trends = []
        
        # Fetch real data
        twitter_trends = self.fetch_twitter_trends()
        reddit_topics = self.fetch_reddit_hot_topics()
        
        # Process Twitter trends
        for trend in twitter_trends:
            all_trends.append(TrendData(
                topic=trend.get("name", ""),
                volume=trend.get("tweet_volume", 0) or 0,
                growth_rate=0.1,  # Would calculate from historical data
                sentiment=self.analyze_sentiment(trend.get("name", "")),
                platforms=["twitter"],
                related_keywords=[]
            ))
        
        # Add Reddit topics
        all_trends.extend([
            TrendData(
                topic=t["topic"],
                volume=t["volume"],
                growth_rate=t["growth_rate"],
                sentiment=t["sentiment"],
                platforms=t["platforms"],
                related_keywords=t["related_keywords"]
            ) for t in reddit_topics
        ])
        
        # Fallback to mock data if no real data
        if not all_trends:
            logger.info("Using mock trending data")
            all_trends = [TrendData(**t) for t in self.mock_trends]
        
        # Filter by platform if specified
        if platform:
            all_trends = [t for t in all_trends if platform in t.platforms]
        
        # Sort by volume and growth
        all_trends.sort(key=lambda x: x.volume * (1 + x.growth_rate), reverse=True)
        
        return all_trends[:10]  # Return top 10

    def generate_content_strategy(self, platform: str) -> Dict[str, Any]:
        """Generate a content strategy based on current trends"""
        trends = self.get_trending_topics(platform)
        
        if not trends:
            return {"error": "No trends available"}
        
        top_trend = trends[0]
        
        return {
            "recommended_topic": top_trend.topic,
            "tone": "professional" if platform == "linkedin" else "conversational",
            "target_audience": "industry professionals" if platform == "linkedin" else "general audience",
            "trending_keywords": top_trend.related_keywords or [top_trend.topic.replace(" ", "")],
            "seo_goal": "engagement" if top_trend.sentiment == "positive" else "awareness",
            "sentiment_context": top_trend.sentiment,
            "trend_volume": top_trend.volume,
            "optimal_posting_time": self._calculate_optimal_time(platform)
        }
    
    def _calculate_optimal_time(self, platform: str) -> str:
        """Calculate optimal posting time based on platform best practices"""
        # Simplified logic - in production, use analytics data
        times = {
            "twitter": "09:00 AM",
            "linkedin": "08:00 AM",
            "instagram": "06:00 PM",
            "facebook": "01:00 PM",
            "threads": "07:00 PM"
        }
        return times.get(platform, "12:00 PM")

# Example Usage
if __name__ == "__main__":
    analyzer = RealTrendAnalyzer()
    
    print("\n=== Top Trending Topics ===")
    trends = analyzer.get_trending_topics()
    for i, trend in enumerate(trends[:5], 1):
        print(f"{i}. {trend.topic} (Volume: {trend.volume}, Sentiment: {trend.sentiment})")
    
    print("\n=== Content Strategy for LinkedIn ===")
    strategy = analyzer.generate_content_strategy("linkedin")
    print(json.dumps(strategy, indent=2))
