"""Генерация assets/pulse.ico без сторонних библиотек.

Запуск: python tools/make_icon.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "assets" / "pulse.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)

WAVE = [
    (0.10, 0.56),
    (0.27, 0.56),
    (0.37, 0.28),
    (0.48, 0.80),
    (0.60, 0.42),
    (0.70, 0.56),
    (0.90, 0.56),
]


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # Фон: скруглённый квадрат с лёгким градиентом.
    background = QLinearGradient(0, 0, size, size)
    background.setColorAt(0.0, QColor("#0d1626"))
    background.setColorAt(1.0, QColor("#070a10"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(background)
    radius = size * 0.24
    painter.drawRoundedRect(QRectF(0.5, 0.5, size - 1, size - 1), radius, radius)

    # Тонкая рамка для контраста на светлом фоне.
    if size >= 32:
        border = QPen(QColor(255, 255, 255, 22))
        border.setWidthF(max(1.0, size * 0.012))
        painter.setPen(border)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inset = border.widthF() / 2
        painter.drawRoundedRect(
            QRectF(inset, inset, size - 2 * inset, size - 2 * inset),
            radius,
            radius,
        )

    # Линия пульса с мягким свечением.
    path = QPainterPath()
    path.moveTo(QPointF(WAVE[0][0] * size, WAVE[0][1] * size))
    for x, y in WAVE[1:]:
        path.lineTo(QPointF(x * size, y * size))

    glow = QPen(QColor(0, 240, 255, 55))
    glow.setWidthF(max(3.0, size * 0.20))
    glow.setCapStyle(Qt.PenCapStyle.RoundCap)
    glow.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(glow)
    painter.drawPath(path)

    accent = QLinearGradient(0, 0, size, size)
    accent.setColorAt(0.0, QColor("#00f0ff"))
    accent.setColorAt(1.0, QColor("#2ee6a8"))
    stroke = QPen()
    stroke.setBrush(QBrush(accent))
    stroke.setWidthF(max(1.4, size * 0.085))
    stroke.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroke.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(stroke)
    painter.drawPath(path)
    painter.end()
    return image


def build_ico(path: Path) -> None:
    """ICO-контейнер с PNG-кадрами (поддерживается Windows Vista+)."""
    frames: list[tuple[int, bytes]] = []
    for size in SIZES:
        image = render(size)
        payload = QByteArray()
        buffer = QBuffer(payload)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        frames.append((size, bytes(payload)))

    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries = b""
    blobs = b""
    for size, data in frames:
        dimension = 0 if size >= 256 else size
        entries += struct.pack(
            "<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset
        )
        offset += len(data)
        blobs += data

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + blobs)


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841 - нужен для QPainter
    build_ico(TARGET)
    print(f"Готово: {TARGET} ({TARGET.stat().st_size} байт)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
