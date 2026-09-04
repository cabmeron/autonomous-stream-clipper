import time
from services.ingest.twitch_irc import TwitchChatVelocityEngine


def test_velocity_empty():
    engine = TwitchChatVelocityEngine("shroud")
    metrics = engine.recalculate()
    assert metrics["v_instant"] == 0.0
    assert metrics["v_baseline"] == 0.0
    assert metrics["spike_ratio"] == 0.0
    assert metrics["is_spiking"] is False


def test_velocity_steady_traffic():
    engine = TwitchChatVelocityEngine("shroud")
    now = time.time()
    # 2 msgs per second for 60 seconds
    for sec in range(60):
        t = now - 60 + sec
        engine.timestamps.append(t)
        engine.timestamps.append(t + 0.5)

    metrics = engine.recalculate()
    assert abs(metrics["v_baseline"] - 2.0) <= 0.2
    assert abs(metrics["v_instant"] - 2.0) <= 0.2
    assert metrics["is_spiking"] is False


def test_velocity_spike_detection():
    spikes = []

    def on_spike(v_inst, ratio):
        spikes.append((v_inst, ratio))

    engine = TwitchChatVelocityEngine("shroud", on_spike_callback=on_spike, spike_ratio_threshold=3.0, instant_min_threshold=10.0)
    now = time.time()

    # Steady 2 msg/s for baseline
    for sec in range(60):
        t = now - 60 + sec
        engine.timestamps.append(t)
        engine.timestamps.append(t + 0.5)

    # Spike in last 5 seconds: 80 messages (16 msg/s)
    for i in range(80):
        engine.timestamps.append(now - 4.0 + (i * 0.04))

    metrics = engine.recalculate()
    assert metrics["v_instant"] >= 14.0
    assert metrics["spike_ratio"] >= 3.0
    assert metrics["is_spiking"] is True
    assert len(spikes) == 1


def test_parse_irc_privmsg():
    from services.ingest.twitch_irc import parse_irc_privmsg

    # Standard IRC privmsg
    raw = ":cooluser!cooluser@cooluser.tmi.twitch.tv PRIVMSG #tarik :CLUTCH GOD PogChamp"
    parsed = parse_irc_privmsg(raw)
    assert parsed is not None
    assert parsed["user"] == "cooluser"
    assert parsed["text"] == "CLUTCH GOD PogChamp"

    # IRC privmsg with Twitch tags
    tagged = "@badge-info=;badges=moderator/1;color=#1E90FF;display-name=ModUser;emotes= :moduser!moduser@moduser.tmi.twitch.tv PRIVMSG #tarik :Slow down chat!"
    parsed_tagged = parse_irc_privmsg(tagged)
    assert parsed_tagged is not None
    assert parsed_tagged["user"] == "moduser"
    assert parsed_tagged["text"] == "Slow down chat!"

    # Non-privmsg line
    assert parse_irc_privmsg("PING :tmi.twitch.tv") is None


def test_recent_messages_cap_and_id_tracking():
    engine = TwitchChatVelocityEngine("tarik")
    for i in range(65):
        engine.total_messages += 1
        engine.recent_messages.append({"id": engine.total_messages, "user": f"user{i}", "text": f"message {i}", "time": time.time()})

    metrics = engine.recalculate()
    # recent_messages deque is capped at 50
    assert len(metrics["recent_messages"]) == 50
    # total_messages tracks cumulative count past 50
    assert metrics["total_messages"] == 65
    # oldest in recent_messages is message 15
    assert metrics["recent_messages"][0]["id"] == 16
    # newest is message 65
    assert metrics["recent_messages"][-1]["id"] == 65

