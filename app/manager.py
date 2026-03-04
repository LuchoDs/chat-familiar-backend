from fastapi import WebSocket
from typing import Dict, List


class ConnectionManager:
    def __init__(self):
        # { family_id: [websocket1, websocket2] }
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, family_id: int):
        await websocket.accept()

        if family_id not in self.active_connections:
            self.active_connections[family_id] = []

        self.active_connections[family_id].append(websocket)

    def disconnect(self, websocket: WebSocket, family_id: int):
        if family_id in self.active_connections:
            if websocket in self.active_connections[family_id]:
                self.active_connections[family_id].remove(websocket)

            # Si ya no queda nadie conectado en esa familia, limpiamos
            if not self.active_connections[family_id]:
                del self.active_connections[family_id]

    async def broadcast(self, family_id: int, message: dict):
        if family_id in self.active_connections:
            for connection in self.active_connections[family_id]:
                await connection.send_json(message)


# Instancia global
manager = ConnectionManager()