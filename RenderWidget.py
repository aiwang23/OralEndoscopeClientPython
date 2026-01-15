# RenderWidget.py
from enum import Enum
from typing import Union, List
import numpy as np
from PySide6.QtOpenGL import QOpenGLTexture, QOpenGLShaderProgram, QOpenGLShader, QOpenGLVertexArrayObject, \
    QOpenGLBuffer
from PySide6.QtOpenGLWidgets import QOpenGLWidget

GLVERSION = "#version 330 core\n"

vertex_shader_src = GLVERSION + """
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec2 aTexCoord;
out vec2 TexCoord;
uniform vec2 u_scale;
void main()
{
    gl_Position = vec4(aPos.x * u_scale.x, aPos.y * u_scale.y, aPos.z, 1.0);
    TexCoord = aTexCoord;
}
"""

fragment_shader_src = GLVERSION + """
in vec2 TexCoord;
out vec4 FragColor;

uniform sampler2D textureY;
uniform sampler2D textureU;
uniform sampler2D textureV;
uniform bool isYUV;

void main()
{
    if (isYUV) {
        // 全范围YUV (0-255) 到 RGB 转换
        float y = texture(textureY, TexCoord).r;
        float u = texture(textureU, TexCoord).r - 0.5;
        float v = texture(textureV, TexCoord).r - 0.5;

        // JPEG/全范围 YUV 转换矩阵
        float r = y + 1.140 * v;
        float g = y - 0.395 * u - 0.581 * v;
        float b = y + 2.032 * u;

        FragColor = vec4(clamp(r, 0.0, 1.0), clamp(g, 0.0, 1.0), clamp(b, 0.0, 1.0), 1.0);
    } else {
        FragColor = texture(textureY, TexCoord);
    }
}
"""


class PixelFormat(Enum):
    YUV420P = 0
    RGB24 = 3
    BGR24 = 4


class RenderWidget(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.m_shaderProgram = None
        self.m_vao = None
        self.m_vbo = None
        self.m_width = 0
        self.m_height = 0
        self.m_scaleX = 1.0
        self.m_scaleY = 1.0
        self.m_textureY = None
        self.m_textureU = None
        self.m_textureV = None
        self.m_currentFormat = None
        self.m_yuvPlanes = None

    def __del__(self):
        self.makeCurrent()
        if self.m_vao:
            self.m_vao.destroy()
        if self.m_vbo:
            self.m_vbo.destroy()
        for tex in (self.m_textureY, self.m_textureU, self.m_textureV):
            if tex:
                tex.destroy()
        if self.m_shaderProgram:
            del self.m_shaderProgram
        self.doneCurrent()

    def updateAspectRatio(self):
        if self.m_width <= 0 or self.m_height <= 0:
            self.m_scaleX = self.m_scaleY = 1.0
            return
        windowAspect = self.width() / float(self.height())
        videoAspect = self.m_width / float(self.m_height)
        if windowAspect > videoAspect:
            self.m_scaleX = videoAspect / windowAspect
            self.m_scaleY = 1.0
        else:
            self.m_scaleX = 1.0
            self.m_scaleY = windowAspect / videoAspect

    def setTextureData(self, buffer: Union[np.ndarray, List[np.ndarray]], width: int, height: int, fmt: PixelFormat):
        if width <= 0 or height <= 0:
            return

        self.makeCurrent()
        self.m_width = width
        self.m_height = height
        self.m_currentFormat = fmt
        self.updateAspectRatio()

        for tex in (self.m_textureY, self.m_textureU, self.m_textureV):
            if tex:
                tex.destroy()
        self.m_textureY = self.m_textureU = self.m_textureV = None
        self.m_yuvPlanes = None

        if fmt in (PixelFormat.RGB24, PixelFormat.BGR24):
            if not isinstance(buffer, np.ndarray) or buffer.ndim != 3 or buffer.shape[2] != 3:
                raise ValueError("RGB/BGR 必须是 (h, w, 3) 的 ndarray")

            self.m_textureY = QOpenGLTexture(QOpenGLTexture.Target2D)
            self.m_textureY.setFormat(QOpenGLTexture.RGB8_UNorm)
            self.m_textureY.setSize(width, height)
            self.m_textureY.allocateStorage()
            self.m_textureY.setMinMagFilters(QOpenGLTexture.Linear, QOpenGLTexture.Linear)

            pixel_format = QOpenGLTexture.BGR if fmt == PixelFormat.BGR24 else QOpenGLTexture.RGB
            data_bytes = buffer.astype(np.uint8).tobytes()
            self.m_textureY.setData(pixel_format, QOpenGLTexture.UInt8, data_bytes)

        elif fmt == PixelFormat.YUV420P:
            if not isinstance(buffer, list) or len(buffer) != 3:
                raise ValueError("YUV420P 必须传入 [Y, U, V] 三个 ndarray 平面")
            Y, U, V = buffer
            if Y.shape != (height, width) or U.shape != (height // 2, width // 2) or V.shape != (height // 2,
                                                                                                 width // 2):
                raise ValueError("YUV420P 平面尺寸不符合要求")

            self.m_textureY = QOpenGLTexture(QOpenGLTexture.Target2D)
            self.m_textureY.setFormat(QOpenGLTexture.R8_UNorm)
            self.m_textureY.setSize(width, height)
            self.m_textureY.allocateStorage()
            self.m_textureY.setMinMagFilters(QOpenGLTexture.Linear, QOpenGLTexture.Linear)
            self.m_textureY.setData(QOpenGLTexture.Red, QOpenGLTexture.UInt8, Y.astype(np.uint8).tobytes())

            self.m_textureU = QOpenGLTexture(QOpenGLTexture.Target2D)
            self.m_textureU.setFormat(QOpenGLTexture.R8_UNorm)
            self.m_textureU.setSize(width // 2, height // 2)
            self.m_textureU.allocateStorage()
            self.m_textureU.setMinMagFilters(QOpenGLTexture.Linear, QOpenGLTexture.Linear)
            self.m_textureU.setData(QOpenGLTexture.Red, QOpenGLTexture.UInt8, U.astype(np.uint8).tobytes())

            self.m_textureV = QOpenGLTexture(QOpenGLTexture.Target2D)
            self.m_textureV.setFormat(QOpenGLTexture.R8_UNorm)
            self.m_textureV.setSize(width // 2, height // 2)
            self.m_textureV.allocateStorage()
            self.m_textureV.setMinMagFilters(QOpenGLTexture.Linear, QOpenGLTexture.Linear)
            self.m_textureV.setData(QOpenGLTexture.Red, QOpenGLTexture.UInt8, V.astype(np.uint8).tobytes())

            self.m_yuvPlanes = (Y.astype(np.uint8).tobytes(), U.astype(np.uint8).tobytes(),
                                V.astype(np.uint8).tobytes())
        else:
            raise ValueError("不支持的像素格式")

        self.doneCurrent()
        self.update()

    def clear(self):
        self.makeCurrent()
        for tex in (self.m_textureY, self.m_textureU, self.m_textureV):
            if tex:
                tex.destroy()
        self.m_textureY = self.m_textureU = self.m_textureV = None
        self.m_yuvPlanes = None
        self.m_width = self.m_height = 0
        self.m_currentFormat = None
        self.m_scaleX = self.m_scaleY = 1.0
        self.doneCurrent()

        # 触发重绘，paintGL 会清屏
        self.update()

    def initializeGL(self):
        f = self.context().functions()
        f.glClearColor(0.0, 0.0, 0.0, 1.0)

        self.m_shaderProgram = QOpenGLShaderProgram(self)
        self.m_shaderProgram.addShaderFromSourceCode(QOpenGLShader.Vertex, vertex_shader_src)
        self.m_shaderProgram.addShaderFromSourceCode(QOpenGLShader.Fragment, fragment_shader_src)
        self.m_shaderProgram.link()

        vertices = np.array([
            -1.0, -1.0, 0.0, 0.0, 1.0,
            1.0, -1.0, 0.0, 1.0, 1.0,
            -1.0, 1.0, 0.0, 0.0, 0.0,
            1.0, 1.0, 0.0, 1.0, 0.0
        ], dtype=np.float32)

        self.m_vao = QOpenGLVertexArrayObject(self)
        self.m_vao.create()
        self.m_vao.bind()

        self.m_vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self.m_vbo.create()
        self.m_vbo.bind()
        self.m_vbo.allocate(vertices.tobytes(), vertices.nbytes)

        self.m_shaderProgram.bind()
        self.m_shaderProgram.enableAttributeArray(0)
        self.m_shaderProgram.enableAttributeArray(1)
        self.m_shaderProgram.setAttributeBuffer(0, 0x1406, 0, 3, 5 * 4)
        self.m_shaderProgram.setAttributeBuffer(1, 0x1406, 3 * 4, 2, 5 * 4)

        self.m_vao.release()
        self.m_vbo.release()
        self.m_shaderProgram.release()

    def resizeGL(self, w: int, h: int):
        self.updateAspectRatio()

    def paintGL(self):
        f = self.context().functions()

        # 清屏为黑色
        f.glClearColor(0.0, 0.0, 0.0, 1.0)
        f.glClear(0x4000)  # GL_COLOR_BUFFER_BIT

        # 如果没有纹理，就直接返回，保持黑屏
        if not self.m_shaderProgram or not self.m_textureY:
            return

        # 下面是原来的绘制逻辑
        self.m_shaderProgram.bind()
        self.m_vao.bind()
        self.m_shaderProgram.setUniformValue("u_scale", self.m_scaleX, self.m_scaleY)
        is_yuv = (self.m_currentFormat == PixelFormat.YUV420P)
        self.m_shaderProgram.setUniformValue("isYUV", is_yuv)

        self.m_textureY.bind(0)
        self.m_shaderProgram.setUniformValue("textureY", 0)
        if is_yuv:
            self.m_textureU.bind(1)
            self.m_shaderProgram.setUniformValue("textureU", 1)
            self.m_textureV.bind(2)
            self.m_shaderProgram.setUniformValue("textureV", 2)

        f.glDrawArrays(5, 0, 4)

        if is_yuv:
            self.m_textureV.release()
            self.m_textureU.release()
        self.m_textureY.release()

        self.m_vao.release()
        self.m_shaderProgram.release()


if __name__ == "__main__":
    import sys
    import cv2
    import numpy as np
    from PySide6.QtWidgets import QApplication, QMainWindow
    from PySide6.QtCore import QTimer

    class CameraApp(QMainWindow):
        def __init__(self):
            super().__init__()
            self.render_widget = RenderWidget()
            self.setCentralWidget(self.render_widget)
            self.resize(800, 600)

            self.cap = cv2.VideoCapture(0)
            if not self.cap.isOpened():
                print("错误：无法打开摄像头")
                sys.exit(-1)

            self.timer = QTimer(self)
            self.timer.timeout.connect(self.update_frame)
            self.timer.start(30)

        def update_frame(self):
            ret, frame = self.cap.read()
            if ret:
                h, w = frame.shape[:2]
                self.render_widget.setTextureData(frame, w, h, PixelFormat.BGR24)

        def closeEvent(self, event):
            self.cap.release()
            super().closeEvent(event)

    app = QApplication(sys.argv)
    window = CameraApp()
    window.show()
    sys.exit(app.exec())