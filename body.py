# body.py (客户端)
import os
import pyautogui
import io
import base64
import asyncio
import websockets
import json
import threading
import pygetwindow as gw
import pyperclip
try:
    import winsound
except ImportError:
    winsound = None

import config
"""
======================================================================
[模块] Crimson 物理躯壳端 (The Body)
======================================================================
在 C/S (Client/Server) 分离架构下，此脚本运行在用户的物理机（或轻薄本）上。
它不包含任何耗资源的 LLM 推理逻辑，仅负责统筹“物理感知与表达”：
1. 听觉 (Ear): 基于 Faster-Whisper 进行毫秒级环境音监听与 VAD 检测。
2. 视觉 (Eye): 接收大脑指令，进行屏幕截图并 Base64 压缩回传。
3. 嗅觉 (Nose): 后台低功耗轮询，窃取焦点窗口和剪贴板变化。
4. 表达 (Voice/Face): 播放 Edge-TTS 语音队列，并通过 VTube Studio 联动皮套。

它通过 WebSocket 与运行在带 GPU 工作站上的大脑 (server.py) 保持长连接。
======================================================================
"""
from colorama import init, Fore, Style
from senses.listener import Ear
from senses.voice import Voice
from tools.vts_adapter import VTSController

init(autoreset=True)

class CrimsonBody:
    def __init__(self):
        print(Fore.CYAN + "🦾 [Body] 正在初始化躯壳硬件..." + Style.RESET_ALL)
        self.ear = Ear(model_size="medium", device="cpu", compute_type="int8")
        self.voice = Voice()
        self.vts = VTSController()

        # ==========================================
        # [网络配置] 脑机连接路由 (Brain-Computer Interface)
        # 支持通过环境变量动态修改大脑(Server)的 IP 地址。
        # 默认回环地址 localhost。在双机分布式部署时，只需设置环境变量 CRIMSON_SERVER_HOST。
        # ==========================================
        server_host = os.environ.get("CRIMSON_SERVER_HOST", "localhost")
        self.server_uri = f"ws://{server_host}:8000/ws"
        self.websocket = None
        self.is_processing_vision = False

        # [核心] 音频播放队列
        self.audio_queue = asyncio.Queue()

    async def start(self):
        await self.vts.connect()

        try:
            async with websockets.connect(self.server_uri) as websocket:
                self.websocket = websocket
                print(Fore.GREEN + "✅ [Body] 已连接到大脑 (Server Connected)" + Style.RESET_ALL)

                # 并行运行四大死循环：网络接收、音频播放、环境录音、底层嗅觉
                await asyncio.gather(
                    self.receive_loop(),
                    self.audio_playback_loop(),
                    self.listen_loop(),
                    self.environment_sniff_loop()
                )
        except Exception as e:
            print(Fore.RED + f"❌ [Body] 脑机接口断开: {e}" + Style.RESET_ALL)

    async def audio_playback_loop(self):
        """ 独立的音频消费线程，防止 TTS 阻塞网络通信 """
        while True:
            # 阻塞等待队列中的待播报文本
            text = await self.audio_queue.get()

            # 说话前，捂住耳朵，防止录进自己的声音
            self.ear.pause()

            # 播放语音 (非阻塞，允许被打断)
            finished_naturally = await self.voice.speak(text)

            self.audio_queue.task_done()

            # 如果自然播放完毕，且队列里没词了，通知服务端“我说完了”
            if finished_naturally and self.audio_queue.empty():
                try:
                    await self.websocket.send(json.dumps({"type": "signal", "content": "speak_end"}))
                    # 重新张开耳朵监听用户
                    self.ear.resume()
                except:
                    pass

    async def receive_loop(self):
        try:
            async for message in self.websocket:
                data = json.loads(message)
                msg_type = data.get("type")

                # --- 视觉指令 ---
                if msg_type == "command" and data.get("content") == "snapshot":
                    print(Fore.CYAN + "📸 [Body] 收到截图指令 -> 锁定听觉 (专注模式)" + Style.RESET_ALL)
                    self.is_processing_vision = True
                    self.ear.pause()

                    if winsound: threading.Thread(target=winsound.Beep, args=(1000, 200)).start()

                    loop = asyncio.get_running_loop()
                    img_str = await loop.run_in_executor(None, self._capture_and_compress)

                    await self.websocket.send(json.dumps({
                        "type": "image", "content": img_str, "tag": "vision_response"
                    }))
                    print(Fore.CYAN + "📤 [Body] 视觉信号已回传 -> 等待大脑分析..." + Style.RESET_ALL)
                    # [核心] 此时绝不解锁听觉！让大脑安心跑模型。

                    # --- [新增] 视觉分析彻底完成，解除专注模式 ---
                elif msg_type == "command" and data.get("content") == "vision_end":
                    if self.is_processing_vision:
                        print(Fore.GREEN + "✅ [Body] 大脑视觉分析完成 -> 重新解锁听觉" + Style.RESET_ALL)
                        self.is_processing_vision = False
                        self.ear.resume()

                # --- 强行打断 (Barge-in) ---
                elif msg_type == "interrupt":
                    print(Fore.YELLOW + "🔇 [Body] 收到静音指令，紧急刹车" + Style.RESET_ALL)
                    # 1. 强行闭嘴
                    self.voice.stop()
                    # 2. 清空待播放的词库
                    while not self.audio_queue.empty():
                        try:
                            self.audio_queue.get_nowait()
                            self.audio_queue.task_done()
                        except asyncio.QueueEmpty:
                            break
                    # 3. 恢复听觉
                    self.ear.resume()

                # --- 全文下发 ---
                elif msg_type == "text_full":
                    text = data.get("content")
                    print(Fore.YELLOW + f"🧠 [Brain]: {text}" + Style.RESET_ALL)
                    # [核心] 不再 await speak，而是扔进队列！
                    await self.audio_queue.put(text)

                # --- 表情动作 ---
                elif msg_type == "action":
                    action = data.get("action")
                    val = data.get("data")
                    if action == "emotion_change":
                        status = val.get("status")
                        print(Fore.MAGENTA + f"🎭 [VTS] 切换表情: {status}" + Style.RESET_ALL)
                        await self.vts.trigger_hotkey(status)

        except websockets.exceptions.ConnectionClosed:
            print("❌ 连接关闭")

    def _capture_and_compress(self):
        screenshot = pyautogui.screenshot()
        img_buffer = io.BytesIO()
        screenshot.thumbnail((512, 512))
        screenshot.save(img_buffer, format="JPEG", quality=60)
        return base64.b64encode(img_buffer.getvalue()).decode('utf-8')

    async def listen_loop(self):
        """ 持续监听环境音的桥梁 """
        loop = asyncio.get_running_loop()

        def on_voice_start():
            # 当底层 Ear 检测到声音时触发
            if self.is_processing_vision: return

            # [关键] 瞬间通知服务端用户说话了，服务端会立即下发 interrupt
            asyncio.run_coroutine_threadsafe(
                self.websocket.send(json.dumps({"type": "signal", "content": "listen_start"})),
                loop
            )

        while True:
            if self.is_processing_vision:
                await asyncio.sleep(0.1)
                continue

            text = await loop.run_in_executor(None, self.ear.listen_continuous, on_voice_start)

            if text and len(text) > 1 and not self.is_processing_vision:
                print(Fore.BLUE + f"🎤 [Mic]: {text}" + Style.RESET_ALL)
                await self.websocket.send(json.dumps({
                    "type": "chat", "content": text, "tag": "voice"
                }))
            else:
                # 如果没转录出字（杂音），或者字太短，通知 Server 解除刹车
                # 只要底层退出录音但没有发送有效文本，就直接发 abort 通知 Server 释放刹车。
                await self.websocket.send(json.dumps({"type": "signal", "content": "listen_abort"}))

    async def environment_sniff_loop(self):
        """ 低功耗后台嗅觉：每 2 秒窃取一次你的屏幕焦点和剪贴板 """
        last_title = ""
        last_clip = ""

        while True:
            try:
                # 1. 嗅探当前激活的窗口
                active_window = gw.getActiveWindow()
                current_title = active_window.title if active_window else "桌面/未知"

                # 2. 嗅探剪贴板 (如果里面是文本的话)
                current_clip = pyperclip.paste()
                if len(current_clip) > 500:
                    current_clip = current_clip[:500] + "...(已截断)"

                # 只有当环境发生变化时，才悄悄发给大脑
                if current_title != last_title or current_clip != last_clip:
                    await self.websocket.send(json.dumps({
                        "type": "env_sniff",
                        "content": {
                            "window": current_title,
                            "clipboard": current_clip
                        }
                    }))
                    last_title = current_title
                    last_clip = current_clip

            except Exception as e:
                # 忽略那些烦人的系统权限报错
                pass

            await asyncio.sleep(2.0)  # 保持极低 CPU 功耗


if __name__ == "__main__":
    body = CrimsonBody()
    asyncio.run(body.start())