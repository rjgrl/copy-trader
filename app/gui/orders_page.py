"""Orders table page."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class OrdersPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        title = QLabel("Orders")
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
                "Signal",
                "Ticket",
                "Symbol",
                "Dir",
                "Vol",
                "Entry",
                "TP",
                "SL",
                "Status",
                "Time",
            ]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table, 1)

    def set_orders(self, rows: list) -> None:
        self.table.setRowCount(len(rows))
        for i, o in enumerate(rows):
            created = getattr(o, "created_at", None)
            time_s = created.strftime("%H:%M:%S") if created else "—"
            vals = [
                str(getattr(o, "signal_id", "")),
                str(getattr(o, "mt5_ticket", "") or ("DRY" if o.dry_run else "—")),
                getattr(o, "symbol", ""),
                getattr(o, "direction", ""),
                str(getattr(o, "volume", "")),
                str(getattr(o, "entry_price", "") or ""),
                str(getattr(o, "take_profit", "") or ""),
                str(getattr(o, "stop_loss", "") or ""),
                getattr(o, "status", ""),
                time_s,
            ]
            for c, val in enumerate(vals):
                self.table.setItem(i, c, QTableWidgetItem(val))
