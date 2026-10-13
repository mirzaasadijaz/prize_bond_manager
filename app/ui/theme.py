"""Colours and the application stylesheet (one light theme with a dark sidebar)."""
from __future__ import annotations

PRIMARY = "#0F766E"
PRIMARY_HOVER = "#115E59"
PRIMARY_SOFT = "#CCFBF1"
ACCENT = "#2DD4BF"
SIDEBAR_BG = "#0F172A"
SIDEBAR_HOVER = "#1E293B"
SIDEBAR_TEXT = "#CBD5E1"
BG = "#F3F5F8"
SURFACE = "#FFFFFF"
BORDER = "#E2E8F0"
BORDER_STRONG = "#CBD5E1"
TEXT = "#0F172A"
MUTED = "#64748B"
DANGER = "#B91C1C"
WARNING_BG = "#FEF3C7"
WARNING_TEXT = "#92400E"
SUCCESS_BG = "#DCFCE7"
SUCCESS_TEXT = "#166534"
WON_TEXT = "#64748B"

STYLESHEET = f"""
* {{
    font-family: "Segoe UI", "Inter", "SF Pro Text", "Helvetica Neue", "DejaVu Sans", Arial, sans-serif;
    font-size: 10pt;
}}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget#Page {{ background: {BG}; }}
QLabel {{ color: {TEXT}; background: transparent; }}
QLabel[role="title"] {{ font-size: 19pt; font-weight: 700; }}
QLabel[role="subtitle"], QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="section"] {{ font-size: 11.5pt; font-weight: 600; }}
QLabel[role="statvalue"] {{ font-size: 22pt; font-weight: 700; }}
QLabel[role="problem"] {{ color: {DANGER}; }}
QLabel[role="ok"] {{ color: {SUCCESS_TEXT}; }}

QFrame#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#Banner {{ background: {WARNING_BG}; border: 1px solid #FCD34D; border-radius: 10px; }}
QFrame#Banner QLabel {{ color: {WARNING_TEXT}; font-weight: 600; }}
QFrame#Note {{ background: #F0FDFA; border: 1px solid #99F6E4; border-radius: 8px; }}
QFrame#Note QLabel {{ color: #115E59; }}

QPushButton {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER_STRONG};
    border-radius: 6px; padding: 6px 14px;
}}
QPushButton:hover {{ background: #F1F5F9; }}
QPushButton:pressed {{ background: #E2E8F0; }}
QPushButton:disabled {{ color: #94A3B8; background: #F8FAFC; border-color: {BORDER}; }}
QPushButton[kind="primary"] {{
    background: {PRIMARY}; border-color: {PRIMARY}; color: white; font-weight: 600;
}}
QPushButton[kind="primary"]:hover {{ background: {PRIMARY_HOVER}; }}
QPushButton[kind="primary"]:disabled {{ background: #99C9C4; border-color: #99C9C4; color: #F0FDFA; }}
QPushButton[kind="danger"] {{ color: {DANGER}; border-color: #FCA5A5; }}
QPushButton[kind="danger"]:hover {{ background: #FEF2F2; }}
QPushButton[kind="danger"]:disabled {{ color: #FCA5A5; }}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QDateEdit, QSpinBox {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER_STRONG};
    border-radius: 6px; padding: 5px 8px;
    selection-background-color: #99F6E4; selection-color: {TEXT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus,
QDateEdit:focus, QSpinBox:focus {{ border: 1px solid {PRIMARY}; }}
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QSpinBox:disabled,
QPlainTextEdit:disabled {{ background: #F1F5F9; color: #94A3B8; }}
QLineEdit[invalid="true"] {{ border: 1px solid #EF4444; }}
QComboBox QAbstractItemView {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER_STRONG};
    selection-background-color: {PRIMARY_SOFT}; selection-color: {TEXT};
}}
QCheckBox, QRadioButton {{ color: {TEXT}; spacing: 8px; }}

QTableView, QTableWidget {{
    background: {SURFACE}; alternate-background-color: #F8FAFC; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 8px; gridline-color: #EEF2F7;
    selection-background-color: {PRIMARY_SOFT}; selection-color: {TEXT};
}}
QTableView::item {{ padding: 4px 6px; }}
QHeaderView::section {{
    background: #F1F5F9; color: #334155; padding: 7px 8px; border: none;
    border-bottom: 1px solid {BORDER}; border-right: 1px solid {BORDER}; font-weight: 600;
}}
QTableCornerButton::section {{ background: #F1F5F9; border: none; }}

QTabWidget::pane {{
    border: 1px solid {BORDER}; border-radius: 8px; background: {SURFACE}; top: -1px;
}}
QTabBar::tab {{
    background: transparent; padding: 8px 16px; color: {MUTED};
    border-bottom: 2px solid transparent; margin-right: 2px;
}}
QTabBar::tab:selected {{ color: {PRIMARY}; border-bottom: 2px solid {PRIMARY}; font-weight: 600; }}
QTabBar::tab:hover:!selected {{ color: {TEXT}; }}

QGroupBox {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px;
    margin-top: 14px; padding: 16px 12px 10px 12px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #334155; font-weight: 600;
}}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #CBD5E1; border-radius: 5px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: #94A3B8; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #CBD5E1; border-radius: 5px; min-width: 28px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}

QMenuBar {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
QMenuBar::item {{ padding: 6px 12px; background: transparent; }}
QMenuBar::item:selected {{ background: #F1F5F9; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER_STRONG}; padding: 4px; }}
QMenu::item {{ padding: 6px 24px; border-radius: 4px; }}
QMenu::item:selected {{ background: {PRIMARY_SOFT}; color: {TEXT}; }}
QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; color: {MUTED}; }}
QToolTip {{ background: {TEXT}; color: white; border: none; padding: 5px 8px; }}
QTextBrowser {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; }}
QSplitter::handle {{ background: transparent; }}

QFrame#Sidebar {{ background: {SIDEBAR_BG}; }}
QFrame#Sidebar QLabel {{ color: {SIDEBAR_TEXT}; }}
QFrame#Sidebar QLabel[role="brand"] {{ color: white; font-size: 13pt; font-weight: 700; }}
QFrame#Sidebar QLabel[role="muted"] {{ color: #64748B; font-size: 8.5pt; }}
QPushButton#NavButton {{
    background: transparent; color: {SIDEBAR_TEXT}; border: none; border-radius: 8px;
    padding: 10px 14px; text-align: left; font-size: 10.5pt;
}}
QPushButton#NavButton:hover {{ background: {SIDEBAR_HOVER}; color: white; }}
QPushButton#NavButton:checked {{
    background: {SIDEBAR_HOVER}; color: white; font-weight: 600;
    border-left: 3px solid {ACCENT}; border-top-left-radius: 0; border-bottom-left-radius: 0;
}}
"""
