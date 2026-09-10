"""Locally-wired weather/environment peripherals: sensors that plug
straight into the Pi itself rather than talking to the boat's Cerbo/Venus
OS network.

Kept in their own package (rather than flat files in carpediem/, like
wifi_monitor.py/ups_monitor.py) because the status matrix already pairs
them up as adjacent slots - see status_monitor.py's Weather280 (BME280,
bme280_sensor.py) and Weather433 (RTL-SDR + rtl_433, added separately) -
and README.md documents them together for the same reason.
"""
