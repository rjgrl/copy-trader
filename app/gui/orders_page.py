"""Orders table page with dry-run cleanup."""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


def _order_ids_from_selection(table: QTableWidget) -> set[int]:
    ids: set[int] = set()
    model = table.selectionModel()
    if model is None:
        return ids
    for index in model.selectedRows():
        item = table.item(index.row(), 0)
        if item is None:
            continue
        oid = item.data(Qt.ItemDataRole.UserRole)
        if oid is not None:
            ids.add(int(oid))
    return ids


def fill_orders_table(table: QTableWidget, rows: list) -> None:
    """Render order rows, labeling dry-run fills clearly."""
    keep = _order_ids_from_selection(table)
    table.setRowCount(len(rows))
    for i, o in enumerate(rows):
        created = getattr(o, "created_at", None)
        time_s = created.strftime("%H:%M:%S") if created else "—"
        dry = bool(getattr(o, "dry_run", False))
        ticket = getattr(o, "mt5_ticket", None)
        status = getattr(o, "status", "") or ""
        if dry and status and "DRY" not in status.upper():
            status = f"DRY RUN / {status}"
        elif dry and not status:
            status = "DRY RUN"
        vals = [
            str(getattr(o, "signal_id", "")),
            str(ticket) if ticket else ("DRY" if dry else "—"),
            getattr(o, "symbol", "") or "",
            getattr(o, "direction", "") or "",
            str(getattr(o, "volume", "") or ""),
            str(getattr(o, "entry_price", "") or ""),
            str(getattr(o, "take_profit", "") or ""),
            str(getattr(o, "stop_loss", "") or ""),
            "DRY RUN" if dry else "LIVE",
            status,
            time_s,
        ]
        for c, val in enumerate(vals):
            item = QTableWidgetItem(val)
            if getattr(o, "id", None) is not None and c == 0:
                item.setData(Qt.ItemDataRole.UserRole, int(o.id))
            if dry:
                item.setForeground(Qt.GlobalColor.darkYellow)
            table.setItem(i, c, item)

    if not keep:
        return
    model = table.selectionModel()
    if model is None:
        return
    flags = (
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows
    )
    for i in range(table.rowCount()):
        item = table.item(i, 0)
        if item is None:
            continue
        oid = item.data(Qt.ItemDataRole.UserRole)
        if oid is not None and int(oid) in keep:
            model.select(table.model().index(i, 0), flags)


class OrdersPage(QWidget):
    delete_selected_requested = Signal()
    delete_all_dry_run_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        title = QLabel("Orders")
        title.setStyleSheet("font-size:18px;font-weight:700;")
        root.addWidget(title)
        hint = QLabel(
            "Dry Run orders are fake fills (never sent to MT5). Select one or more, then delete."
        )
        hint.setStyleSheet("color:#6b7280;")
        root.addWidget(hint)

        bar = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_delete_selected = QPushButton("Delete selected dry-run")
        self.btn_delete_all_dry = QPushButton("Delete all dry-run")
        self.btn_delete_all_dry.setObjectName("Danger")
        bar.addWidget(self.btn_refresh)
        bar.addStretch(1)
        bar.addWidget(self.btn_delete_selected)
        bar.addWidget(self.btn_delete_all_dry)
        root.addLayout(bar)

        self.table = QTableWidget(0, 11)
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
                "Mode",
                "Status",
                "Time",
            ]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        root.addWidget(self.table, 1)

        self.btn_delete_selected.clicked.connect(self.delete_selected_requested.emit)
        self.btn_delete_all_dry.clicked.connect(self.delete_all_dry_run_requested.emit)

    def set_orders(self, rows: list) -> None:
        fill_orders_table(self.table, rows)

    def selected_order_ids(self) -> list[int]:
        ids: list[int] = []
        seen: set[int] = set()
        for index in self.table.selectionModel().selectedRows():
            item = self.table.item(index.row(), 0)
            if item is None:
                continue
            oid = item.data(Qt.ItemDataRole.UserRole)
            if oid is None:
                continue
            order_id = int(oid)
            if order_id not in seen:
                seen.add(order_id)
                ids.append(order_id)
        return ids
