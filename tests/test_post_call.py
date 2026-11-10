import asyncio

from backend.app.config import Settings
from backend.app.post_call import TurnLike, generate_call_summary


def test_rule_based_summary_for_empty_call():
    result = asyncio.run(generate_call_summary([], Settings(openai_api_key="")))
    assert result["method"] == "rules-demo"
    assert result["coaching_score"] == 70
    assert "No turns" in result["summary"]


def test_rule_based_score_penalizes_unbalanced_talk_time_and_objections():
    # Rep dominates the conversation and multiple objections go by.
    turns = [
        TurnLike("microphone", "Let me tell you about our product " * 10),
        TurnLike("microphone", "It has many great features " * 10),
        TurnLike("microphone", "And here is even more about pricing " * 10),
        TurnLike("twilio-customer", "That sounds too expensive for our budget."),
        TurnLike("twilio-customer", "We're also concerned about the risk of switching."),
    ]
    result = asyncio.run(generate_call_summary(turns, Settings(openai_api_key="")))
    assert result["method"] == "rules-demo"
    assert result["coaching_score"] < 70
    assert "objections" in result["coaching_notes"] or "rep talked" in result["coaching_notes"]


def test_rule_based_score_rewards_discovery_and_balance():
    turns = [
        TurnLike("microphone", "How does your team currently track inquiries?"),
        TurnLike("twilio-customer", "We use a spreadsheet right now."),
        TurnLike("microphone", "What happens when a lead gets missed?"),
        TurnLike("twilio-customer", "It just falls through, which is frustrating."),
    ]
    result = asyncio.run(generate_call_summary(turns, Settings(openai_api_key="")))
    assert result["coaching_score"] >= 70
    assert result["follow_up_email"]
    assert result["summary"]
