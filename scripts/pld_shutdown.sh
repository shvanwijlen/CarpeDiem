#!/bin/bash
# Run by carpediem/ups_monitor.py when the Geekworm X-UPS's PLD (Power Loss
# Detection) signal fires on GPIO23 - i.e. mains power has been lost and
# the Pi is now running on the UPS battery.
#
# 1. Best-effort blank the HDMI output, so the Magedok display gets a
#    "no signal" it can react to - most small HDMI monitors auto power off
#    on signal loss, but this can't force a screen that ignores it to turn
#    off; there's no separate control line to it.
# 2. Shut the Pi down cleanly.
#
# Both commands need to run without a password prompt - add this to
# /etc/sudoers.d/carpediem-shutdown (via `sudo visudo -f ...`), replacing
# `pi` with whatever user runs carpediem:
#   pi ALL=(ALL) NOPASSWD: /usr/bin/vcgencmd display_power 0, /sbin/shutdown -h now

set -u

logger "carpediem: PLD signal received, shutting down"

sudo /usr/bin/vcgencmd display_power 0

sudo /sbin/shutdown -h now
