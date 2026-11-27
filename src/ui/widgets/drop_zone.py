import os
from PyQt5.QtWidgets import QFrame
from PyQt5.QtCore import Qt, pyqtSignal
from src.config import SUPPORTED_EXTENSIONS

class DropZoneFrame(QFrame):
    """Quadro interativo para seleção de arquivo via clique ou arrastar e soltar (Drag and Drop)."""
    clicked = pyqtSignal()
    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                path = urls[0].toLocalFile()
                ext = os.path.splitext(path)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                path = urls[0].toLocalFile()
                if os.path.exists(path):
                    self.file_dropped.emit(path)
                    event.acceptProposedAction()
