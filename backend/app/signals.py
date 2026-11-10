"""Lightweight per-turn sentiment/intent tagging and live talk-time aggregation.

Deliberately heuristic rather than LLM-based: this runs on every single utterance
alongside the hint pipeline, and adding a second model call per turn would double
per-utterance latency and cost for a signal that only needs to be directionally
useful (a coaching indicator, not a graded transcript).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

POSITIVE_WORDS = frozenset((
    "great", "good", "love", "like", "interested", "excited", "perfect", "awesome",
    "sounds good", "makes sense", "yes", "definitely", "happy", "helpful",
    "accha", "acha", "badhiya", "badiya", "sahi", "pasand", "bilkul", "zaroor",
    "अच्छा", "बढ़िया", "पसंद", "सही", "बिल्कुल", "हाँ", "जी हाँ",
))
NEGATIVE_WORDS = frozenset((
    "expensive", "costly", "not interested", "no", "don't", "dont", "won't", "wont",
    "frustrat", "annoyed", "disappointed", "concerned", "worried", "problem", "issue",
    "cancel", "complicated", "confusing", "difficult", "hard to",
    "mehenga", "mahanga", "muskil", "mushkil", "dikkat", "pareshani", "nahi chahiye",
    "महंगा", "मुश्किल", "दिक्कत", "परेशानी", "चिंता", "नहीं चाहिए",
))
OBJECTION_WORDS = frozenset((
    "expensive", "costly", "budget", "not sure", "need to think", "competitor",
    "already use", "already have", "concern", "worried", "risk", "too much",
    "mehenga", "mahanga", "sochna padega", "abhi nahi", "baad mein", "pehle se",
    "महंगा", "बजट", "सोचना पड़ेगा", "अभी नहीं", "बाद में", "पहले से",
))
PRICING_WORDS = frozenset((
    "price", "pricing", "cost", "discount", "budget", "quote", "expensive",
    "mehenga", "mahanga", "keemat", "kimat", "paisa", "paise", "kharcha", "rate",
    "महंगा", "बजट", "कीमत", "पैसा", "पैसे", "खर्चा", "रेट",
))
BUYING_SIGNAL_WORDS = frozenset((
    "interested", "sign up", "get started", "when can we start", "timeline",
    "let's do it", "lets do it", "sounds good", "move forward", "next step",
    "shuru karte", "start karte", "kab se", "aage badhte", "demo dikhao",
    "शुरू करते", "कब से", "आगे बढ़ते", "डेमो",
))
DISCOVERY_MARKERS = (
    "how ", "what ", "can it", "can you", "could it", "does it", "do you", "?",
    "kaise ", "kya ", "kitna ", "kab ", "kaun ", "कैसे", "क्या", "कितना", "कब", "कौन",
)


def tag_turn(text: str) -> tuple[str, list[str]]:
    """Return (sentiment, intents) for one utterance using fast keyword heuristics."""
    q = text.casefold()

    positive_hits = sum(1 for w in POSITIVE_WORDS if w in q)
    negative_hits = sum(1 for w in NEGATIVE_WORDS if w in q)
    if negative_hits > positive_hits:
        sentiment = "negative"
    elif positive_hits > negative_hits:
        sentiment = "positive"
    else:
        sentiment = "neutral"

    intents: list[str] = []
    if any(w in q for w in OBJECTION_WORDS):
        intents.append("objection")
    if any(w in q for w in PRICING_WORDS):
        intents.append("pricing")
    if any(w in q for w in BUYING_SIGNAL_WORDS):
        intents.append("buying_signal")
    if any(marker in q for marker in DISCOVERY_MARKERS):
        intents.append("discovery")
    return sentiment, intents


@dataclass
class CallSignals:
    """Running per-call aggregate, kept in memory for the life of one live session."""

    word_counts: Counter = field(default_factory=Counter)  # by source
    sentiment_counts: Counter = field(default_factory=Counter)  # positive/neutral/negative
    intent_counts: Counter = field(default_factory=Counter)  # objection/pricing/buying_signal/discovery

    def record(self, text: str, source: str, sentiment: str, intents: list[str]) -> None:
        self.word_counts[source] += len(text.split())
        self.sentiment_counts[sentiment] += 1
        for intent in intents:
            self.intent_counts[intent] += 1

    def talk_time(self, rep_sources: tuple[str, ...], customer_sources: tuple[str, ...]) -> dict:
        rep_words = sum(self.word_counts[s] for s in rep_sources)
        customer_words = sum(self.word_counts[s] for s in customer_sources)
        total = rep_words + customer_words
        rep_pct = round(100 * rep_words / total) if total else 0
        return {
            "rep_words": rep_words,
            "customer_words": customer_words,
            "rep_pct": rep_pct,
            "customer_pct": 100 - rep_pct if total else 0,
        }

    def public(self, rep_sources: tuple[str, ...], customer_sources: tuple[str, ...]) -> dict:
        return {
            "type": "signals",
            "sentiment": {
                "positive": self.sentiment_counts["positive"],
                "neutral": self.sentiment_counts["neutral"],
                "negative": self.sentiment_counts["negative"],
            },
            "intents": dict(self.intent_counts),
            "talk_time": self.talk_time(rep_sources, customer_sources),
        }


REP_SOURCES = ("microphone", "manual-test", "twilio-rep")
CUSTOMER_SOURCES = ("twilio-customer", "customer-test")
