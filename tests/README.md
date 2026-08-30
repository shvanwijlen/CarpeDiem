# Tests

No automated test suite yet. During the port, the AIS decoder
(`carpediem/ais/decoder.py`) was cross-checked against `pyais` (an
independent AIS decoding library) on both a real-world test sentence and
several synthetic ones - see `PORTING_NOTES.md` for details. The rest was
smoke-tested end-to-end in `CARPEDIEM_DO_FAKE=true` mode.

Worth adding here eventually: unit tests for `ais/decoder.py` (pin down
the verified test vectors from the port so they don't silently regress)
and `vessel_tracker.py`'s distance/bearing/range-filter math.
