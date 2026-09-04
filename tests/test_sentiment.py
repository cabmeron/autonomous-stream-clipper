import time
from services.heuristics.chat_sentiment import ChatSentimentAnalyzer
from services.ingest.twitch_irc import TwitchChatVelocityEngine
from services.storage.db import DatabaseRepository


def test_sentiment_empty_window():
    analyzer = ChatSentimentAnalyzer()
    res = analyzer.analyze_window([], "tarik")
    assert res["vibe"] == "QUIET"
    assert res["velocity"] == 0.0
    assert res["message_count"] == 0
    assert "Quiet" in res["descriptor"]
    assert res["color"] == "#475569"


def test_sentiment_hype_detection():
    analyzer = ChatSentimentAnalyzer()
    now = time.time()
    messages = [
        {"user": "user1", "text": "POGCHAMP WHAT A SHOT!", "time": now},
        {"user": "user2", "text": "LETSGOOO W W W", "time": now},
        {"user": "user3", "text": "CLUTCH GOD INSANE!!", "time": now},
        {"user": "user4", "text": "poggers that was crazy", "time": now},
        {"user": "user5", "text": "WWWWWW", "time": now},
    ]
    res = analyzer.analyze_window(messages, "tarik", window_start=now - 60.0, window_end=now)
    assert res["vibe"] == "HYPE"
    assert res["emoji"] == "🔥"
    assert res["color"] == "#22c55e"
    assert res["message_count"] == 5
    assert res["score"] > 0.1
    assert "Hype" in res["descriptor"]
    assert len(res["top_emotes"]) > 0


def test_sentiment_laughter_detection():
    analyzer = ChatSentimentAnalyzer()
    now = time.time()
    messages = [
        {"user": "user1", "text": "KEKW HE FELL OFF", "time": now},
        {"user": "user2", "text": "LULW LULW", "time": now},
        {"user": "user3", "text": "hahaha omg icant", "time": now},
        {"user": "user4", "text": "OMEGALUL", "time": now},
    ]
    res = analyzer.analyze_window(messages, "shroud", window_start=now - 60.0, window_end=now)
    assert res["vibe"] == "LAUGHTER"
    assert res["emoji"] == "😂"
    assert res["color"] == "#eab308"
    assert "Hysterics" in res["descriptor"] or "LAUGHTER" in res["vibe"]


def test_sentiment_tilt_and_suspense():
    analyzer = ChatSentimentAnalyzer()
    now = time.time()

    # Tilt test
    tilt_msgs = [
        {"user": "u1", "text": "so bad bro throwing", "time": now},
        {"user": "u2", "text": "babyrage unlucky rigged", "time": now},
        {"user": "u3", "text": "malding so hard trash", "time": now},
    ]
    tilt_res = analyzer.analyze_window(tilt_msgs, "tarik")
    assert tilt_res["vibe"] == "TILT"
    assert tilt_res["emoji"] == "🤬"

    # Suspense test
    suspense_msgs = [
        {"user": "u1", "text": "monkas what is happening", "time": now},
        {"user": "u2", "text": "monkaw panic panic", "time": now},
        {"user": "u3", "text": "no way wtf wait", "time": now},
    ]
    suspense_res = analyzer.analyze_window(suspense_msgs, "tarik")
    assert suspense_res["vibe"] == "SUSPENSE"
    assert suspense_res["emoji"] == "😬"


def test_sentiment_database_persistence():
    db = DatabaseRepository()
    now = time.time()
    sample_sentiment = {
        "channel": "testchannel",
        "window_start": now - 60.0,
        "window_end": now,
        "timestamp_str": "12:00:00",
        "vibe": "HYPE",
        "emoji": "🔥",
        "descriptor": "🔥 Hype & Excitement (POG, W) · 2.5 msg/s",
        "score": 0.75,
        "velocity": 2.5,
        "message_count": 150,
        "top_emotes": ["POG", "W"],
        "color": "#22c55e",
    }

    sentiment_id = db.save_chat_sentiment(sample_sentiment)
    assert sentiment_id is not None

    recent = db.get_recent_sentiments(channel="testchannel", limit=10)
    assert len(recent) >= 1
    item = next(s for s in recent if s["id"] == sentiment_id)
    assert item["channel_name"] == "testchannel"
    assert item["vibe"] == "HYPE"
    assert item["descriptor"] == sample_sentiment["descriptor"]
    assert item["top_emotes"] == ["POG", "W"]
    assert item["message_count"] == 150


def test_twitch_irc_window_messages_draining():
    engine = TwitchChatVelocityEngine("tarik")
    engine.window_messages.append({"user": "user1", "text": "hello", "time": time.time()})
    engine.window_messages.append({"user": "user2", "text": "gg", "time": time.time()})

    assert len(engine.window_messages) == 2
    drained = engine.drain_window_messages()
    assert len(drained) == 2
    assert len(engine.window_messages) == 0
