"""Real-time Ring "Live View" via WebRTC - the same mechanism the Ring
app itself uses, and the only way to get a picture from cameras where
ring_client.py's Snapshot-API-based fetch_snapshot_now() structurally
can't work at all (Ring's own support confirms the 3rd Gen Stick Up Cam
Battery has no Snapshot API support whatsoever - see that method's
docstring). Live View is a bounded, on-demand video call instead of a
polled endpoint, and isn't subject to that limitation.

ring_doorbell only handles the *signaling* half of WebRTC (sending our
SDP offer to Ring over a websocket and receiving Ring's answer + ICE
candidates back) - actually decoding video needs a real WebRTC peer,
which is what aiortc provides here. One RingLiveView instance handles
exactly one camera; ring_client.py creates one instance per camera name,
so multiple can run concurrently (the Cam page watches all 4 at once).
Each instance's own state (peer connection, decode task, session id) is
fully independent of any other instance - the only thing four of them
running together share is the Pi's CPU decoding four video streams in
software at once, which is a real, currently-unverified resource
question worth watching for on real hardware.

This is a first pass, written directly against ring_doorbell's and
aiortc's documented APIs rather than tested against a live account (no
Ring credentials or aiortc install available in the environment this was
written in) - WebRTC negotiation is notoriously fiddly (exact ICE
candidate string formats, timing, aiortc version differences), so expect
this to need real on-device debugging with actual logs, not just a
read-through.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable, Optional

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.sdp import candidate_from_sdp

from carpediem.logging_setup import log

# Callback receives an ndarray, HxWx3 uint8 RGB (typed as Any rather than
# importing numpy just for this) - the Cam page turns it into a QImage
# itself, keeping this module (like the rest of the non-hmi_qt backend)
# Qt-free.
FrameCallback = Callable[[Any], None]

# Matches generate_async_webrtc_stream()'s own default - Ring's own cap on
# how long a Live View session runs before it's force-closed server side,
# independent of whether we're still watching.
SESSION_TIMEOUT_SECONDS = 5 * 60

# Video frames decode as fast as the stream sends them (usually 15-30fps)
# but forwarding every single one to the Cam page for a QImage conversion
# + repaint would be wasteful on a Pi - this caps how often on_frame is
# actually called, independent of decode rate.
MIN_FRAME_INTERVAL_SECONDS = 1.0 / 10.0

ICE_GATHERING_TIMEOUT_SECONDS = 6.0
ANSWER_TIMEOUT_SECONDS = 12.0


class RingLiveView:
    def __init__(self) -> None:
        self._pc: Optional[RTCPeerConnection] = None
        self._cam = None
        self.camera_name: Optional[str] = None
        self._session_id: Optional[str] = None
        self._recv_task: Optional[asyncio.Task] = None
        self._on_frame: Optional[FrameCallback] = None
        self._on_ended: Optional[Callable[[], None]] = None
        self._last_frame_time = 0.0

    async def start(self, cam_name: str, cam, on_frame: FrameCallback,
                     on_ended: Optional[Callable[[], None]] = None) -> bool:
        """Begin watching `cam` (a ring_doorbell camera object, already
        looked up by RingClient). Stops any session already in progress
        first - only one camera at a time."""
        await self.stop()

        self._cam = cam
        self.camera_name = cam_name
        self._on_frame = on_frame
        self._on_ended = on_ended
        self._last_frame_time = 0.0

        pc = RTCPeerConnection()
        self._pc = pc
        pc.addTransceiver("video", direction="recvonly")

        @pc.on("track")
        def on_track(track) -> None:
            log(9, f"Ring: live view - received a {track.kind} track for '{cam_name}'")
            if track.kind == "video":
                self._recv_task = asyncio.ensure_future(self._consume(track))

        @pc.on("connectionstatechange")
        async def on_state_change() -> None:
            log(9, f"Ring: live view - peer connection state for '{cam_name}': {pc.connectionState}")
            if pc.connectionState in ("failed", "closed") and self.camera_name == cam_name:
                await self.stop(notify=True)

        try:
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            await self._wait_ice_gathering_complete(pc)
        except Exception as exc:  # noqa: BLE001 - report, don't crash the tap handler
            log(9, f"Ring: live view - failed building local offer for '{cam_name}': {exc!r}")
            await self.stop()
            return False

        session_id = uuid.uuid4().hex
        self._session_id = session_id
        answer_event = asyncio.Event()
        result: dict = {}

        def on_message(msg) -> None:
            if msg.error_code:
                log(9, f"Ring: live view - Ring reported an error for '{cam_name}': "
                       f"{msg.error_code} {msg.error_message}")
                result["error"] = msg.error_message or msg.error_code
                answer_event.set()
                return
            if msg.answer:
                result["answer"] = msg.answer
                answer_event.set()
            if msg.candidate is not None and msg.sdp_m_line_index is not None:
                asyncio.ensure_future(self._add_remote_candidate(msg.candidate, msg.sdp_m_line_index, cam_name))

        try:
            await cam.generate_async_webrtc_stream(
                pc.localDescription.sdp, session_id, on_message,
                keep_alive_timeout=SESSION_TIMEOUT_SECONDS,
            )
            await asyncio.wait_for(answer_event.wait(), timeout=ANSWER_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            log(9, f"Ring: live view - timed out waiting for Ring's answer for '{cam_name}'")
            await self.stop()
            return False
        except Exception as exc:  # noqa: BLE001 - report, don't crash the tap handler
            log(9, f"Ring: live view - signaling failed for '{cam_name}': {exc!r}")
            await self.stop()
            return False

        if "error" in result or "answer" not in result:
            log(9, f"Ring: live view - no usable answer for '{cam_name}' ({result.get('error', 'no answer')})")
            await self.stop()
            return False

        try:
            await pc.setRemoteDescription(RTCSessionDescription(sdp=result["answer"], type="answer"))
        except Exception as exc:  # noqa: BLE001 - report, don't crash the tap handler
            log(9, f"Ring: live view - couldn't apply Ring's answer for '{cam_name}': {exc!r}")
            await self.stop()
            return False

        log(9, f"Ring: live view - signaling complete for '{cam_name}', waiting for video track...")
        return True

    async def stop(self, notify: bool = False) -> None:
        cam, session_id, on_ended = self._cam, self._session_id, self._on_ended
        camera_name = self.camera_name

        self._cam = None
        self.camera_name = None
        self._session_id = None
        self._on_frame = None
        self._on_ended = None

        if self._recv_task is not None:
            self._recv_task.cancel()
            self._recv_task = None
        if self._pc is not None:
            try:
                await self._pc.close()
            except Exception as exc:  # noqa: BLE001 - closing shouldn't ever raise into the caller
                log(9, f"Ring: live view - error closing peer connection: {exc!r}")
            self._pc = None
        if cam is not None and session_id is not None:
            try:
                await cam.close_webrtc_stream(session_id)
            except Exception as exc:  # noqa: BLE001 - Ring-side cleanup failing isn't fatal to us
                log(9, f"Ring: live view - error closing Ring-side session for '{camera_name}': {exc!r}")
        if notify and on_ended is not None:
            on_ended()

    async def _add_remote_candidate(self, candidate: str, sdp_m_line_index: int, cam_name: str) -> None:
        pc = self._pc
        if pc is None:
            return
        try:
            ice_candidate = candidate_from_sdp(candidate.removeprefix("candidate:"))
            ice_candidate.sdpMLineIndex = sdp_m_line_index
            await pc.addIceCandidate(ice_candidate)
        except Exception as exc:  # noqa: BLE001 - one bad candidate shouldn't kill the session
            log(9, f"Ring: live view - couldn't add ICE candidate for '{cam_name}': {exc!r}")

    async def _consume(self, track) -> None:
        cam_name = self.camera_name
        try:
            while True:
                frame = await track.recv()
                now = time.monotonic()
                if now - self._last_frame_time < MIN_FRAME_INTERVAL_SECONDS:
                    continue
                self._last_frame_time = now
                if self._on_frame is not None:
                    self._on_frame(frame.to_ndarray(format="rgb24"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - report, then fall through to end-of-stream cleanup
            log(9, f"Ring: live view - video track for '{cam_name}' ended: {exc!r}")
        if self.camera_name == cam_name:
            await self.stop(notify=True)

    @staticmethod
    async def _wait_ice_gathering_complete(pc: RTCPeerConnection) -> None:
        if pc.iceGatheringState == "complete":
            return
        done = asyncio.Event()

        @pc.on("icegatheringstatechange")
        def _on_change() -> None:
            if pc.iceGatheringState == "complete":
                done.set()

        try:
            await asyncio.wait_for(done.wait(), timeout=ICE_GATHERING_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            log(9, "Ring: live view - ICE gathering didn't finish in time, sending offer as-is")
