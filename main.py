# ============ main.py ============
import asyncio
import sys

import qasync
from PySide6.QtWidgets import QApplication
from qt_material import apply_stylesheet

from MainWindow import MainWindow

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
    # sys.exit(app.exec())
