import asyncio
import json
import logging
import sys
import threading
import time
from queue import Queue, Full, Empty
from threading import Event
from typing import Any

import cv2
import qasync
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QStatusBar, QLabel, QPushButton, QComboBox, QMessageBox
)
from numpy import ndarray
from qt_material import apply_stylesheet

from Camera import Camera
from RTCSender import RTCSender
from RenderWidget import RenderWidget, PixelFormat

logger = logging.getLogger(__file__)


class MainWindow(QMainWindow):
    signalFrame: Signal = Signal(object)  # frame: ndarray
    STATUS_STOPPED = "Detection: Stopped"
    STATUS_STARTING = "Detection: Starting..."
    STATUS_CONNECTING = "Detection: Connecting (ICE checking)..."
    STATUS_CONNECTED = "Detection: Connected ✓"
    STATUS_FAILED = "Detection: Failed ×"
    STATUS_CLOSED = "Detection: Closed"

    def __init__(self):
        super().__init__()
        self.camWidget: RenderWidget | None = None
        self.openOrCloseDetBtn: QPushButton | None = None
        self.makeReportBtn: QPushButton | None = None
        self.camListComBoBox: QComboBox | None = None
        self.camListBtn: QPushButton | None = None
        self.mStatusText: QLabel | None = None

        self.readFrameThread: threading.Thread | None = None
        self.readFrameThreadIsRunning: Event = threading.Event()  # set true; clear false
        self.readFrameThreadIsRunning.clear()

        self.camera: Camera | None = Camera()
        self.rtcSender: RTCSender = RTCSender()
        self.rtcSenderIsRunning: Event = threading.Event()  # set true; clear false
        self.camToRtcQueue: Queue = Queue(1)
        self.rtcToCamQueue: Queue = Queue(1)

        self.initUI()
        self.setGeometry((QApplication.primaryScreen().availableGeometry().width() - 1000) // 2,
                         (QApplication.primaryScreen().availableGeometry().height() - 700) // 2, 1000, 700)

        self.initSignalSlots()

        self.updateCameraList()

    def closeEvent(self, event: QCloseEvent):
        self.stopReadFrameThreadFunction()
        self.camera.close()
        super().closeEvent(event)

    def initUI(self):
        # 1. 容器
        mainWidget = QWidget(self)
        mainLayout = QHBoxLayout(mainWidget)
        splitter = QSplitter(Qt.Orientation.Horizontal, mainWidget)

        # 1.1 左侧部分
        leftContainer = QWidget()
        mLeftVLayout = QVBoxLayout()
        leftContainer.setLayout(mLeftVLayout)
        self.camWidget = RenderWidget()
        mLeftVLayout.addWidget(self.camWidget)
        # 1.1 左侧部分

        # 1.2 右侧部分
        rightContainer = QWidget()
        mRightVLayout = QVBoxLayout()
        rightContainer.setLayout(mRightVLayout)
        camListText = QLabel("camera: ", rightContainer)
        mOpenDetText = QLabel("detection: ", rightContainer)
        self.openOrCloseDetBtn = QPushButton("Open Detection", rightContainer)
        mMakeText = QLabel("make report: ", rightContainer)
        self.makeReportBtn = QPushButton("Make Report", rightContainer)
        mRightVLayout.addWidget(camListText)

        # 1.2.1 水平布局（摄像头选择 + 按钮）
        mHLayout = QHBoxLayout()
        self.camListComBoBox = QComboBox()
        self.camListBtn = QPushButton("Refresh")
        mHLayout.addWidget(self.camListComBoBox)
        mHLayout.addWidget(self.camListBtn)
        mRightVLayout.addLayout(mHLayout)
        # 1.2.1 水平布局（摄像头选择 + 按钮）

        mRightVLayout.addWidget(mOpenDetText)
        mRightVLayout.addWidget(self.openOrCloseDetBtn)
        mRightVLayout.addWidget(mMakeText)
        mRightVLayout.addWidget(self.makeReportBtn)
        mRightVLayout.addStretch()  # 占位，推到顶部
        # 1.2 右侧部分

        # 1.3 下侧部分
        mStatusBar = QStatusBar(self)
        self.mStatusText = QLabel("running", self)
        mStatusBar.addWidget(self.mStatusText)
        self.setStatusBar(mStatusBar)
        # 1.3 下侧部分

        splitter.addWidget(leftContainer)
        splitter.addWidget(rightContainer)
        splitter.setStretchFactor(0, 150)
        splitter.setStretchFactor(1, 1)
        splitter.setStyleSheet("QSplitter::handle { background-color: lightgray; }")
        splitter.setHandleWidth(5)

        mainLayout.addWidget(splitter)
        self.setCentralWidget(mainWidget)
        # 1. 容器

    def initSignalSlots(self):
        if self.camListBtn:
            self.camListBtn.clicked.connect(self.updateCameraList)
        if self.camListComBoBox:
            self.camListComBoBox.currentIndexChanged.connect(self.cameraListCurrentChanged)
        self.signalFrame.connect(self.onFrameArrived)
        if self.openOrCloseDetBtn:
            self.openOrCloseDetBtn.clicked.connect(self.openOrCloseDetection)

    def updateCameraList(self):

        # 阻止刷新期间触发索引改变信号
        self.camListComBoBox.blockSignals(True)

        itemName: str | None = self.camListComBoBox.currentText()
        itemNum: int = self.camListComBoBox.currentData()
        self.camListComBoBox.clear()
        if (itemName is None or itemNum is None) or itemName == self.tr("close"):
            self.camListComBoBox.addItem(self.tr("close"), -1)
            for dev in Camera.devices():
                name: str = dev.name
                displayName: str = name if name is not None else f"Camera {dev.index}"
                self.camListComBoBox.addItem(displayName, dev.index)
        else:
            self.camListComBoBox.addItem(itemName, itemNum)
            self.camListComBoBox.addItem(self.tr("close"), -1)
            for dev in Camera.devices():
                name: str = dev.name
                displayName: str = name if name is not None else f"Camera {dev.index}"
                if displayName != itemName:
                    self.camListComBoBox.addItem(displayName, dev.index)

        self.camListComBoBox.blockSignals(False)

    def cameraListCurrentChanged(self):
        index = self.camListComBoBox.currentIndex()
        cam_id = self.camListComBoBox.itemData(index)

        if index == -1:
            return

        # === close 分支 ===
        if self.camListComBoBox.itemText(index) == self.tr("close"):
            if self.readFrameThreadIsRunning.is_set():
                self.stopReadFrameThreadFunction()
            self.camera.close()
            print("摄像头关闭成功！")
            self.camWidget.clear()
            return

        # === 1. 先安全停止旧线程 ===
        if self.readFrameThreadIsRunning.is_set():
            self.stopReadFrameThreadFunction()

        # === 2. 打开摄像头并启动新线程 ===
        if self.camera.open(cam_id):
            print("摄像头打开成功！")

            self.readFrameThreadIsRunning.set()

            self.readFrameThread = threading.Thread(
                target=self.readFrameThreadFunction,
                daemon=True
            )
            self.readFrameThread.start()

    def readFrameThreadFunction(self):
        print("采集线程启动")

        while self.readFrameThreadIsRunning.is_set():
            frame: ndarray | None = self.camera.read()
            if frame is None:
                time.sleep(0.001)  # 等价于 sleep_for(1ms)
                continue

            # 子线程 → 主线程
            self.signalFrame.emit(frame)
            # rtc
            self.put_latest(self.camToRtcQueue, frame)

        print("采集线程退出")

    def onFrameArrived(self, frame: ndarray):
        """
        接收到新的一幀影像時觸發
        - 從 rtcToCamQueue 取出最新的位置資料
        - 根據 class_name 畫不同顏色的框（cavity → 紅色，其他 → 綠色）
        - 將畫好框的影像傳給 camWidget 顯示
        """
        display_frame = frame.copy()  # 複製一份，避免修改原始 frame

        try:
            # 非阻塞取出最新的位置資料
            posStr: str | bytes | None = self.rtcToCamQueue.get_nowait()

            if posStr:
                # 處理 bytes → str
                if isinstance(posStr, bytes):
                    posStr = posStr.decode('utf-8')

                # 解析 JSON
                posJson: Any = json.loads(posStr)

                # 取出 detections 列表
                detections = posJson.get("detections", [])

                for det in detections:
                    # 取出 bbox [x1, y1, x2, y2]
                    bbox = det.get("bbox")
                    if not isinstance(bbox, list) or len(bbox) != 4:
                        logger.warning(f"無效的 bbox 格式: {bbox}")
                        continue

                    try:
                        x1, y1, x2, y2 = map(int, bbox)
                    except (ValueError, TypeError):
                        logger.warning(f"無法轉換 bbox 座標: {bbox}")
                        continue

                    # 根據 class_name 決定顏色
                    class_name = det.get("class_name", "unknown").lower()  # 轉小寫防大小寫差異
                    confidence = det.get("confidence", 0.0)

                    if "cavity" in class_name:  # 包含 "cavity" 就算（可精確改成 == "cavity"）
                        color = (0, 0, 255)  # BGR 紅色
                        label_color = (0, 0, 255)
                    else:
                        color = (0, 255, 0)  # BGR 綠色
                        label_color = (0, 255, 0)

                    # 畫矩形框
                    cv2.rectangle(
                        display_frame,
                        (x1, y1),
                        (x2, y2),
                        color,
                        3  # 粗一點更明顯，2 → 3
                    )

                    # 畫標籤：類別名稱 + 信心度
                    label = f"{det.get('class_name', 'unknown')} {confidence:.2f}"
                    # 文字背景（可選，讓文字更清楚）
                    text_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                    text_bg = (x1, y1 - 25, x1 + text_size[0], y1 - 5)
                    cv2.rectangle(display_frame, (text_bg[0], text_bg[1]), (text_bg[2], text_bg[3]), (0, 0, 0),
                                  -1)  # 黑色背景

                    cv2.putText(
                        display_frame,
                        label,
                        (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        label_color,
                        2
                    )

                    # 可選：畫 object_id
                    obj_id = det.get("object_id")
                    if obj_id is not None:
                        cv2.putText(
                            display_frame,
                            f"ID:{obj_id}",
                            (x1, y2 + 20),  # 框下方
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.6,
                            (255, 255, 255),  # 白色
                            2
                        )

        except Empty:
            pass  # 無新資料，保持原樣

        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解析失敗: {e}")

        except Exception as e:
            logger.error(f"onFrameArrived 錯誤: {e}", exc_info=True)

        # 最後傳給 widget
        h, w = display_frame.shape[:2]
        self.camWidget.setTextureData(
            display_frame,
            w,
            h,
            PixelFormat.BGR24
        )

    def stopReadFrameThreadFunction(self):
        self.readFrameThreadIsRunning.clear()

        if self.readFrameThread is not None:
            self.readFrameThread.join(timeout=1.0)
            self.readFrameThread = None

    def openOrCloseDetection(self):
        if self.rtcSenderIsRunning.is_set():
            # 正在運行 → 關閉
            self.rtcSender.close()
            self.rtcSenderIsRunning.clear()
            self.openOrCloseDetBtn.setText(self.tr("Open Detection"))
            self.mStatusText.setText(self.STATUS_STOPPED)
            self.mStatusText.setStyleSheet("color: gray;")  # 可選：變灰色表示停止

            print("RTC Detection 已關閉")

        else:
            # 沒運行 → 開啟（先檢查相機）
            if not self.camera.is_opened():
                self.mStatusText.setText("相機未開啟，無法啟動")
                self.mStatusText.setStyleSheet("color: red;")
                QMessageBox.warning(self, "警告", "請先開啟相機")
                return

            # 顯示「正在啟動」
            self.mStatusText.setText(self.STATUS_STARTING)
            self.mStatusText.setStyleSheet("color: blue;")

            def readCameraCallBack() -> ndarray | None:
                if not self.camera.is_opened():
                    return None
                try:
                    return self.camToRtcQueue.get_nowait()  # 取最新幀
                except Empty:
                    return None

            def readRTCFunc(msg: str | bytes):
                self.put_latest(self.rtcToCamQueue, msg)

            try:
                self.rtcSender.open(readCameraCallBack, readRTCFunc)
                self.rtcSenderIsRunning.set()
                self.openOrCloseDetBtn.setText(self.tr("Detection running"))

                # 初始設為「連線中」
                self.mStatusText.setText(self.STATUS_CONNECTING)
                self.mStatusText.setStyleSheet("color: orange;")

                print("RTC Detection 已啟動")

            except Exception as e:
                error_msg = f"啟動失敗: {str(e)}"
                print(error_msg)
                self.mStatusText.setText(self.STATUS_FAILED)
                self.mStatusText.setStyleSheet("color: red;")
                QMessageBox.critical(self, "錯誤", error_msg)
                # 恢復按鈕
                self.openOrCloseDetBtn.setText(self.tr("Open Detection"))

    @staticmethod
    def put_latest(queue, item):
        while True:
            try:
                queue.put_nowait(item)
                break
            except Full:
                try:
                    _ = queue.get_nowait()  # 清掉旧值
                except Empty:
                    break


if __name__ == "__main__":
    app = QApplication(sys.argv)
    apply_stylesheet(app, theme='dark_teal.xml')

    # 關鍵：把 asyncio 綁到 Qt 的事件循環上
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    # 現在就可以安全地使用 asyncio.create_task()、asyncio.sleep() 等
    window = MainWindow()  # 你的主視窗
    window.show()

    with loop:  # 推薦這樣寫，確保乾淨關閉
        sys.exit(loop.run_forever())
