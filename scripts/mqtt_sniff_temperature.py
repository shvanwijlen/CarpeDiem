"""Throwaway diagnostic: dump every N/<portal>/temperature/# MQTT message
Venus publishes, so we can see the exact topic path (device instance) and
payload shape for the two Ruuvi Bluetooth sensors ("Console" and
"Watertank PS") before wiring them into mqtt_client.py's _TOPIC_TO_FIELD.

Run on the Pi (needs the same venv mqtt_client.py uses):
    python -m scripts.mqtt_sniff_temperature

Ctrl+C to stop once you've seen both sensors report at least once - Venus
only pushes current values after the keepalive poke below, same as
mqtt_client.py's own _poke().
"""
from __future__ import annotations

import paho.mqtt.client as mqtt

from carpediem.config import config

portal = config.mqtt.portal_id


def on_connect(client, userdata, flags, rc) -> None:
    print(f"connected (rc={rc}), subscribing to N/{portal}/temperature/#")
    client.subscribe(f"N/{portal}/temperature/#")
    client.publish(f"R/{portal}/system/0/Serial", payload="")  # poke, like mqtt_client.py's _poke()


def on_message(client, userdata, msg) -> None:
    print(f"{msg.topic}  =  {msg.payload.decode('utf-8', errors='replace')}")


client = mqtt.Client(client_id="CarpeDiem-sniff", clean_session=True)
client.on_connect = on_connect
client.on_message = on_message
client.connect(config.mqtt.host, config.mqtt.port, keepalive=60)
client.loop_forever()
