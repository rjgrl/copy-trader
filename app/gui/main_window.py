"""Main application window."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app.gui.controller import AppController
from app.gui.dashboard import DashboardPage
from app.gui.logs_page import LogsPage
from app.gui.orders_page import OrdersPage
from app.gui.settings_page import SettingsPage
from app.gui.signals_page import SignalsPage
from app.gui.styles import APP_STYLESHEET
from app.gui.telegram_page import TelegramPage


class MainWindow(QMainWindow):
    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Telegram MT5 Copier")
        self.resize(1180, 760)
        self.setStyleSheet(APP_STYLESHEET)

        shell = QWidget()
        self.setCentralWidget(shell)
        layout = QHBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Side nav
        nav = QFrame()
        nav.setObjectName("SideNav")
        nav.setFixedWidth(200)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(10, 10, 10, 10)
        brand = QLabel("Telegram → MT5")
        brand.setObjectName("Brand")
        nl.addWidget(brand)

        self.stack = QStackedWidget()
        self.page_dashboard = DashboardPage()
        self.page_telegram = TelegramPage()
        self.page_signals = SignalsPage()
        self.page_orders = OrdersPage()
        self.page_settings = SettingsPage()
        self.page_logs = LogsPage()
        pages = [
            ("Dashboard", self.page_dashboard),
            ("Telegram", self.page_telegram),
            ("Signals", self.page_signals),
            ("Orders", self.page_orders),
            ("Settings", self.page_settings),
            ("Logs", self.page_logs),
        ]
        self._nav_buttons: list[QPushButton] = []
        for i, (name, page) in enumerate(pages):
            self.stack.addWidget(page)
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setProperty("class", "NavButton")
            btn.setStyleSheet(
                "QPushButton{background:transparent;color:#c5cad3;text-align:left;"
                "padding:10px 16px;border:none;border-radius:6px;}"
                "QPushButton:hover{background:#2a3140;color:#fff;}"
                "QPushButton:checked{background:#3b82f6;color:#fff;font-weight:600;}"
            )
            btn.clicked.connect(lambda checked=False, idx=i: self._goto(idx))
            nl.addWidget(btn)
            self._nav_buttons.append(btn)
        nl.addStretch(1)
        layout.addWidget(nav)
        layout.addWidget(self.stack, 1)
        self._goto(0)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready")

        self._wire()
        self.page_settings.load_from_settings(controller.settings)
        controller.refresh_status()

    def _goto(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index)

    def _wire(self) -> None:
        c = self.controller
        d = self.page_dashboard
        t = self.page_telegram
        s = self.page_settings

        d.btn_connect_mt5.clicked.connect(c.connect_mt5)
        d.btn_connect_tg.clicked.connect(lambda: c.connect_telegram(interactive=True))
        d.btn_listen.clicked.connect(c.start_listening)
        d.btn_stop_listen.clicked.connect(c.stop_listening)
        d.btn_simulate.clicked.connect(c.simulate_sample)
        d.btn_kill.clicked.connect(self._toggle_kill)

        t.btn_connect.clicked.connect(lambda: c.connect_telegram(interactive=True))
        t.btn_load.clicked.connect(c.load_dialogs)
        t.btn_refresh.clicked.connect(lambda: self.page_telegram.set_sources(c.sources.list_all()))
        t.source_toggled.connect(self._on_source_toggled)

        self.page_signals.btn_refresh.clicked.connect(c.refresh_status)
        self.page_orders.btn_refresh.clicked.connect(c.refresh_status)

        s.btn_save.clicked.connect(self._save_settings)
        s.btn_inspect.clicked.connect(self._inspect)

        c.status_changed.connect(self._on_status)
        c.data_refreshed.connect(self._on_data)
        c.log_received.connect(self.page_logs.append_log)
        c.error_occurred.connect(self._on_error)
        c.dialogs_loaded.connect(self._on_dialogs)
        c.auth_finished.connect(self._on_auth)

    def _on_source_toggled(self, telegram_id: int, enabled: bool, name: str, dtype: str) -> None:
        if name:
            self.controller.upsert_source(telegram_id, name, dtype or "unknown", enabled)
        else:
            self.controller.set_source_enabled(telegram_id, enabled)

    def _toggle_kill(self) -> None:
        if self.page_dashboard.btn_kill.isChecked():
            self.controller.activate_kill_switch()
        else:
            self.controller.deactivate_kill_switch()

    def _save_settings(self) -> None:
        data = self.page_settings.collect()
        self.controller.save_settings_from_dict(data)
        self.status.showMessage("Settings saved", 3000)

    def _inspect(self) -> None:
        text = self.page_settings.txt_inspect_in.toPlainText()
        report = self.controller.inspect_text(text)
        self.page_settings.txt_inspect_out.setPlainText(report)

    def _on_status(self, snap: dict) -> None:
        self.page_dashboard.update_snapshot(snap)
        parts = [
            f"TG:{snap.get('telegram')}",
            f"MT5:{snap.get('mt5')}",
            f"Listen:{'yes' if snap.get('listening') else 'no'}",
            f"DryRun:{snap.get('dry_run')}",
        ]
        if snap.get("kill_switch"):
            parts.append("KILL SWITCH")
        self.status.showMessage(" | ".join(parts))

    def _on_data(self) -> None:
        snap = self.controller.snapshot()
        self.page_signals.set_signals(snap.get("recent_signals") or [])
        self.page_orders.set_orders(snap.get("recent_orders") or [])
        # Don't overwrite dialogs table if currently showing dialogs
        if not self.page_telegram._dialogs:
            self.page_telegram.set_sources(snap.get("sources") or [])

    def _on_dialogs(self, dialogs: list) -> None:
        self.page_telegram.set_dialogs(dialogs)
        self.status.showMessage(f"Loaded {len(dialogs)} Telegram dialogs", 4000)

    def _on_auth(self, ok: bool, msg: str) -> None:
        if ok:
            self.status.showMessage(f"Telegram {msg}", 4000)
        else:
            QMessageBox.warning(self, "Telegram", f"Auth: {msg}")

    def _on_error(self, message: str) -> None:
        self.page_logs.append_log(message, "ERROR")
        self.status.showMessage(f"Error: {message}", 8000)
        QMessageBox.warning(self, "Error", message)

    def closeEvent(self, event) -> None:  # noqa: N802
        # aboutToQuit also calls shutdown; guard with poll stop is fine
        self.controller.shutdown()
        super().closeEvent(event)
