"""Application logs page."""

from __future__ import annotations

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget


class LogsPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        title = QLabel("Logs")
        title.setStyleSheet("font-size:18px;font-weight:700;")
        root.addWidget(title)

        bar = QHBoxLayout()
        self.btn_clear = QPushButton("Clear")
        bar.addWidget(self.btn_clear)
        bar.addStretch(1)
        root.addLayout(bar)

        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; font-size: 12px;"
        )
        root.addWidget(self.view, 1)
        self.btn_clear.clicked.connect(self.view.clear)

    def append_log(self, message: str, level: str = "INFO") -> None:
        color = {
            "DEBUG": "#6b7280",
            "INFO": "#111827",
            "WARNING": "#b45309",
            "ERROR": "#b91c1c",
            "CRITICAL": "#7f1d1d",
        }.get(level.upper(), "#111827")
        self.view.append(f'<span style="color:{color}">{message}</span>')
        self.view.moveCursor(QTextCursor.MoveOperation.End)
