"""Telegram sources page."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class TelegramPage(QWidget):
    """Select which Telegram chats are monitored for signals."""

    source_toggled = Signal(int, bool, str, str)  # id, enabled, name, type

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("Telegram Sources")
        title.setStyleSheet("font-size:18px;font-weight:700;")
        root.addWidget(title)
        hint = QLabel(
            "Only enabled sources generate trades. Connect Telegram, load dialogs, then enable."
        )
        hint.setStyleSheet("color:#6b7280;")
        root.addWidget(hint)

        bar = QHBoxLayout()
        self.btn_connect = QPushButton("Connect / Auth")
        self.btn_connect.setObjectName("Primary")
        self.btn_load = QPushButton("Load Dialogs")
        self.btn_refresh = QPushButton("Refresh Sources")
        bar.addWidget(self.btn_connect)
        bar.addWidget(self.btn_load)
        bar.addWidget(self.btn_refresh)
        bar.addStretch(1)
        root.addLayout(bar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Enabled", "Name", "Telegram ID", "Type", "Last Message"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table, 1)

        self._dialogs: list[dict] = []

    def set_sources(self, sources: list) -> None:
        self._dialogs = []
        self.table.setRowCount(len(sources))
        for i, src in enumerate(sources):
            tid = int(getattr(src, "telegram_id", 0) or 0)
            name = str(getattr(src, "name", "") or "")
            dtype = str(getattr(src, "source_type", "") or "unknown")
            enabled = bool(getattr(src, "enabled", False))
            self._put_row(i, tid, name, dtype, enabled, getattr(src, "last_message_id", None))

    def set_dialogs(self, dialogs: list[dict]) -> None:
        self._dialogs = dialogs
        self.table.setRowCount(len(dialogs))
        for i, d in enumerate(dialogs):
            self._put_row(
                i,
                int(d["telegram_id"]),
                str(d["name"]),
                str(d["type"]),
                bool(d.get("monitored")),
                None,
            )

    def _put_row(
        self,
        row: int,
        telegram_id: int,
        name: str,
        dtype: str,
        enabled: bool,
        last_message_id: int | None,
    ) -> None:
        cb = QCheckBox()
        cb.setChecked(enabled)
        cb.setProperty("telegram_id", telegram_id)
        cb.setProperty("dialog_name", name)
        cb.setProperty("dialog_type", dtype)
        cb.toggled.connect(
            lambda checked, tid=telegram_id, n=name, t=dtype: self.source_toggled.emit(
                tid, checked, n, t
            )
        )
        self.table.setCellWidget(row, 0, cb)
        self.table.setItem(row, 1, QTableWidgetItem(name))
        self.table.setItem(row, 2, QTableWidgetItem(str(telegram_id)))
        self.table.setItem(row, 3, QTableWidgetItem(dtype))
        self.table.setItem(
            row, 4, QTableWidgetItem(str(last_message_id) if last_message_id else "—")
        )
