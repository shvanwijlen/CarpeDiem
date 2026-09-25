# Tests

Run from the repo root:

```
python -m unittest discover -s tests -v
```

- `test_publish_status.py` - when the SYS lamp turns purple (push failures, the
  2-in-a-row debounce, red beating purple, the popup's DATA STORE row).

The data store service (`server/`) has its own suite - see `server/README.md`.

There is otherwise no automated suite for the Pi app yet. During the port, the AIS
decoder (`carpediem/ais/decoder.py`) was cross-checked against `pyais` (an
independent AIS decoding library) on both a real-world test sentence and
several synthetic ones - see `PORTING_NOTES.md` for details. The rest was
smoke-tested end-to-end in `CARPEDIEM_DO_FAKE=true` mode.

Worth adding here eventually: unit tests for `ais/decoder.py` (pin down
the verified test vectors from the port so they don't silently regress)
and `vessel_tracker.py`'s distance/bearing/range-filter math.
