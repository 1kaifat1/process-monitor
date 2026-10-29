"""Темы оформления: тёмная и светлая, с настраиваемым акцентом."""

from __future__ import annotations

from PyQt6.QtGui import QColor, QFont, QPalette

PALETTES = {
    "dark": {
        "bg": "#070a10",
        "panel": "#0d121b",
        "panel2": "#111826",
        "sidebar": "#0a0f16",
        "text": "#e8eef7",
        "muted": "#8b9bb4",
        "border": "#1e2938",
        "border_strong": "#2b3a4f",
        "input": "#121a26",
        "hover": "#182233",
        "danger": "#ff5470",
        "warning": "#ffb020",
        "success": "#2ee6a8",
    },
    "light": {
        "bg": "#eef2f8",
        "panel": "#ffffff",
        "panel2": "#f7f9fd",
        "sidebar": "#f7f9fd",
        "text": "#0e1726",
        "muted": "#5c6b80",
        "border": "#dde4ee",
        "border_strong": "#c3cedd",
        "input": "#ffffff",
        "hover": "#e9f0fa",
        "danger": "#d92d4b",
        "warning": "#b97700",
        "success": "#0f9d6d",
    },
}


def rgba(hex_color: str, alpha: float) -> str:
    color = QColor(hex_color)
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha:.2f})"


def palette(theme: str) -> dict:
    return PALETTES.get(theme, PALETTES["dark"])


def build_stylesheet(theme: str, accent: str, font_size: int) -> str:
    c = palette(theme)
    accent_text = "#05070b" if QColor(accent).lightness() > 140 else "#ffffff"
    base = font_size
    return f"""
    * {{
        font-family: "Segoe UI", "Inter", Arial, sans-serif;
        outline: none;
    }}
    QWidget {{
        color: {c['text']};
    }}
    QMainWindow, QDialog {{
        background-color: {c['bg']};
    }}
    QToolTip {{
        background: {c['panel2']};
        color: {c['text']};
        border: 1px solid {c['border_strong']};
        border-radius: 6px;
        padding: 5px 8px;
    }}
    QFrame#Sidebar {{
        background: {c['sidebar']};
        border-right: 1px solid {c['border']};
    }}
    QFrame#Header {{
        background: {c['panel']};
        border-bottom: 1px solid {c['border']};
    }}
    QFrame#Card {{
        background: {c['panel2']};
        border: 1px solid {c['border']};
        border-radius: 12px;
    }}
    QFrame#Card:hover {{
        border-color: {rgba(accent, 0.45)};
    }}
    QLabel#Logo {{
        font-size: {base + 8}px;
        font-weight: 700;
        letter-spacing: 2px;
        color: {accent};
    }}
    QLabel#LogoSub {{
        font-size: {base - 2}px;
        color: {c['muted']};
    }}
    QLabel#PageTitle {{
        font-size: {base + 9}px;
        font-weight: 600;
    }}
    QLabel#PageSubtitle {{
        color: {c['muted']};
        font-size: {base - 1}px;
    }}
    QLabel#SectionTitle {{
        font-size: {base + 3}px;
        font-weight: 600;
    }}
    QLabel#CardTitle {{
        color: {c['muted']};
        font-size: {base - 2}px;
        text-transform: uppercase;
        letter-spacing: 1px;
    }}
    QLabel#CardValue {{
        font-size: {base + 12}px;
        font-weight: 700;
    }}
    QLabel#CardHint {{
        color: {c['muted']};
        font-size: {base - 2}px;
    }}
    QLabel#Muted {{
        color: {c['muted']};
    }}
    QLabel#Badge {{
        color: {accent};
        background: {rgba(accent, 0.12)};
        border: 1px solid {rgba(accent, 0.35)};
        border-radius: 9px;
        padding: 2px 8px;
        font-size: {base - 3}px;
        font-weight: 600;
    }}
    QLabel#BadgeWarning {{
        color: {c['warning']};
        background: {rgba(c['warning'], 0.12)};
        border: 1px solid {rgba(c['warning'], 0.4)};
        border-radius: 9px;
        padding: 2px 8px;
        font-size: {base - 3}px;
        font-weight: 600;
    }}
    QPushButton {{
        background: {c['panel2']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 7px 14px;
    }}
    QPushButton:hover {{
        border-color: {rgba(accent, 0.65)};
        background: {c['hover']};
    }}
    QPushButton:pressed {{
        background: {rgba(accent, 0.2)};
    }}
    QPushButton:disabled {{
        color: {c['muted']};
        border-color: {c['border']};
    }}
    QPushButton#PrimaryButton {{
        background: {accent};
        color: {accent_text};
        border: none;
        font-weight: 600;
    }}
    QPushButton#PrimaryButton:hover {{
        background: {QColor(accent).lighter(112).name()};
    }}
    QPushButton#DangerButton {{
        color: {c['danger']};
        border-color: {rgba(c['danger'], 0.5)};
        background: transparent;
    }}
    QPushButton#DangerButton:hover {{
        background: {rgba(c['danger'], 0.14)};
        border-color: {c['danger']};
    }}
    QPushButton#NavButton {{
        text-align: left;
        padding: 10px 14px;
        border: 1px solid transparent;
        border-radius: 9px;
        background: transparent;
        color: {c['muted']};
        font-size: {base}px;
        font-weight: 500;
    }}
    QPushButton#NavButton:hover {{
        background: {c['hover']};
        color: {c['text']};
    }}
    QPushButton#NavButton:checked {{
        background: {rgba(accent, 0.13)};
        border: 1px solid {rgba(accent, 0.4)};
        color: {accent};
        font-weight: 600;
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {c['input']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 6px 10px;
        selection-background-color: {rgba(accent, 0.35)};
        selection-color: {c['text']};
        min-height: 18px;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border-color: {accent};
        background: {c['panel2']};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        background: {c['panel2']};
        border: 1px solid {c['border_strong']};
        border-radius: 8px;
        selection-background-color: {rgba(accent, 0.25)};
        padding: 4px;
    }}
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        width: 16px;
        border: none;
        background: transparent;
    }}
    QCheckBox, QRadioButton {{
        spacing: 8px;
        color: {c['text']};
    }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 15px;
        height: 15px;
        border: 1px solid {c['border_strong']};
        background: {c['input']};
    }}
    QCheckBox::indicator {{ border-radius: 4px; }}
    QRadioButton::indicator {{ border-radius: 8px; }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background: {accent};
        border-color: {accent};
    }}
    QTableView {{
        background: {c['panel2']};
        alternate-background-color: {rgba(c['text'], 0.025)};
        border: 1px solid {c['border']};
        border-radius: 10px;
        gridline-color: transparent;
        selection-background-color: {rgba(accent, 0.22)};
        selection-color: {c['text']};
    }}
    QTableView::item {{
        padding: 4px 6px;
        border: none;
    }}
    QTableView::item:hover {{
        background: {rgba(accent, 0.08)};
    }}
    QHeaderView::section {{
        background: {c['panel']};
        color: {c['muted']};
        border: none;
        border-bottom: 1px solid {c['border']};
        border-right: 1px solid {rgba(c['border'], 0.6)};
        padding: 7px 6px;
        font-weight: 600;
        font-size: {base - 2}px;
    }}
    QTableCornerButton::section {{
        background: {c['panel']};
        border: none;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {c['border_strong']};
        border-radius: 5px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {accent}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {c['border_strong']};
        border-radius: 5px;
        min-width: 30px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {accent}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QMenu {{
        background: {c['panel2']};
        border: 1px solid {c['border_strong']};
        border-radius: 8px;
        padding: 5px;
    }}
    QMenu::item {{
        padding: 6px 22px 6px 12px;
        border-radius: 6px;
    }}
    QMenu::item:selected {{
        background: {rgba(accent, 0.22)};
    }}
    QMenu::separator {{
        height: 1px;
        background: {c['border']};
        margin: 5px 8px;
    }}
    QStatusBar {{
        background: {c['panel']};
        border-top: 1px solid {c['border']};
        color: {c['muted']};
        font-size: {base - 2}px;
    }}
    QGroupBox {{
        border: 1px solid {c['border']};
        border-radius: 10px;
        margin-top: 14px;
        padding: 12px 10px 10px 10px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 4px;
        color: {c['muted']};
    }}
    QTabWidget::pane {{
        border: 1px solid {c['border']};
        border-radius: 10px;
        top: -1px;
        background: {c['panel2']};
    }}
    QTabBar::tab {{
        background: transparent;
        color: {c['muted']};
        padding: 8px 16px;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{
        color: {accent};
        border-bottom: 2px solid {accent};
    }}
    QSplitter::handle {{
        background: transparent;
        height: 10px;
    }}
    QProgressBar {{
        background: {c['input']};
        border: none;
        border-radius: 5px;
        height: 8px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{
        background: {accent};
        border-radius: 5px;
    }}
    """


def apply_theme(app, theme: str, accent: str, font_size: int) -> None:
    app.setStyleSheet(build_stylesheet(theme, accent, font_size))
    app.setFont(QFont("Segoe UI", font_size))

    c = palette(theme)
    qpalette = QPalette()
    qpalette.setColor(QPalette.ColorRole.Window, QColor(c["bg"]))
    qpalette.setColor(QPalette.ColorRole.WindowText, QColor(c["text"]))
    qpalette.setColor(QPalette.ColorRole.Base, QColor(c["panel2"]))
    qpalette.setColor(QPalette.ColorRole.AlternateBase, QColor(c["panel"]))
    qpalette.setColor(QPalette.ColorRole.Text, QColor(c["text"]))
    qpalette.setColor(QPalette.ColorRole.Button, QColor(c["panel2"]))
    qpalette.setColor(QPalette.ColorRole.ButtonText, QColor(c["text"]))
    qpalette.setColor(QPalette.ColorRole.Highlight, QColor(accent))
    qpalette.setColor(QPalette.ColorRole.HighlightedText, QColor("#05070b"))
    qpalette.setColor(QPalette.ColorRole.ToolTipBase, QColor(c["panel2"]))
    qpalette.setColor(QPalette.ColorRole.ToolTipText, QColor(c["text"]))
    app.setPalette(qpalette)


def create_app_icon(size: int = 64):
    """Сгенерировать иконку приложения без внешних файлов."""
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import QIcon, QLinearGradient, QPainter, QPen, QPixmap

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0, QColor("#00f0ff"))
    gradient.setColorAt(1, QColor("#0066ff"))
    painter.setBrush(gradient)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(QRectF(2, 2, size - 4, size - 4), size * 0.22, size * 0.22)

    painter.setPen(QPen(QColor("#05070b"), max(2.0, size * 0.07)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    points = [(0.22, 0.58), (0.36, 0.58), (0.44, 0.32), (0.56, 0.72), (0.66, 0.46), (0.78, 0.46)]
    for index in range(len(points) - 1):
        x1, y1 = points[index]
        x2, y2 = points[index + 1]
        painter.drawLine(int(x1 * size), int(y1 * size), int(x2 * size), int(y2 * size))
    painter.end()
    return QIcon(pixmap)


def app_icon_path():
    """Путь к ``assets/pulse.ico`` (в onefile-сборке — к распакованному файлу)."""
    from pathlib import Path

    candidate = Path(__file__).resolve().parents[1] / "assets" / "pulse.ico"
    return candidate if candidate.is_file() else None


def load_app_icon(size: int = 64):
    """Иконка приложения для окна, трея и панели задач.

    Предпочитает готовый ``assets/pulse.ico``: в нём есть кадры 16–256 px,
    поэтому панель задач, Alt+Tab и заголовок окна получают чёткую иконку
    нужного размера. Если файла нет, иконка рисуется программно.
    """
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QIcon

    path = app_icon_path()
    if path is not None:
        icon = QIcon()
        for px in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256):
            icon.addFile(str(path), QSize(px, px))
        if not icon.isNull():
            return icon
    return create_app_icon(size)

