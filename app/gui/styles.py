"""Application stylesheet — readable, low-chrome trading UI."""

APP_STYLESHEET = """
QWidget {
    font-family: "Segoe UI", "Helvetica Neue", sans-serif;
    font-size: 13px;
    color: #1a1d23;
}
QMainWindow, QDialog {
    background: #f0f2f5;
}
QFrame#SideNav {
    background: #1e2430;
    border: none;
}
QPushButton.NavButton {
    background: transparent;
    color: #c5cad3;
    text-align: left;
    padding: 10px 16px;
    border: none;
    border-radius: 6px;
}
QPushButton.NavButton:hover {
    background: #2a3140;
    color: #ffffff;
}
QPushButton.NavButton:checked {
    background: #3b82f6;
    color: #ffffff;
    font-weight: 600;
}
QLabel#Brand {
    color: #ffffff;
    font-size: 15px;
    font-weight: 700;
    padding: 16px;
}
QFrame#Card {
    background: #ffffff;
    border: 1px solid #dde1e6;
    border-radius: 8px;
}
QLabel.SectionTitle {
    font-size: 18px;
    font-weight: 700;
    color: #111827;
}
QLabel.Muted {
    color: #6b7280;
}
QLabel.StatusOk { color: #059669; font-weight: 600; }
QLabel.StatusWarn { color: #d97706; font-weight: 600; }
QLabel.StatusBad { color: #dc2626; font-weight: 600; }
QPushButton {
    background: #e8eaed;
    border: 1px solid #cfd3d8;
    border-radius: 6px;
    padding: 7px 14px;
}
QPushButton:hover { background: #dde1e6; }
QPushButton:disabled { color: #9ca3af; }
QPushButton#Primary {
    background: #2563eb;
    color: white;
    border: 1px solid #1d4ed8;
    font-weight: 600;
}
QPushButton#Primary:hover { background: #1d4ed8; }
QPushButton#Danger {
    background: #dc2626;
    color: white;
    border: 1px solid #b91c1c;
    font-weight: 700;
    padding: 10px 18px;
}
QPushButton#Danger:hover { background: #b91c1c; }
QPushButton#Danger:checked {
    background: #7f1d1d;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {
    background: #ffffff;
    border: 1px solid #cfd3d8;
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: #bfdbfe;
}
QTableWidget {
    background: #ffffff;
    border: 1px solid #dde1e6;
    border-radius: 8px;
    gridline-color: #eef0f3;
}
QHeaderView::section {
    background: #f7f8fa;
    border: none;
    border-bottom: 1px solid #dde1e6;
    padding: 6px 8px;
    font-weight: 600;
}
QCheckBox { spacing: 8px; }
QStatusBar {
    background: #ffffff;
    border-top: 1px solid #dde1e6;
}
QTabWidget::pane {
    border: 1px solid #dde1e6;
    border-radius: 8px;
    background: #ffffff;
}
"""
