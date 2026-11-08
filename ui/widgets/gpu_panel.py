"""Компактная панель метрик GPU (NVIDIA NVML)."""

from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.i18n import tr


class GpuPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 10, 16, 10)
        outer.setSpacing(18)

        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title = QLabel(tr("Видеокарта"))
        title.setObjectName("SectionTitle")
        self.name_label = QLabel(tr("GPU: N/A"))
        self.name_label.setObjectName("Muted")
        title_box.addWidget(title)
        title_box.addWidget(self.name_label)
        outer.addLayout(title_box, 2)

        self.values: dict[str, QLabel] = {}
        metrics = (
            ("temperature", tr("Температура")),
            ("load", tr("Загрузка GPU")),
            ("memory", tr("Контроллер памяти")),
            ("vram", tr("Видеопамять")),
        )
        for key, caption in metrics:
            box = QVBoxLayout()
            box.setSpacing(1)
            caption_label = QLabel(caption)
            caption_label.setObjectName("Muted")
            value_label = QLabel("—")
            value_label.setObjectName("SectionTitle")
            box.addWidget(caption_label)
            box.addWidget(value_label)
            outer.addLayout(box, 1)
            self.values[key] = value_label

        self.hide()

    def set_stats(self, stats: dict | None) -> None:
        if not stats or not stats.get("available"):
            self.hide()
            return
        self.show()

        name = str(stats.get("name") or "GPU")
        details: list[str] = []
        clock = stats.get("clock_mhz")
        if clock is not None:
            details.append(f"{int(clock)} {tr('МГц')}")
        fan = stats.get("fan_percent")
        if fan is not None:
            details.append(f"{tr('вентилятор')} {int(fan)}%")
        self.name_label.setText(
            name + (f" · {' · '.join(details)}" if details else "")
        )
        self.name_label.setToolTip(name)

        def value_text(value, suffix: str = "") -> str:
            return f"{int(value)}{suffix}" if value is not None else "—"

        self.values["temperature"].setText(
            value_text(stats.get("temperature_c"), " °C")
        )
        self.values["load"].setText(value_text(stats.get("gpu_percent"), "%"))
        self.values["memory"].setText(value_text(stats.get("memory_percent"), "%"))

        used = stats.get("vram_used_mb")
        total = stats.get("vram_total_mb")
        percent = stats.get("vram_percent")
        if used is not None and total:
            vram = f"{used} / {total} {tr('МБ')}"
            if percent is not None:
                vram += f" · {float(percent):.0f}%"
        elif used is not None:
            vram = f"{used} {tr('МБ')}"
        else:
            vram = "—"
        self.values["vram"].setText(vram)
