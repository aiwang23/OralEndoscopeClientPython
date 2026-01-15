# RTCSender.py（替换整个文件）
import threading
import json
import sys
import asyncio
from typing import Callable

import av
import numpy as np
from aiortc import (
    RTCPeerConnection,
    RTCConfiguration,
    RTCIceServer,
    VideoStreamTrack,
    RTCSessionDescription,
)

# ==============================
# WebRTC 配置（你的 STUN / TURN）
# ==============================
RTC_CONFIG = RTCConfiguration(
    iceServers=[
        RTCIceServer(urls=["stun:124.71.218.178:3478"]),
        RTCIceServer(
            urls=["turn:124.71.218.178:3478?transport=udp"],
            username="webrtc",
            credential="123456",
        ),
    ]
)


class CameraTrack(VideoStreamTrack):
    def __init__(self, readFunc: Callable[[], np.ndarray | None], fps: int = 30):
        super().__init__()
        self.readFunc = readFunc
        self.frame_interval = 1.0 / fps

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        # 非阻塞式尝试获取帧（readFunc 应尽量使用 get_nowait）
        while True:
            frame = self.readFunc()
            if frame is not None:
                break
            await asyncio.sleep(0.005)

        video_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame


class RTCSender:
    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self.pc = None  # 仅供 debug / 外部查询

    def open(self, readFunc: Callable[[], np.ndarray | None]):
        """
        在新线程里创建 asyncio loop 与 RTCPeerConnection，打印 Offer（等待 ICE gather 完成），
        然后读取终端粘贴的 Answer 并设置 remote description。
        """
        if self._thread and self._thread.is_alive():
            raise RuntimeError("RTCSender already opened")

        def _thread_main():
            asyncio.run(self._run_async(readFunc))

        self._thread = threading.Thread(target=_thread_main, daemon=True)
        self._thread.start()

    async def _run_async(self, readFunc):
        pc = RTCPeerConnection(RTC_CONFIG)
        self.pc = pc

        # 状态回调（便于观察）
        @pc.on("iceconnectionstatechange")
        def on_ice_state():
            print("SENDER: iceConnectionState ->", pc.iceConnectionState)

        @pc.on("icegatheringstatechange")
        def on_ice_gathering():
            print("SENDER: iceGatheringState ->", pc.iceGatheringState)

        @pc.on("icecandidate")
        def on_ice_candidate(candidate):
            # 如果你想手动 exchange candidate，可以把此处的 candidate 发给对端
            if candidate:
                print("\n=== SENDER candidate JSON ===")
                print(json.dumps({
                    "candidate": candidate.to_sdp(),
                    "sdpMid": candidate.sdpMid,
                    "sdpMLineIndex": candidate.sdpMLineIndex,
                }, separators=(",", ":")))

        # 添加视频轨道（CameraTrack 内会周期性调用 readFunc）
        pc.addTrack(CameraTrack(readFunc))

        # create offer & set local
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        # 等待 ICE gather 完成（重要）
        while pc.iceGatheringState != "complete":
            await asyncio.sleep(0.05)

        print("\n=== Offer JSON ===")
        print(json.dumps({
            "type": pc.localDescription.type,
            "sdp": pc.localDescription.sdp,
        }, separators=(",", ":")))

        print("\n=== Paste Answer JSON ===")
        # 从 stdin 读一行 JSON（你也可以改成在 GUI 中弹窗粘贴）
        answer_line = sys.stdin.readline()
        if not answer_line:
            print("No answer pasted. Exiting RTCSender thread.")
            return

        answer = json.loads(answer_line)
        await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))

        # 保持任务存活，直到程序结束或显式关闭
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            pass

    def close(self):
        # 如果需要在外部关闭 connection，请实现对线程/loop 的安全关闭。
        # 简单实现（最好在实际中用更健壮的线程间通信去做 asyncio.run_coroutine_threadsafe）
        if self.pc:
            try:
                coro = self.pc.close()
                # 在一个临时 loop 中同步等待关闭（简单做法）
                asyncio.run(coro)
            except Exception:
                pass
            self.pc = None
