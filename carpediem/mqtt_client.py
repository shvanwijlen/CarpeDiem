"""Port of the PubSubClient setup, reconnect(), and callback() from the
sketch - subscribes to Venus OS / VRM MQTT topics and maps JSON {"value":
...} payloads onto the display_data store.

Bugs fixed while porting (see display_data.py for the field additions this
relies on): the original callback() had real, working code paths for
"battery/278/Dc/1/*" and "system/0/Dc/Battery/Power", but DisplayInfo[] had
no matching field for any of them, so UpdateDisplayTable() silently
dropped every one of those values. Also removed one duplicate `else if`
branch for "system/0/Dc/System/Current" that appeared twice (the second
copy was unreachable dead code) and the debug-only `delay(10000)` on an
unmatched topic, which would have frozen the whole single-threaded
Arduino loop for 10 seconds - meaningless (and harmful) now that MQTT
runs on its own thread.

Uses paho-mqtt's network loop in a background thread (loop_start()), so
on_message runs concurrently with the rest of the app - display_data is
locked internally so that's safe.
"""
from __future__ import annotations

import json
import time

import paho.mqtt.client as mqtt

from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log

# internal_label -> True if the value should be divided by 3600 (seconds -> hours),
# matching the sketch's `JSONvalue/3600` for the two TimeToGo topics.
_TOPIC_TO_FIELD = {
    "battery/278/Dc/0/Power": ("Battery0 Power (W)", 1.0),
    "battery/278/Dc/0/Current": ("Battery0 Current (A)", 1.0),
    "battery/278/Dc/0/Voltage": ("Battery0 Voltage (V)", 1.0),
    "battery/278/Dc/1/Power": ("Battery1 Power (W)", 1.0),
    "battery/278/Dc/1/Current": ("Battery1 Current (A)", 1.0),
    "battery/278/Dc/1/Voltage": ("Battery1 Voltage (V)", 1.0),
    "system/0/Dc/Battery/TimeToGo": ("Battery Time to Go (System)", 1.0 / 3600),
    "battery/278/TimeToGo": ("Battery Time to Go (Batt)", 1.0 / 3600),
    "system/0/Dc/Battery/Power": ("Battery Power (W)", 1.0),
    "system/0/Dc/Battery/Current": ("Battery Current (A)", 1.0),
    "system/0/Dc/System/Power": ("DC Power (W)", 1.0),
    "system/0/Dc/System/Current": ("DC Current (A)", 1.0),
    # system/0/Dc/Battery/Voltage and system/0/Dc/Battery/Soc: intentionally
    # not mapped, same as the original (Modbus is the preferred source for
    # both - see modbus_client.py's "Battery0 Voltage (V)" / "Battery SOC (%)").
}

# Every topic we subscribe to (superset of _TOPIC_TO_FIELD's keys, matching
# the original myVictronMQTT[] table 1:1 so nothing subscribed-to is lost
# even if it has no display field yet).
SUBSCRIBED_TOPICS = [
    "system/0/Dc/Battery/Current",
    "system/0/Dc/Battery/Power",
    "system/0/Dc/Battery/Soc",
    "system/0/Dc/Battery/TimeToGo",
    "system/0/Dc/Battery/Voltage",
    "battery/278/TimeToGo",
    "battery/278/Dc/1/Current",
    "battery/278/Dc/1/Power",
    "battery/278/Dc/1/Voltage",
    "battery/278/Dc/0/Current",
    "battery/278/Dc/0/Power",
    "battery/278/Dc/0/Voltage",
]

_KEEPALIVE_INTERVAL = 30  # seconds, matches the sketch's poke-keepalive


class VictronMqttClient:
    def __init__(self) -> None:
        self._portal_id = config.mqtt.portal_id
        self._client = mqtt.Client(client_id="CarpeDiem", clean_session=True)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._last_keepalive = 0.0

    # -- lifecycle -----------------------------------------------------
    def start(self) -> None:
        log(9, f"MQTT: connecting to {config.mqtt.host}:{config.mqtt.port} ...")
        self._client.connect_async(config.mqtt.host, config.mqtt.port, keepalive=60)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def tick(self) -> None:
        """Call periodically (e.g. once a second) from the main loop to
        send the keepalive poke, equivalent to the `if (now - lastMsg >
        30000)` block inside the DoMQTT branch of loop()."""
        now = time.monotonic()
        if now - self._last_keepalive > _KEEPALIVE_INTERVAL:
            self._last_keepalive = now
            self._poke()

    # -- internals -------------------------------------------------------
    def _poke_topic(self) -> str:
        return f"R/{self._portal_id}/system/0/Serial"

    def _poke(self) -> None:
        self._client.publish(self._poke_topic(), payload="")

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc != 0:
            log(9, f"MQTT: connect failed, rc={rc}")
            display_data.update("MQTT", 0, source="S")
            return
        log(9, "MQTT: connected")
        display_data.update("MQTT", 1, source="S")
        base = f"N/{self._portal_id}/"
        for topic in SUBSCRIBED_TOPICS:
            client.subscribe(base + topic)
        self._poke()  # poke it so it starts sending data, same as setup()

    def _on_disconnect(self, client, userdata, rc) -> None:
        log(9, f"MQTT: disconnected (rc={rc}), paho will auto-reconnect")
        display_data.update("MQTT", 0, source="S")

    def _on_message(self, client, userdata, msg) -> None:
        # msg.topic is like "N/<portalId>/battery/278/Dc/0/Power"
        prefix = f"N/{self._portal_id}/"
        if not msg.topic.startswith(prefix):
            return
        topic_suffix = msg.topic[len(prefix):]

        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            log(9, f"MQTT: failed to parse JSON on {msg.topic}: {exc}")
            return

        value = payload.get("value")
        if value is None:
            return

        mapping = _TOPIC_TO_FIELD.get(topic_suffix)
        if mapping is None:
            log(9, f"MQTT: not yet covered: {topic_suffix}; value={value}")
            return

        field, scale = mapping
        display_data.update(field, value * scale, source="Q")
