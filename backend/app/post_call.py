"""Post-call analysis: summary, a coaching score, and a drafted follow-up email.

Mirrors the AI/rules-demo split used by agent.py and knowledge.py elsewhere in this
app: with an OpenAI key configured, one LLM call analyzes the full transcript; without
one, a deterministic rubric over the signals already computed live (talk-time,
sentiment, objections) produces a directionally-useful score so the feature still
works in the free demo path.
"""
from __future__ import annotations

import json
import logging

from .config import Settings
from .signals import CUSTOMER_SOURCES, REP_SOURCES, CallSignals, tag_turn

logger = logging.getLogger(__name__)

DISPOSITIONS = ("interested", "not_interested", "follow_up", "no_decision", "do_not_contact")

SYSTEM_PROMPT = """You are a sales coaching assistant reviewing a finished call transcript.
The transcript may mix English, Hindi (Devanagari), or Hinglish.
Respond with ONLY a JSON object, no markdown fences, with exactly these keys:
"summary" (2-3 sentences on what happened and the outcome),
"coaching_score" (integer 0-100; weigh discovery questions asked, objections handled, balanced talk-time, and whether next steps were set),
"coaching_notes" (1-2 sentences of specific, actionable coaching feedback for the rep),
"follow_up_email" (a short, ready-to-send follow-up email draft, 3-5 sentences, no subject line, grounded only in what was actually discussed),
"disposition" (exactly one of: "interested", "not_interested", "follow_up", "no_decision", "do_not_contact" — the call's outcome).
Do not invent prices, features, or commitments that were not in the transcript."""


class TurnLike:
    """Minimal shape post_call needs from a Turn row or an in-memory turn dict."""

    def __init__(self, source: str, text: str):
        self.source = source
        self.text = text


def _rule_based_score(turns: list[TurnLike]) -> tuple[int, str]:
    signals = CallSignals()
    for t in turns:
        sentiment, intents = tag_turn(t.text)
        signals.record(t.text, t.source, sentiment, intents)

    talk_time = signals.talk_time(REP_SOURCES, CUSTOMER_SOURCES)
    discovery_count = sum(
        1 for t in turns if t.source in REP_SOURCES and "discovery" in tag_turn(t.text)[1]
    )
    objection_count = signals.intent_counts.get("objection", 0)
    positive = signals.sentiment_counts.get("positive", 0)
    negative = signals.sentiment_counts.get("negative", 0)

    score = 70
    score += min(discovery_count * 5, 15)
    if talk_time["rep_pct"] > 70:
        score -= min((talk_time["rep_pct"] - 70) // 2, 20)
    score -= min(max(objection_count - 1, 0) * 5, 20)
    if positive > negative:
        score += 10
    elif negative > positive:
        score -= 10
    score = max(0, min(100, int(score)))

    notes = []
    if talk_time["rep_pct"] > 70:
        notes.append("the rep talked for most of the call — leave more room for the customer")
    if discovery_count == 0:
        notes.append("no discovery questions were asked — open with one next time")
    if objection_count > 1:
        notes.append(f"{objection_count} objections came up — confirm each was addressed before moving on")
    if not notes:
        notes.append("balanced conversation with reasonable discovery; keep this pattern")
    return score, ("Coaching note: " + "; ".join(notes) + ".")


def _rule_based_disposition(turns: list[TurnLike]) -> str:
    if not turns:
        return "no_decision"
    signals = CallSignals()
    for t in turns:
        sentiment, intents = tag_turn(t.text)
        signals.record(t.text, t.source, sentiment, intents)
    positive = signals.sentiment_counts.get("positive", 0)
    negative = signals.sentiment_counts.get("negative", 0)
    objections = signals.intent_counts.get("objection", 0)
    buying_signal = signals.intent_counts.get("buying_signal", 0)
    discovery = signals.intent_counts.get("discovery", 0)

    if buying_signal > 0 and positive >= negative:
        return "interested"
    if negative > positive and objections >= 2:
        return "not_interested"
    if discovery > 0 or objections > 0:
        return "follow_up"
    return "no_decision"


def _rule_based_summary(turns: list[TurnLike]) -> str:
    if not turns:
        return "No turns were recorded for this call."
    customer_turns = [t for t in turns if t.source in CUSTOMER_SOURCES or t.source == "manual-test"]
    topic = customer_turns[0].text if customer_turns else turns[0].text
    return f"{len(turns)}-turn call. Opened around: “{topic[:140]}”."


def _rule_based_follow_up(turns: list[TurnLike]) -> str:
    if not turns:
        return "Hi, thanks for your time today — following up on our conversation. Let me know if you have any questions."
    return (
        "Hi, thank you for the time today. To recap, we discussed "
        f"“{turns[0].text[:120]}” and a few related points. "
        "I'll follow up with the details we covered — let me know if any questions come up in the meantime, "
        "and happy to set up a next step whenever works for you."
    )


async def generate_call_summary(turns: list[TurnLike], settings: Settings) -> dict:
    """Returns {summary, coaching_score, coaching_notes, follow_up_email, method}."""
    if settings.openai_api_key and turns:
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=15.0, max_retries=0)
            transcript = "\n".join(f"[{t.source}] {t.text}" for t in turns)[:6000]
            completion = await client.chat.completions.create(
                model=settings.openai_hint_model,
                temperature=0.3,
                max_tokens=500,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"TRANSCRIPT:\n{transcript}"},
                ],
            )
            content = (completion.choices[0].message.content or "").strip()
            content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(content)
            disposition = str(data.get("disposition", "no_decision"))
            if disposition not in DISPOSITIONS:
                disposition = "no_decision"
            return {
                "summary": str(data["summary"])[:2000],
                "coaching_score": max(0, min(100, int(data["coaching_score"]))),
                "coaching_notes": str(data["coaching_notes"])[:1000],
                "follow_up_email": str(data["follow_up_email"])[:3000],
                "disposition": disposition,
                "method": "ai",
            }
        except Exception:
            logger.exception("AI post-call summary failed; falling back to rules-demo")

    score, notes = _rule_based_score(turns)
    return {
        "summary": _rule_based_summary(turns),
        "coaching_score": score,
        "coaching_notes": notes,
        "follow_up_email": _rule_based_follow_up(turns),
        "disposition": _rule_based_disposition(turns),
        "method": "rules-demo",
    }
