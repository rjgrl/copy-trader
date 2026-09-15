"""Settings and Signal Inspector page."""

from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class SettingsPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        title = QLabel("Settings")
        title.setStyleSheet("font-size:18px;font-weight:700;")
        root.addWidget(title)

        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        # Trading tab
        trading = QWidget()
        form = QFormLayout(trading)
        self.chk_dry = QCheckBox("Dry Run (no real MT5 orders)")
        self.chk_copy = QCheckBox("Copy Trading Enabled")
        self.spin_magic = QSpinBox()
        self.spin_magic.setRange(1, 2_000_000_000)
        self.spin_dev = QDoubleSpinBox()
        self.spin_dev.setRange(0.0, 1000.0)
        self.spin_dev.setDecimals(2)
        self.spin_lot = QDoubleSpinBox()
        self.spin_lot.setRange(0.01, 100.0)
        self.spin_lot.setDecimals(2)
        self.spin_spread = QDoubleSpinBox()
        self.spin_spread.setRange(0.0, 1000.0)
        self.spin_spread.setDecimals(2)
        self.chk_tp_prot = QCheckBox("TP Proximity Protection")
        form.addRow(self.chk_dry)
        form.addRow(self.chk_copy)
        form.addRow("Magic number", self.spin_magic)
        form.addRow("Max entry deviation", self.spin_dev)
        form.addRow("Fixed lot", self.spin_lot)
        form.addRow("Max spread (price)", self.spin_spread)
        form.addRow(self.chk_tp_prot)
        tabs.addTab(trading, "Execution / Risk")

        # Symbols tab
        symbols = QWidget()
        sform = QFormLayout(symbols)
        self.txt_mappings = QTextEdit()
        self.txt_mappings.setPlaceholderText('{"XAUUSD": "GOLD#", "GOLD": "GOLD#"}')
        self.txt_mt5_path = QLineEdit()
        self.txt_mt5_path.setPlaceholderText("Optional MT5 terminal64.exe path")
        sform.addRow("Symbol mappings (JSON)", self.txt_mappings)
        sform.addRow("MT5 terminal path", self.txt_mt5_path)
        tabs.addTab(symbols, "Symbols / MT5")

        # Telegram secrets hint
        tg = QWidget()
        tform = QFormLayout(tg)
        hint = QLabel(
            "Telegram API ID / Hash are loaded from the .env file "
            "(never stored in config.json). Use CLI: python run.py auth"
        )
        hint.setWordWrap(True)
        tform.addRow(hint)
        tabs.addTab(tg, "Telegram")

        # Inspector
        insp = QWidget()
        il = QVBoxLayout(insp)
        il.addWidget(QLabel("Paste a Telegram message to inspect (no trades):"))
        self.txt_inspect_in = QTextEdit()
        self.txt_inspect_out = QTextEdit()
        self.txt_inspect_out.setReadOnly(True)
        self.btn_inspect = QPushButton("Inspect")
        self.btn_inspect.setObjectName("Primary")
        il.addWidget(self.txt_inspect_in, 1)
        il.addWidget(self.btn_inspect)
        il.addWidget(self.txt_inspect_out, 1)
        tabs.addTab(insp, "Signal Inspector")

        bar = QHBoxLayout()
        self.btn_save = QPushButton("Save Settings")
        self.btn_save.setObjectName("Primary")
        bar.addStretch(1)
        bar.addWidget(self.btn_save)
        root.addLayout(bar)

    def load_from_settings(self, settings) -> None:
        self.chk_dry.setChecked(bool(settings.dry_run))
        self.chk_copy.setChecked(bool(settings.copy_trading_enabled))
        self.spin_magic.setValue(int(settings.magic_number))
        self.spin_dev.setValue(float(settings.entry.max_entry_deviation))
        self.spin_lot.setValue(float(settings.risk.fixed_lot))
        self.spin_spread.setValue(float(settings.risk.max_spread))
        self.chk_tp_prot.setChecked(bool(settings.entry.tp_proximity_protection))
        self.txt_mappings.setPlainText(json.dumps(settings.symbol_mappings, indent=2))
        self.txt_mt5_path.setText(settings.mt5_terminal_path or "")

    def collect(self) -> dict:
        try:
            mappings = json.loads(self.txt_mappings.toPlainText() or "{}")
        except json.JSONDecodeError:
            mappings = {"XAUUSD": "GOLD#", "GOLD": "GOLD#"}
        path = self.txt_mt5_path.text().strip() or None
        return {
            "dry_run": self.chk_dry.isChecked(),
            "copy_trading_enabled": self.chk_copy.isChecked(),
            "magic_number": self.spin_magic.value(),
            "mt5_terminal_path": path,
            "symbol_mappings": mappings,
            "entry": {
                "max_entry_deviation": self.spin_dev.value(),
                "tp_proximity_protection": self.chk_tp_prot.isChecked(),
            },
            "risk": {
                "fixed_lot": self.spin_lot.value(),
                "max_spread": self.spin_spread.value(),
            },
        }
