from backend.app.signals import CallSignals, tag_turn


def test_tag_turn_detects_objection_and_negative_sentiment():
    sentiment, intents = tag_turn("Your solution seems too expensive, we already use Excel.")
    assert sentiment == "negative"
    assert "objection" in intents
    assert "pricing" in intents


def test_tag_turn_detects_buying_signal_and_positive_sentiment():
    sentiment, intents = tag_turn("This sounds good, I'm interested, when can we start?")
    assert sentiment == "positive"
    assert "buying_signal" in intents
    assert "discovery" in intents


def test_tag_turn_defaults_to_neutral_with_no_signal_words():
    sentiment, intents = tag_turn("We currently track orders in a spreadsheet.")
    assert sentiment == "neutral"
    assert intents == []


def test_call_signals_aggregates_talk_time_and_counts():
    signals = CallSignals()
    signals.record("hello there how can I help", "microphone", "neutral", [])
    signals.record("it is too expensive for us", "twilio-customer", "negative", ["objection", "pricing"])
    signals.record("I understand, let's find a plan that fits", "microphone", "neutral", [])

    payload = signals.public(rep_sources=("microphone", "manual-test", "twilio-rep"), customer_sources=("twilio-customer",))
    assert payload["type"] == "signals"
    assert payload["sentiment"] == {"positive": 0, "neutral": 2, "negative": 1}
    assert payload["intents"] == {"objection": 1, "pricing": 1}
    talk_time = payload["talk_time"]
    assert talk_time["customer_words"] == 6
    assert talk_time["rep_words"] == 14
    assert talk_time["rep_pct"] + talk_time["customer_pct"] == 100


def test_call_signals_talk_time_with_no_turns_is_zero_not_divide_by_zero():
    signals = CallSignals()
    payload = signals.public(rep_sources=("microphone",), customer_sources=("twilio-customer",))
    assert payload["talk_time"] == {"rep_words": 0, "customer_words": 0, "rep_pct": 0, "customer_pct": 0}


def test_tag_turn_detects_hindi_and_hinglish_signals():
    sentiment, intents = tag_turn("आपका solution थोड़ा महंगा लग रहा है, अभी बजट नहीं है")
    assert sentiment == "negative"
    assert "objection" in intents
    assert "pricing" in intents

    sentiment_hi_pos, intents_hi_pos = tag_turn("यह बहुत अच्छा और बढ़िया है, कब से शुरू करते हैं?")
    assert sentiment_hi_pos == "positive"
    assert "buying_signal" in intents_hi_pos
    assert "discovery" in intents_hi_pos

    sentiment_rom, intents_rom = tag_turn("Aapka rate thoda mehenga hai, sochna padega")
    assert sentiment_rom == "negative"
    assert "objection" in intents_rom
    assert "pricing" in intents_rom
