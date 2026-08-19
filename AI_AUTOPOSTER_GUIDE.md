# AI-Powered Auto-Posting System

## Overview
This system integrates real-time trend analysis, AI image generation (DALL-E 3), SEO optimization, and multi-platform posting into a fully automated workflow.

## Components

### 1. AI Engine (`ai_engine.py`)
- **Smart Prompt Generation**: Creates detailed DALL-E 3 prompts optimized for social media engagement
- **Image Generation**: Calls OpenAI's DALL-E 3 API to generate platform-specific images
- **Caption & SEO**: Generates relatable captions with optimal hashtags and SEO scores
- **Platform Adaptation**: Adjusts tone, length, and hashtag count per platform

### 2. Real-Time Trend Analyzer (`trend_analyzer.py`)
- **Multi-Source Integration**: Fetches trends from Twitter/X, Reddit, and mock Google Trends
- **Sentiment Analysis**: Evaluates trend sentiment (positive/neutral/negative)
- **Strategy Generation**: Recommends topics, tones, and optimal posting times
- **Growth Tracking**: Monitors trend velocity and volume

### 3. Auto Poster (`auto_poster.py`)
- **End-to-End Automation**: Combines trends + AI + publishing
- **Batch Posting**: Adapts one topic for multiple platforms simultaneously
- **Approval Workflow**: Supports manual review or auto-approve modes
- **Multi-Agent Safe**: Uses distributed locking to prevent duplicate posts

## Setup

### Environment Variables
```bash
# OpenAI (Required for AI features)
export OPENAI_API_KEY="sk-..."

# Twitter API (Optional, for real trends)
export TWITTER_BEARER_TOKEN="..."

# Reddit API (Optional, for real trends)
export REDDIT_CLIENT_ID="..."
export REDDIT_SECRET="..."

# Database (for multi-agent coordination)
export DATABASE_URL="sqlite:///socialbot.db"
```

### Install Dependencies
```bash
pip install openai requests
```

## Usage

### Generate Content Only (No Posting)
```bash
python ai_engine.py
```

### View Trending Topics
```bash
python trend_analyzer.py
```

### Auto-Post to Single Platform
```bash
# LinkedIn (manual approval)
python auto_poster.py --platform linkedin

# Twitter (auto-approve)
python auto_poster.py --platform twitter --auto-approve

# Custom topic
python auto_poster.py --platform instagram --topic "Sustainable Living" --auto-approve
```

### Batch Post to All Platforms
```bash
# Queued for approval on all platforms
python auto_poster.py --batch

# Auto-approve and post everywhere
python auto_poster.py --batch --auto-approve
```

### Programmatic Usage
```python
from auto_poster import AutoPoster

autoposter = AutoPoster()

# Single platform
result = autoposter.create_and_post_trending_content(
    platform="linkedin",
    auto_approve=False
)

# All platforms
results = autoposter.batch_post_to_all_platforms(
    topic="AI Innovation",
    platforms=["twitter", "linkedin", "instagram"],
    auto_approve=True
)
```

## Workflow Diagram

```
┌─────────────────┐
│ Trend Analyzer  │
│ - Twitter API   │
│ - Reddit API    │
│ - Sentiment     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Content Strategy│
│ - Topic         │
│ - Tone          │
│ - Keywords      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   AI Engine     │
│ - GPT-4 Prompt  │
│ - DALL-E 3 Image│
│ - Caption + SEO │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Agent Manager  │
│ - Acquire Lock  │
│ - Queue Task    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Publisher     │
│ - Platform API  │
│ - Media Upload  │
│ - Error Handle  │
└─────────────────┘
```

## Features

### SEO Optimization
- Keyword density analysis
- Hashtag relevance scoring
- Optimal posting time calculation
- Platform-specific character limits

### Relatability Scoring
- Audience targeting logic
- Tone adaptation (professional vs. conversational)
- Sentiment alignment with trends
- Engagement prediction

### Multi-Agent Coordination
- Distributed locking prevents duplicate posts
- Task queuing for approval workflows
- Agent health monitoring
- Automatic failover on agent death

### Safety & Controls
- Manual approval mode available
- Rate limit handling
- Error recovery with retries
- Comprehensive logging

## Example Output

```json
{
  "success": true,
  "post_id": "1234567890",
  "platform": "linkedin",
  "topic": "AI in Healthcare",
  "image_url": "https://oaidalleapiprodscus.blob.core.windows.net/...",
  "caption_preview": "Exciting innovations in healthcare AI are transforming patient care...",
  "seo_score": 0.89,
  "relatability_score": 0.94
}
```

## Best Practices

1. **Start with Manual Approval**: Run with `--batch` but without `--auto-approve` initially
2. **Monitor Metrics**: Check `/api/metrics` endpoint for AI usage and success rates
3. **Set Budget Limits**: OpenAI API costs can add up; monitor usage
4. **Review Generated Content**: AI may occasionally produce off-brand content
5. **Tune Prompts**: Customize `ai_engine.py` prompts for your brand voice

## Troubleshooting

### No Images Generated
- Check `OPENAI_API_KEY` is set
- Verify API key has DALL-E 3 access
- Check logs for rate limit errors

### No Real Trends
- Configure Twitter/Reddit API credentials
- System falls back to mock data if APIs unavailable

### Duplicate Posts
- Ensure `agents.py` database is accessible
- Check lock acquisition logs
- Verify only one auto-poster instance running per topic

## Next Steps

1. **Add More Trend Sources**: Google Trends, TikTok trending, YouTube trending
2. **Advanced NLP**: Integrate dedicated sentiment analysis model
3. **A/B Testing**: Generate multiple variants and test performance
4. **Analytics Integration**: Track post performance and refine AI models
5. **Custom Fine-Tuning**: Fine-tune GPT model on your brand's historical top-performing posts
