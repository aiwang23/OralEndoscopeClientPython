import sys
import threading
import time
from queue import Queue, Full, Empty
from threading import Event

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QStatusBar, QLabel, QPushButton, QComboBox
)
from numpy import ndarray
from qt_material import apply_stylesheet

from Camera import Camera
from RTCSender import RTCSender
from RenderWidget import RenderWidget, PixelFormat


class MainWindow(QMainWindow):
    signalFrame: Signal = Signal(object)  # frame: ndarray

    def __init__(self):
        super().__init__()
        self.camWidget: RenderWidget | None = None
        self.openOrCloseDetBtn: QPushButton | None = None
        self.makeReportBtn: QPushButton | None = None
        self.camListComBoBox: QComboBox | None = None
        self.camListBtn: QPushButton | None = None

        self.readFrameThread: threading.Thread | None = None
        self.readFrameThreadIsRunning: Event = threading.Event()  # set true; clear false
        self.readFrameThreadIsRunning.clear()

        self.camera: Camera | None = Camera()
        self.rtcSender: RTCSender = RTCSender()
        self.camToRtcQueue: Queue = Queue(1)

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
        mStatusText = QLabel("running", self)
        mStatusBar.addWidget(mStatusText)
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
        h, w = frame.shape[:2]
        self.camWidget.setTextureData(
            frame,
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

        def readCallBack() -> ndarray | None:
            if not self.camera.is_opened():
                return None
            try:
                return self.camToRtcQueue.get_nowait()  # 非阻塞取最新帧
            except Empty:
                return None

        self.rtcSender.open(readCallBack)

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

    print(Camera.devices())

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
