import sys
from typing import Optional, Tuple

import cv2
import numpy as np
from cv2_enumerate_cameras import enumerate_cameras
from cv2_enumerate_cameras.camera_info import CameraInfo


class Camera:
    def __init__(self, index: Optional[int] = None):
        self.cam: Optional[cv2.VideoCapture] = None

        if index is not None:
            self.cam  = cv2.VideoCapture(index)

    def __del__(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


    def open(self, index: int) -> bool:
        self.close()

        self.cam = cv2.VideoCapture(index)
        if not self.cam.isOpened():
            self.cam.release()
            self.cam = None
            return False

        return True

    def close(self):
        if self.cam is not None:
            self.cam.release()
            self.cam = None

    def is_opened(self) -> bool:
        return self.cam is not None and self.cam.isOpened()

    def read(self) -> np.ndarray:
        if not self.is_opened():
            raise RuntimeError("Camera is not opened")
        ret, frame = self.cam.read()
        if not ret:
            raise RuntimeError("Failed to read frame")
        return frame

    @staticmethod
    def devices(backend: Optional[int] = None) -> list[CameraInfo]:
        """

        :rtype: list[CameraInfo]
        """
        if backend is None:
            if sys.platform.startswith("win"):
                backend = cv2.CAP_MSMF
            elif sys.platform.startswith("linux"):
                backend = cv2.CAP_V4L2
            elif sys.platform == "darwin":
                backend = cv2.CAP_AVFOUNDATION
            else:
                backend = cv2.CAP_ANY
        return enumerate_cameras(backend)

