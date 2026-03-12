# interfaces/websocket_ui.py
import asyncio
from core.interface import BaseInterface

class WebSocketUI(BaseInterface):
    def __init__(self):
        self.msg_queue = asyncio.Queue()
        self.loop = None

    def _push(self, message: dict):
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.msg_queue.put(message), self.loop)

    def output_text(self, text: str):
        self._push({"type": "text_stream", "content": text})

    def output_final(self, text: str):
        self._push({"type": "text_full", "content": text})

    def output_action(self, action_type: str, data: dict = None):
        self._push({"type": "action", "action": action_type, "data": data})

    def system_log(self, text: str, level: str = "info"):
        self._push({"type": "system", "content": text, "level": level})

    def interrupt(self):
        # 此方法不再使用，中断逻辑已收口到 server.py 强制发送 WS 包
        pass