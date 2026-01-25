# RTCSender.py
import asyncio
import json
import logging
import ssl
from typing import Callable

import aiomqtt
import av
import numpy as np
from aiortc import (
    RTCPeerConnection,
    RTCConfiguration,
    RTCIceServer,
    VideoStreamTrack,
    RTCSessionDescription, RTCDataChannel,
)

# ==============================
# 設定 logging，方便看問題
# ==============================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RTCSender")

# 你的 STUN/TURN（請確認 124.71.218.178:3478 真的可用）
RTC_CONFIG = RTCConfiguration(
    iceServers=[
        RTCIceServer(urls=["stun:124.71.218.178:3478"]),
        RTCIceServer(
            urls=["turn:124.71.218.178:3478?transport=udp"],
            username="webrtc",
            credential="123456",
        ),
        # 建議加 google 的 stun 做備援
        RTCIceServer(urls=["stun:stun.l.google.com:19302"]),
    ]
)


def create_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


class CameraTrack(VideoStreamTrack):
    def __init__(self, read_func: Callable[[], np.ndarray | None], fps: int = 30):
        super().__init__()
        self.read_func = read_func
        self.frame_interval = 1.0 / fps

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        # 避免無限卡住，最多等一小段時間
        for _ in range(int(self.frame_interval * 1000 / 5)):  # 最多等 ~frame_interval
            frame = self.read_func()
            if frame is not None:
                break
            await asyncio.sleep(0.005)
        else:
            # 沒拿到畫面就給黑屏（避免下游崩潰）
            frame = np.zeros((480, 640, 3), dtype=np.uint8)

        video_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame


class RTCSender:
    def __init__(self, mqtt_topic_prefix: str = "user/aiwang23"):
        self.pc: RTCPeerConnection | None = None
        self.topic_offer = f"{mqtt_topic_prefix}/offer"
        self.topic_answer = f"{mqtt_topic_prefix}/answer"
        self.mqtt_hostname = "broker.emqx.io"
        self.mqtt_port = 8883
        self._running = False

    def open(self, readCameraFunc: Callable[[], np.ndarray | None], readRTCFunc: Callable[[str | bytes], None]):
        """從同步程式碼啟動"""
        asyncio.create_task(self._run(readCameraFunc, readRTCFunc))

    def close(self):
        self._running = False
        if self.pc:
            asyncio.create_task(self.pc.close())
            self.pc = None

    async def _create_peer_connection(self):
        pc = RTCPeerConnection(configuration=RTC_CONFIG)
        self.pc = pc

        @pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange(RTCIceConnectionState=None):
            logger.info(f"ICE connection state: {pc.iceConnectionState}")
            if pc.iceConnectionState == RTCIceConnectionState.FAILED:
                logger.error("ICE 連線失敗，請檢查 STUN/TURN / 防火牆 / NAT")
            elif pc.iceConnectionState == RTCIceConnectionState.CONNECTED:
                logger.info("ICE 已連通！應該可以看到畫面了～")
            elif pc.iceConnectionState == RTCIceConnectionState.CLOSED:
                logger.info("ICE connection closed")

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info(f"PeerConnection state: {pc.connectionState}")
            if pc.connectionState == "failed":
                logger.error("PeerConnection failed！通常是 DTLS 或 codec 問題")
            elif pc.connectionState == "connected":
                logger.info("WebRTC 連線成功！")

        return pc

    async def _run(self, readCameraFunc: Callable[[], np.ndarray | None], readRTCFunc: Callable[[str | bytes], None]):
        self._running = True

        try:
            pc = await self._create_peer_connection()
            logger.info("PeerConnection 已建立")

            # 加 track
            track = CameraTrack(readCameraFunc, fps=25)  # 建議 25～30 fps
            pc.addTrack(track)
            logger.info("已加入 VideoTrack")

            await self._craete_data_channel(pc, readRTCFunc)

            # 產生 offer
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            logger.info("Offer 已建立")

            offer_dict = {
                "type": pc.localDescription.type,
                "sdp": pc.localDescription.sdp,
            }
            offer_json = json.dumps(offer_dict)

            # 送 offer
            ssl_ctx = create_ssl_context()
            async with aiomqtt.Client(
                    hostname=self.mqtt_hostname,
                    port=self.mqtt_port,
                    tls_context=ssl_ctx,
            ) as client:
                await client.publish(
                    self.topic_offer,
                    payload=offer_json.encode(),
                    qos=2,  # offer
                )
                logger.info(f"Offer 已發送到 {self.topic_offer}")

            # 收 answer（加上 timeout 避免永遠卡住）
            answer_json_str = None
            async with aiomqtt.Client(
                    hostname=self.mqtt_hostname,
                    port=self.mqtt_port,
                    tls_context=ssl_ctx,
            ) as client:
                await client.subscribe(self.topic_answer, qos=2)
                logger.info(f"已訂閱 {self.topic_answer}，等待 answer...")

                try:
                    async with asyncio.timeout(25):  # 最多等 25 秒
                        async for message in client.messages:
                            answer_json_str = message.payload.decode()
                            logger.info("收到 answer")
                            break
                except asyncio.TimeoutError:
                    logger.error("等待 answer 超時（25秒）")
                    return

            if not answer_json_str:
                logger.error("沒有收到 answer")
                return

            answer_data = json.loads(answer_json_str)
            await pc.setRemoteDescription(
                RTCSessionDescription(sdp=answer_data["sdp"], type=answer_data["type"])
            )
            logger.info("Remote Description (answer) 已設定")

            # 保持連線，直到被外部關閉或 ICE 斷掉
            while self._running and pc.connectionState not in ("closed", "failed"):
                await asyncio.sleep(1.5)

        except Exception as e:
            logger.exception("RTCSender 發生錯誤")
        finally:
            self._running = False
            if self.pc:
                await self.pc.close()
                self.pc = None
            logger.info("RTCSender 結束")

    async def _craete_data_channel(self, pc: RTCPeerConnection,
                                   readRTCFunc: Callable[[str | bytes], None]) -> RTCDataChannel:
        dc = pc.createDataChannel("pos")

        @dc.on("open")
        async def on_open():
            logger.info("DataChannel 已開啟")

        @dc.on("message")
        async def on_message(message: bytes | str):
            logger.info(f"DataChannel recv: {message}")
            readRTCFunc(message)

        return dc


# 使用範例
if __name__ == "__main__":
    sender = RTCSender(mqtt_topic_prefix="user/aiwang23")


    # 假的讀取函數（請換成你真的來源，例如 OpenCV 的 cap.read()）
    def fake_read():
        return np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)


    sender.open(fake_read)

    # 讓它跑一段時間
    try:
        asyncio.run(asyncio.sleep(120))
    except KeyboardInterrupt:
        pass
    finally:
        sender.close()
