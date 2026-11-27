# -*- coding: utf-8 -*-
"""
WheelGuard: impede que a roda do mouse altere acidentalmente QComboBox, QSpinBox
e QDoubleSpinBox, encaminhando a rolagem para a QScrollArea ancestral.
"""

from PyQt5.QtCore import QEvent, QObject
from PyQt5.QtWidgets import (
    QAbstractScrollArea, QApplication, QComboBox, QDoubleSpinBox, QSpinBox
)


class WheelGuard(QObject):
    """Bloqueia alterações via scroll em selects/spinboxes e repassa ao scroll pai."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and isinstance(obj, (QComboBox, QSpinBox, QDoubleSpinBox)):
            if isinstance(obj, QComboBox) and obj.view() and obj.view().isVisible():
                return False

            event.ignore()
            parent = obj.parentWidget()
            while parent is not None:
                if isinstance(parent, QAbstractScrollArea):
                    QApplication.sendEvent(parent.viewport(), event)
                    break
                parent = parent.parentWidget()
            return True

        return False


def ensure_global_wheel_guard():
    """Instala o WheelGuard uma única vez na instância QApplication ativa."""
    app = QApplication.instance()
    if app is None:
        return None
    if getattr(app, "_wheel_guard_installed", False):
        return getattr(app, "_wheel_guard", None)

    guard = WheelGuard(app)
    app.installEventFilter(guard)
    app._wheel_guard = guard
    app._wheel_guard_installed = True
    return guard
