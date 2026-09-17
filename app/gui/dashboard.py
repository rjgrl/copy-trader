"""Dashboard page — connection status, kill switch, recent signals."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.orders_page import fill_orders_table


class DashboardPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        title = QLabel("Dashboard")
        title.setProperty("class", "SectionTitle")
        title.setStyleSheet("font-size:18px;font-weight:700;")
        root.addWidget(title)

        # Status cards
        cards = QHBoxLayout()
        self.lbl_app = self._stat_card("Application", "IDLE")
        self.lbl_tg = self._stat_card("Telegram", "DISCONNECTED")
        self.lbl_mt5 = self._stat_card("MT5", "DISCONNECTED")
        self.lbl_copy = self._stat_card("Copy Trading", "OFF")
        for w in (self.lbl_app, self.lbl_tg, self.lbl_mt5, self.lbl_copy):
            cards.addWidget(w)
        root.addLayout(cards)

        # Account + kill switch
        mid = QHBoxLayout()
        account = QFrame()
        account.setObjectName("Card")
        al = QGridLayout(account)
        al.setContentsMargins(16, 16, 16, 16)
        self.acc_login = QLabel("—")
        self.acc_server = QLabel("—")
        self.acc_balance = QLabel("—")
        self.acc_equity = QLabel("—")
        self.acc_margin = QLabel("—")
        rows = [
            ("Account", self.acc_login),
            ("Server", self.acc_server),
            ("Balance", self.acc_balance),
            ("Equity", self.acc_equity),
            ("Free margin", self.acc_margin),
        ]
        for i, (k, v) in enumerate(rows):
            al.addWidget(QLabel(k), i, 0)
            al.addWidget(v, i, 1)
        mid.addWidget(account, 2)

        actions = QFrame()
        actions.setObjectName("Card")
        al2 = QVBoxLayout(actions)
        al2.setContentsMargins(16, 16, 16, 16)
        self.btn_connect_mt5 = QPushButton("Connect MT5")
        self.btn_connect_mt5.setObjectName("Primary")
        self.btn_connect_tg = QPushButton("Connect Telegram")
        self.btn_listen = QPushButton("Start Listening")
        self.btn_listen.setObjectName("Primary")
        self.btn_stop_listen = QPushButton("Stop Listening")
        self.btn_simulate = QPushButton("Simulate Sample Signal")
        self.btn_kill = QPushButton("STOP COPYING")
        self.btn_kill.setObjectName("Danger")
        self.btn_kill.setCheckable(True)
        self.lbl_dry = QLabel("Dry Run: —")
        for w in (
            self.btn_connect_mt5,
            self.btn_connect_tg,
            self.btn_listen,
            self.btn_stop_listen,
            self.btn_simulate,
            self.btn_kill,
            self.lbl_dry,
        ):
            al2.addWidget(w)
        al2.addStretch(1)
        mid.addWidget(actions, 1)
        root.addLayout(mid)

        recent_title = QLabel("Recent Signals")
        recent_title.setStyleSheet("font-weight:600;")
        root.addWidget(recent_title)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Time", "Source", "Direction", "Symbol", "Entry", "Status"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        root.addWidget(self.table, 1)

        orders_title = QLabel("Recent Orders (including Dry Run)")
        orders_title.setStyleSheet("font-weight:600;")
        root.addWidget(orders_title)
        orders_bar = QHBoxLayout()
        self.btn_delete_selected = QPushButton("Delete selected dry-run")
        self.btn_delete_all_dry = QPushButton("Delete all dry-run")
        self.btn_delete_all_dry.setObjectName("Danger")
        orders_bar.addWidget(self.btn_delete_selected)
        orders_bar.addWidget(self.btn_delete_all_dry)
        orders_bar.addStretch(1)
        root.addLayout(orders_bar)
        self.orders_table = QTableWidget(0, 11)
        self.orders_table.setHorizontalHeaderLabels(
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
        self.orders_table.horizontalHeader().setStretchLastSection(True)
        self.orders_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.orders_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.orders_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        root.addWidget(self.orders_table, 1)

    def _stat_card(self, title: str, value: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        t = QLabel(title)
        t.setStyleSheet("color:#6b7280;font-size:12px;")
        v = QLabel(value)
        v.setObjectName("value")
        v.setStyleSheet("font-size:15px;font-weight:700;")
        layout.addWidget(t)
        layout.addWidget(v)
        frame.value_label = v  # type: ignore[attr-defined]
        return frame

    def update_snapshot(self, snap: dict) -> None:
        tg = snap.get("telegram", "disconnected").upper()
        mt5 = snap.get("mt5", "disconnected").upper()
        listening = snap.get("listening", False)
        self.lbl_tg.value_label.setText(tg)  # type: ignore[attr-defined]
        self.lbl_mt5.value_label.setText(mt5)  # type: ignore[attr-defined]
        self.lbl_app.value_label.setText("LISTENING" if listening else "IDLE")  # type: ignore[attr-defined]
        copy = "ON" if snap.get("copy_trading") else "OFF"
        if snap.get("dry_run"):
            copy += " (DRY RUN)"
        self.lbl_copy.value_label.setText(copy)  # type: ignore[attr-defined]
        self.lbl_dry.setText(
            f"Dry Run: {'ON' if snap.get('dry_run') else 'OFF'} | "
            f"Kill Switch: {'ACTIVE' if snap.get('kill_switch') else 'off'}"
        )
        self.btn_kill.setChecked(bool(snap.get("kill_switch")))
        if snap.get("kill_switch"):
            self.btn_kill.setText("RESUME COPYING")
        else:
            self.btn_kill.setText("STOP COPYING")

        acc = snap.get("account") or {}
        self.acc_login.setText(str(acc.get("login", "—")))
        self.acc_server.setText(str(acc.get("server", "—")))
        bal = acc.get("balance")
        eq = acc.get("equity")
        free = acc.get("margin_free")
        self.acc_balance.setText(f"{bal:.2f}" if isinstance(bal, (int, float)) else "—")
        self.acc_equity.setText(f"{eq:.2f}" if isinstance(eq, (int, float)) else "—")
        self.acc_margin.setText(f"{free:.2f}" if isinstance(free, (int, float)) else "—")

        rows = snap.get("recent_signals") or []
        self.table.setRowCount(len(rows))
        for i, sig in enumerate(rows):
            received = getattr(sig, "received_at", None)
            time_s = received.strftime("%H:%M:%S") if received else "—"
            vals = [
                time_s,
                getattr(sig, "source_name", "") or "",
                getattr(sig, "direction", "") or "",
                getattr(sig, "symbol", "") or "",
                str(getattr(sig, "entry_price", "") or ""),
                getattr(sig, "status", "") or "",
            ]
            for c, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if c == 5:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(i, c, item)

        fill_orders_table(self.orders_table, snap.get("recent_orders") or [])

    def selected_order_ids(self) -> list[int]:
        ids: list[int] = []
        seen: set[int] = set()
        for index in self.orders_table.selectionModel().selectedRows():
            item = self.orders_table.item(index.row(), 0)
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
