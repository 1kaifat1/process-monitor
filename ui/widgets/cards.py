"""Карточки метрик и заголовки секций."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget, QHBoxLayout


class StatCard(QFrame):
    """Компактная карточка с заголовком, значением и подсказкой."""

    def __init__(
        self,
        title: str,
        value: str = "—",
        hint: str = "",
        accent: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumHeight(92)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")

        self.value_label = QLabel(value)
        self.value_label.setObjectName("CardValue")

        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("CardHint")

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label, 1)
        layout.addWidget(self.hint_label)

        if accent:
            self.set_accent(accent)

    def set_accent(self, color: str) -> None:
        self.value_label.setStyleSheet(f"color: {color};")

    def set_value(self, value: str, hint: str | None = None) -> None:
        self.value_label.setText(value)
        if hint is not None:
            self.hint_label.setText(hint)

    def set_hint(self, hint: str) -> None:
        self.hint_label.setText(hint)


class PageHeader(QWidget):
    """Заголовок страницы с действиями справа."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("PageTitle")
        texts.addWidget(self.title_label)
        if subtitle:
            self.subtitle_label = QLabel(subtitle)
            self.subtitle_label.setObjectName("PageSubtitle")
            texts.addWidget(self.subtitle_label)
        else:
            self.subtitle_label = None
        layout.addLayout(texts)
        layout.addStretch(1)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        layout.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)

    def set_subtitle(self, text: str) -> None:
        if self.subtitle_label is not None:
            self.subtitle_label.setText(text)


class Badge(QLabel):
    """Небольшой цветной бейдж."""

    def __init__(self, text: str, warning: bool = False, parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName("BadgeWarning" if warning else "Badge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMaximumHeight(22)
