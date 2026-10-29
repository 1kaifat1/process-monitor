"""Один экземпляр приложения на пользователя.

Если Pulse Monitor уже запущен (в том числе свёрнут в трей), второй запуск
не создаёт новое окно, а просит работающий экземпляр показать себя.

Это важно и для панели задач: два процесса с одинаковым AppUserModelID
(например, исходники + собранный EXE) сливаются в одну кнопку, и Windows
может показать иконку не того исполняемого файла — для ``pythonw.exe`` это
стандартная «пустая» иконка.
"""

from __future__ import annotations

import os

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

# Имя сокета привязано к пользователю: два пользователя в одной системе
# не должны мешать друг другу.
_USER = os.environ.get("USERNAME") or "user"
SERVER_NAME = f"PulseMonitor.SingleInstance.{_USER}"
_MESSAGE = b"show"


class SingleInstance(QObject):
    """Сервер локального сокета + оповещение уже запущенного экземпляра."""

    show_requested = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server: QLocalServer | None = None

    # ------------------------------------------------------------------
    def notify_existing(self, timeout_ms: int = 500) -> bool:
        """Есть ли запущенный экземпляр? Если да — попросить его показаться."""
        socket = QLocalSocket()
        socket.connectToServer(SERVER_NAME)
        if not socket.waitForConnected(timeout_ms):
            return False
        socket.write(_MESSAGE)
        socket.waitForBytesWritten(timeout_ms)
        socket.disconnectFromServer()
        socket.close()
        return True

    def listen(self, takeover: bool = False) -> bool:
        """Стать «главным» экземпляром и слушать запросы на показ окна."""
        if takeover:
            # Повышенный перезапуск: старый процесс уже завершается.
            QLocalServer.removeServer(SERVER_NAME)
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        server.newConnection.connect(self._on_new_connection)
        if not server.listen(SERVER_NAME):
            # Остался сокет от аварийно закрытого процесса — убираем его.
            QLocalServer.removeServer(SERVER_NAME)
            if not server.listen(SERVER_NAME):
                return False
        self._server = server
        return True

    def close(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None

    # ------------------------------------------------------------------
    def _on_new_connection(self) -> None:
        """Любое подключение = запрос показать окно (клиент шлёт «show»)."""
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                return
            socket.disconnected.connect(socket.deleteLater)
            self.show_requested.emit()
