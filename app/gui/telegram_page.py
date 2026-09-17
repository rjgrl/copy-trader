"""Telegram sources page."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
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
            "Click a row or the checkbox to choose groups. Selections are saved "
            "immediately and used when you Start Listening."
        )
        hint.setStyleSheet("color:#6b7280;")
        hint.setWordWrap(True)
        root.addWidget(hint)

        bar = QHBoxLayout()
        self.btn_connect = QPushButton("Connect / Auth")
        self.btn_connect.setObjectName("Primary")
        self.btn_load = QPushButton("Load Dialogs")
        self.btn_refresh = QPushButton("Refresh Sources")
        self.btn_listen = QPushButton("Start Listening")
        self.btn_listen.setObjectName("Primary")
        bar.addWidget(self.btn_connect)
        bar.addWidget(self.btn_load)
        bar.addWidget(self.btn_refresh)
        bar.addWidget(self.btn_listen)
        bar.addStretch(1)
        root.addLayout(bar)

        self.lbl_selected = QLabel("No groups selected")
        self.lbl_selected.setStyleSheet("color:#374151;font-weight:600;")
        root.addWidget(self.lbl_selected)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Listen", "Name", "Telegram ID", "Type", "Last Message"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 70)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.cellClicked.connect(self._on_cell_clicked)
        root.addWidget(self.table, 1)

        self._dialogs: list[dict] = []

    def has_rows(self) -> bool:
        return self.table.rowCount() > 0

    def enabled_count(self) -> int:
        return sum(1 for row in self.collect_selections() if row["enabled"])

    def collect_selections(self) -> list[dict]:
        """Current checkbox state in the table (source of truth for listening)."""
        rows: list[dict] = []
        for i in range(self.table.rowCount()):
            telegram_id = self._row_telegram_id(i)
            if telegram_id is None:
                continue
            name_item = self.table.item(i, 1)
            type_item = self.table.item(i, 3)
            cb = self._checkbox_at(i)
            rows.append(
                {
                    "telegram_id": telegram_id,
                    "name": name_item.text() if name_item else "",
                    "type": type_item.text() if type_item else "unknown",
                    "enabled": bool(cb.isChecked()) if cb is not None else False,
                }
            )
        return rows

    def set_checked(self, telegram_id: int, enabled: bool) -> bool:
        """Set one row's checkbox without relying on mouse clicks."""
        for i in range(self.table.rowCount()):
            if self._row_telegram_id(i) != telegram_id:
                continue
            self._set_row_checked(i, enabled, persist=False)
            self._refresh_selected_label()
            return True
        return False

    def set_sources(self, sources: list) -> None:
        current = {s["telegram_id"]: s["enabled"] for s in self.collect_selections()}
        rows = []
        for src in sources:
            tid = int(getattr(src, "telegram_id", 0) or 0)
            if not tid:
                continue
            rows.append(
                {
                    "telegram_id": tid,
                    "name": str(getattr(src, "name", "") or ""),
                    "type": str(getattr(src, "source_type", "") or "unknown"),
                    "enabled": current.get(tid, bool(getattr(src, "enabled", False))),
                    "last_message_id": getattr(src, "last_message_id", None),
                }
            )
        self._rebuild(rows)

    def set_dialogs(self, dialogs: list[dict]) -> None:
        current = {s["telegram_id"]: s["enabled"] for s in self.collect_selections()}
        self._dialogs = list(dialogs)
        rows = []
        for d in dialogs:
            tid = int(d["telegram_id"])
            rows.append(
                {
                    "telegram_id": tid,
                    "name": str(d.get("name") or ""),
                    "type": str(d.get("type") or "unknown"),
                    "enabled": current.get(tid, bool(d.get("monitored"))),
                    "last_message_id": d.get("last_message_id"),
                }
            )
        self._rebuild(rows)

    def _rebuild(self, rows: list[dict]) -> None:
        self._disconnect_checkboxes()
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self._put_row(
                i,
                int(row["telegram_id"]),
                str(row.get("name") or ""),
                str(row.get("type") or "unknown"),
                bool(row.get("enabled")),
                row.get("last_message_id"),
            )
        self._refresh_selected_label()

    def _disconnect_checkboxes(self) -> None:
        """Prevent destroyed checkboxes from emitting and wiping saved groups."""
        for i in range(self.table.rowCount()):
            cb = self._checkbox_at(i)
            if cb is None:
                continue
            cb.blockSignals(True)
            try:
                cb.clicked.disconnect()
            except (TypeError, RuntimeError):
                pass

    def _put_row(
        self,
        row: int,
        telegram_id: int,
        name: str,
        dtype: str,
        enabled: bool,
        last_message_id: int | None,
    ) -> None:
        wrap = QWidget()
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cb = QCheckBox()
        cb.setMinimumSize(22, 22)
        cb.blockSignals(True)
        cb.setChecked(enabled)
        cb.blockSignals(False)
        cb.setProperty("telegram_id", telegram_id)
        cb.setProperty("dialog_name", name)
        cb.setProperty("dialog_type", dtype)
        # Read isChecked() from the widget — do not trust the clicked(bool) argument
        cb.clicked.connect(lambda _checked=False, box=cb: self._on_user_check(box))
        layout.addWidget(cb)
        self.table.setCellWidget(row, 0, wrap)

        name_item = QTableWidgetItem(name)
        id_item = QTableWidgetItem(str(telegram_id))
        id_item.setData(Qt.ItemDataRole.UserRole, telegram_id)
        type_item = QTableWidgetItem(dtype)
        last_item = QTableWidgetItem(str(last_message_id) if last_message_id else "—")
        self.table.setItem(row, 1, name_item)
        self.table.setItem(row, 2, id_item)
        self.table.setItem(row, 3, type_item)
        self.table.setItem(row, 4, last_item)

    def _checkbox_at(self, row: int) -> QCheckBox | None:
        widget = self.table.cellWidget(row, 0)
        if widget is None:
            return None
        if isinstance(widget, QCheckBox):
            return widget
        found = widget.findChild(QCheckBox)
        return found if isinstance(found, QCheckBox) else None

    def _row_telegram_id(self, row: int) -> int | None:
        id_item = self.table.item(row, 2)
        if id_item is not None:
            stored = id_item.data(Qt.ItemDataRole.UserRole)
            if stored is not None:
                try:
                    return int(stored)
                except (TypeError, ValueError):
                    pass
            try:
                return int(id_item.text())
            except (TypeError, ValueError):
                pass
        cb = self._checkbox_at(row)
        if cb is None:
            return None
        try:
            return int(cb.property("telegram_id"))
        except (TypeError, ValueError):
            return None

    def _on_cell_clicked(self, row: int, column: int) -> None:
        if column == 0:
            return
        cb = self._checkbox_at(row)
        if cb is None:
            return
        self._set_row_checked(row, not cb.isChecked(), persist=True)

    def _set_row_checked(self, row: int, enabled: bool, *, persist: bool) -> None:
        cb = self._checkbox_at(row)
        if cb is None:
            return
        cb.blockSignals(True)
        cb.setChecked(enabled)
        cb.blockSignals(False)
        if persist:
            self._on_user_check(cb)
        else:
            self._refresh_selected_label()

    def _on_user_check(self, box: QCheckBox) -> None:
        try:
            telegram_id = int(box.property("telegram_id"))
        except (TypeError, ValueError):
            return
        self.source_toggled.emit(
            telegram_id,
            bool(box.isChecked()),
            str(box.property("dialog_name") or ""),
            str(box.property("dialog_type") or "unknown"),
        )
        self._refresh_selected_label()

    def _refresh_selected_label(self) -> None:
        n = self.enabled_count()
        if n == 0:
            self.lbl_selected.setText("No groups selected")
        elif n == 1:
            self.lbl_selected.setText("1 group selected for listening")
        else:
            self.lbl_selected.setText(f"{n} groups selected for listening")
