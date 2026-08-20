"""Intelligence & understanding — offline NLP-flavoured helpers.

Sentiment analysis (lexicon based, no external deps), intent detection for the
inbox responder, thoughtful reply generation, topic extraction and content
"vibe" metrics used by the adaptive engine. Everything runs locally so the bot
stays fast, private and dependency-free.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# ------------------------------------------------------------------ sentiment
POSITIVE = {
    "great", "good", "love", "loved", "awesome", "amazing", "excellent", "best",
    "nice", "happy", "glad", "thanks", "thank", "like", "liked", "enjoy", "enjoyed",
    "wow", "brilliant", "fantastic", "helpful", "perfect", "cool", "sweet", "win",
    "winning", "success", "successful", "recommend", "wonderful",
    "impressive", "beautiful", "incredible", "superb", "top", "favorite", "favourite",
}
NEGATIVE = {
    "bad", "terrible", "awful", "hate", "hated", "horrible", "worst", "disappointed",
    "disappointing", "unhappy", "angry", "annoyed", "frustrating", "frustrated",
    "broken", "refund", "scam", "spam", "sucks", "sucked", "useless", "waste",
    "problem", "problems", "error", "slow", "late", "boring", "dumb", "stupid",
    "fail", "failed", "failure", "dislike", "complaint", "unfortunately", "never",
}
NEGATION = {"not", "no", "never", "don't", "dont", "doesn't", "isn't", "wasn't",
            "can't", "cant", "won't", "wont", "aren't", "hardly"}
BOOSTERS = {"very", "really", "so", "super", "extremely", "totally", "absolutely",
            "incredibly", "highly", "deeply", "truly"}
POSITIVE_EMOJI = {"👍", "❤️", "❤", "😍", "😊", "🙂", "🎉", "🔥", "💯", "🙌", "👏", "😄", "😃", "🤩"}
NEGATIVE_EMOJI = {"👎", "😡", "😠", "😢", "😭", "💔", "🤬", "😤", "😞", "🙄"}

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "than", "to", "of", "for",
    "on", "in", "with", "at", "by", "from", "as", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "can", "could", "should", "this", "that", "these", "those", "it", "its", "i",
    "you", "your", "we", "our", "they", "their", "he", "she", "his", "her", "me",
    "my", "so", "just", "about", "not", "no", "yes", "up", "out", "all", "very",
    "really", "too", "more", "most", "some", "any", "how", "what", "why", "when",
    "where", "who", "which", "get", "got", "go", "going", "make", "made", "see",
    "like", "want", "please", "also", "now", "even", "only", "over",
}

INTENT_KEYWORDS: Dict[str, List[str]] = {
    "pricing": ["price", "pricing", "cost", "how much", "plan", "subscription",
                "premium", "paid", "charge", "billing", "fee", "rate"],
    "demo": ["demo", "trial", "try it", "try out", "test it", "sample", "walkthrough",
             "show me", "see it in action", "book a call", "sign up"],
    "thanks": ["thanks", "thank you", "thx", "appreciate", "grateful", "thankful",
               "love it", "great service", "awesome job", "great work"],
    "complaint": ["refund", "broken", "disappointed", "terrible", "awful", "hate",
                  "problem", "error", "slow", "scam", "spam", "useless", "waste",
                  "angry", "frustrat", "bad experience", "unacceptable", "cancel my"],
    "question": ["how do", "how does", "what is", "what are", "why is", "when will",
                 "where can", "can you", "could you", "would you", "is it", "does it"],
    "greeting": ["hi", "hello", "hey", "good morning", "good afternoon", "good evening"],
    "spam": ["buy now", "free money", "click here", "earn", "invest now", "crypto",
             "guaranteed", "winner", "lottery", "cash prize", "act fast"],
}

INTENT_REPLIES: Dict[str, str] = {
    "pricing": ("Thanks for asking about pricing — happy to share our plans. "
                "We have a free tier and affordable options for every size. "
                "Want me to send you the details?"),
    "demo": ("Great question — a quick demo is easy to set up. What time "
             "works for you this week?"),
    "thanks": "Thanks for the kind words — really appreciate you! 🙌",
    "complaint": ("I'm really sorry about that — that's not the experience we want "
                  "you to have. I'm escalating this to the team right away and will "
                  "get back to you shortly."),
    "question": ("Happy to help with that! Could you share a bit more context so "
                 "I can point you to the right answer?"),
    "greeting": "Hi there! Thanks for reaching out — how can I help you today?",
    "spam": "",  # never engage with spam — handled by the blacklist path
}

DEFAULT_POSITIVE_REPLY = ("Really glad you enjoyed this — appreciate the support "
                          "and thanks for stopping by! 🙌")
DEFAULT_NEGATIVE_REPLY = ("Thanks for the honest feedback — I've passed it on. "
                          "If there's anything specific you'd like fixed, let me know.")
DEFAULT_NEUTRAL_REPLY = ("Thanks for sharing your thoughts — always good to hear "
                         "different perspectives. 👍")


# ----------------------------------------------------------------- sentiment
def sentiment(text: str) -> float:
    """Score text between -1.0 (very negative) and +1.0 (very positive)."""
    words = re.findall(r"[a-zA-Z']+", (text or "").lower())
    score = 0.0
    negate = False
    for word in words:
        if word in NEGATION:
            negate = True
            continue
        base = 1.0
        if word in BOOSTERS:
            base = 1.8
            continue
        if word in POSITIVE:
            score += base * (-1 if negate else 1)
        elif word in NEGATIVE:
            score += base * (1 if negate else -1)
        negate = False
    for emoji in POSITIVE_EMOJI:
        score += 0.8 * text.count(emoji)
    for emoji in NEGATIVE_EMOJI:
        score -= 0.8 * text.count(emoji)
    if "!!" in text:
        score += 0.3
    return max(-1.0, min(1.0, score / max(1, len(words) / 6)))


def sentiment_label(score: float) -> str:
    if score >= 0.35:
        return "positive"
    if score <= -0.35:
        return "negative"
    return "neutral"


def is_negative(text: str, threshold: float = -0.2) -> bool:
    return sentiment(text) <= threshold


# -------------------------------------------------------------------- intents
def detect_intent(text: str) -> str:
    """Classify a DM/mention into an intent bucket (or 'unknown')."""
    low = (text or "").lower()
    for intent in ("spam", "pricing", "demo", "complaint", "thanks", "question", "greeting"):
        for keyword in INTENT_KEYWORDS[intent]:
            if keyword in low:
                return intent
    return "unknown"


def reply_for(text: str, intent: Optional[str] = None, score: Optional[float] = None,
              template: str = "") -> str:
    """Craft a thoughtful, context-aware reply.

    Uses an explicit template when given; otherwise replies based on intent and
    sentiment, echoing a topic word from the original message.
    """
    if template:
        topic = ", ".join(topics(text, 2)) or "this"
        return template.format(topic=topic) if "{topic}" in template else template
    intent = intent or detect_intent(text)
    score = sentiment(text) if score is None else score
    base = INTENT_REPLIES.get(intent)
    if base:
        return base
    if score >= 0.35:
        return DEFAULT_POSITIVE_REPLY
    if score <= -0.35:
        return DEFAULT_NEGATIVE_REPLY
    return DEFAULT_NEUTRAL_REPLY


# -------------------------------------------------------------------- topics
def topics(text: str, n: int = 4) -> List[str]:
    """Extract the most frequent content words from text."""
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", (text or "").lower())
    freq: Dict[str, int] = {}
    for word in words:
        if word in STOPWORDS or word.startswith("http"):
            continue
        freq[word] = freq.get(word, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [word for word, _ in ranked[:n]]


# --------------------------------------------------------------- vibe metrics
def vibe_metrics(text: str) -> Dict[str, Any]:
    """Numeric description of a post's style, used by the adaptive engine."""
    t = text or ""
    return {
        "length": len(t),
        "words": len(t.split()),
        "hashtags": len(re.findall(r"#\w+", t)),
        "mentions": len(re.findall(r"@\w+", t)),
        "links": len(re.findall(r"https?://\S+", t)),
        "questions": len(re.findall(r"\?", t)),
        "exclamations": len(re.findall(r"!", t)),
        "newlines": t.count("\n"),
        "emoji": len(re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", t)),
        "caps_ratio": (sum(1 for ch in t if ch.isupper()) / max(1, len(t))),
        "sentiment": sentiment(t),
    }


def analyze(text: str) -> Dict[str, Any]:
    """Combined analysis used by the CLI/API sentiment endpoints."""
    score = sentiment(text)
    return {
        "sentiment": score,
        "label": sentiment_label(score),
        "intent": detect_intent(text),
        "topics": topics(text),
        "vibe": vibe_metrics(text),
        "suggested_reply": reply_for(text),
    }