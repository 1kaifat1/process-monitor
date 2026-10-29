"""Лёгкий график истории значений (без QtCharts)."""

from __future__ import annotations

from collections import deque

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PyQt6.QtWidgets import QWidget


class HistoryChart(QWidget):
    """Сглаженная линия с заливкой и авто-масштабом."""

    def __init__(
        self,
        title: str = "",
        color: str = "#00f0ff",
        formatter=None,
        max_points: int = 120,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._color = QColor(color)
        self._formatter = formatter or (lambda value: f"{value:.0f}")
        self._values: deque[float] = deque(maxlen=max_points)
        self.setMinimumHeight(150)
        self.setMinimumWidth(180)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def push(self, value: float) -> None:
        try:
            self._values.append(float(value))
        except (TypeError, ValueError):
            return
        self.update()

    def set_values(self, values) -> None:
        self._values.clear()
        for value in values:
            try:
                self._values.append(float(value))
            except (TypeError, ValueError):
                continue
        self.update()

    def clear(self) -> None:
        self._values.clear()
        self.update()

    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(12, 10, -12, -8)

        # Заголовок и текущее значение
        title_font = QFont(self.font())
        pixel_size = self.font().pixelSize()
        if pixel_size <= 0:
            point_size = self.font().pointSizeF()
            pixel_size = int(round(point_size * 1.333)) if point_size > 0 else 13
        title_font.setPixelSize(max(10, pixel_size - 2))
        painter.setFont(title_font)
        painter.setPen(QColor("#8b9bb4"))
        painter.drawText(
            QRectF(rect.left(), rect.top(), rect.width() * 0.6, 16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._title,
        )

        if self._values:
            current = self._values[-1]
            painter.setPen(self._color)
            painter.drawText(
                QRectF(rect.left(), rect.top(), rect.width(), 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                self._formatter(current),
            )

        plot = QRectF(
            rect.left(),
            rect.top() + 22,
            max(10.0, rect.width()),
            max(10.0, rect.height() - 26),
        )

        # Сетка
        grid_pen = QPen(QColor(255, 255, 255, 18))
        grid_pen.setWidthF(1.0)
        painter.setPen(grid_pen)
        for step in range(1, 4):
            y = plot.top() + plot.height() * step / 4.0
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

        if len(self._values) < 2:
            painter.setPen(QColor("#8b9bb4"))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "Сбор данных…")
            painter.end()
            return

        values = list(self._values)
        maximum = max(values + [1e-9])
        if maximum <= 100:
            scale_max = 100.0 if max(values) > 12 else max(10.0, maximum * 1.3)
        else:
            scale_max = maximum * 1.15
        count = len(values)

        points: list[QPointF] = []
        for index, value in enumerate(values):
            x = plot.left() + plot.width() * index / max(1, count - 1)
            ratio = min(max(value / scale_max, 0.0), 1.0)
            y = plot.bottom() - plot.height() * ratio
            points.append(QPointF(x, y))

        area = QPainterPath()
        area.moveTo(points[0].x(), plot.bottom())
        for point in points:
            area.lineTo(point)
        area.lineTo(points[-1].x(), plot.bottom())
        area.closeSubpath()

        gradient = QLinearGradient(plot.topLeft(), plot.bottomLeft())
        start = QColor(self._color)
        start.setAlpha(80)
        end = QColor(self._color)
        end.setAlpha(0)
        gradient.setColorAt(0.0, start)
        gradient.setColorAt(1.0, end)
        painter.fillPath(area, gradient)

        line_pen = QPen(self._color)
        line_pen.setWidthF(2.0)
        line_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(line_pen)
        painter.drawPolyline(QPolygonF(points))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(points[-1], 3.2, 3.2)
        painter.end()
