"""Signals table page."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
)


class SignalsPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        title = QLabel("Signals")
        title.setStyleSheet("font-size:18px;font-weight:700;")
        root.addWidget(title)

        bar = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        bar.addWidget(self.btn_refresh)
        bar.addStretch(1)
        root.addLayout(bar)

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            [
                "Time",
                "Source",
                "Dir",
                "Symbol",
                "Entry",
                "Exec",
                "Dev",
                "TPs",
                "SL",
                "Status",
            ]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table, 2)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("Select a signal for details…")
        self.detail.setMaximumHeight(160)
        root.addWidget(self.detail)
        self.table.itemSelectionChanged.connect(self._on_select)
        self._rows: list = []

    def set_signals(self, rows: list) -> None:
        self._rows = rows
        self.table.setRowCount(len(rows))
        for i, sig in enumerate(rows):
            received = getattr(sig, "received_at", None)
            time_s = received.strftime("%H:%M:%S") if received else "—"
            tps = sum(
                1
                for x in (
                    getattr(sig, "tp1", None),
                    getattr(sig, "tp2", None),
                    getattr(sig, "tp3", None),
                )
                if x is not None
            )
            vals = [
                time_s,
                getattr(sig, "source_name", "") or "",
                getattr(sig, "direction", "") or "",
                getattr(sig, "mapped_mt5_symbol", None)
                or getattr(sig, "symbol", "")
                or "",
                str(getattr(sig, "entry_price", "") or ""),
                str(getattr(sig, "actual_execution_price", "") or ""),
                str(getattr(sig, "entry_deviation", "") or ""),
                str(tps),
                str(getattr(sig, "stop_loss", "") or ""),
                getattr(sig, "status", "") or "",
            ]
            for c, val in enumerate(vals):
                self.table.setItem(i, c, QTableWidgetItem(val))

    def _on_select(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        idx = rows[0].row()
        if idx < 0 or idx >= len(self._rows):
            return
        sig = self._rows[idx]
        self.detail.setPlainText(
            f"ID: {sig.id}\n"
            f"Chat/Msg: {sig.telegram_chat_id} / {sig.telegram_message_id}\n"
            f"Status: {sig.status}\n"
            f"Reason: {sig.failure_reason or '—'}\n"
            f"Mapped: {sig.mapped_mt5_symbol}\n"
            f"Raw:\n{sig.raw_message}"
        )
