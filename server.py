# server.py
import os
import re
import asyncio
import uvicorn
import base64
import io
import time
import threading
from PIL import Image
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from colorama import init, Fore, Style

import config
"""
======================================================================
[模块] Crimson 云端中枢脑 (The Brain / Server)
======================================================================
基于 FastAPI + WebSocket 构建的神经中枢服务端。
该模块必须运行在拥有强劲 GPU 的机器上，负责统筹大模型推理、状态机调度和长期记忆。
它被动等待躯壳 (body.py) 连接，一旦连接建立：
- 接收并解析来自躯壳的视觉、听觉、嗅探信号。
- 在防弹状态机 (TaskScheduler) 的保护下，执行安全的并发大模型推理。
- 动态下发文字TTS流、打断指令 (Barge-in) 以及情绪表情指令。
======================================================================
"""
from core.agent import CrimsonAgent
from interfaces.websocket_ui import WebSocketUI
from core.scheduler import GlobalState

init(autoreset=True)


# --- 升级版：带刹车感知的视觉缓冲区 ---
class VisualBuffer:
    def __init__(self):
        self.latest_image = None
        self.event = threading.Event()

    def clear(self):
        self.latest_image = None
        self.event.clear()

    def set_image(self, pil_image):
        self.latest_image = pil_image
        self.event.set()

    def wait_for_image(self, stop_event: threading.Event, timeout=15):
        """ 阻塞等待，如果触发打断刹车，则立即退出等待 """
        start_time = time.time()
        while time.time() - start_time < timeout:
            if stop_event and stop_event.is_set():
                print(Fore.RED + "🛑 [VisualBuffer] 检测到中断信号，放弃等待图片。" + Style.RESET_ALL)
                return "TIMEOUT"  # 被打断当做超时处理
            if self.event.wait(0.2):  # 每 0.5 秒醒来检查一次状态
                return self.latest_image
        return "TIMEOUT"


visual_buffer = VisualBuffer()
SERVER_LOOP = None
agent = None
ws_ui = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent, ws_ui, SERVER_LOOP
    print(Fore.RED + "🧱 [Server] 正在初始化 Crimson 内核..." + Style.RESET_ALL)
    SERVER_LOOP = asyncio.get_running_loop()
    ws_ui = WebSocketUI()
    ws_ui.loop = SERVER_LOOP
    agent = CrimsonAgent(ui=ws_ui)

    print(Fore.GREEN + "✅ [Server] 内核就绪。等待客户端连接..." + Style.RESET_ALL)
    yield
    print(Fore.YELLOW + "👋 [Server] 内核正在休眠..." + Style.RESET_ALL)


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print(Fore.GREEN + f"🔌 [Server] 躯壳已连接" + Style.RESET_ALL)

    def request_remote_snapshot():
        print(Fore.YELLOW + "📡 [Server] 向 Body 请求视觉信号..." + Style.RESET_ALL)
        visual_buffer.clear()

        if SERVER_LOOP:
            asyncio.run_coroutine_threadsafe(
                websocket.send_json({"type": "command", "content": "snapshot"}), SERVER_LOOP
            )

        # 挂起等待图片，传入大模型的 stop_event 保证可以被秒速打断
        img = visual_buffer.wait_for_image(stop_event=agent.scheduler.stop_event, timeout=15)

        if img != "TIMEOUT":
            print(Fore.GREEN + "✅ [Server] 视觉信号接收完毕。" + Style.RESET_ALL)
            return img
        else:
            print(Fore.RED + "❌ [Server] 视觉信号请求超时或被中断。" + Style.RESET_ALL)
            return "TIMEOUT"

    if agent:
        agent.tool_manager.set_snapshot_callback(request_remote_snapshot)
        # 上线！改变状态
        agent.scheduler.change_state(GlobalState.IDLE, force=True)

    sender_task = asyncio.create_task(sender_loop(websocket))

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            # 1. 对话请求
            if msg_type == "chat":
                content = data.get("content")
                tag = data.get("tag", "text")
                print(Fore.BLUE + f"📩 [收到] {content}")
                # [任务下发] 封装并投递至防弹调度队列 (Bulletproof Queue)
                # 绝不在此处 await 阻塞 WebSocket 的接收循环。
                if agent:
                    # ================= [Barge-in 状态重置] =================
                    # 收到完整文本意味着用户发言结束。此时必须立即释放 LLM 的推理手刹(stop_event)。
                    agent.scheduler.reset_stop_event()
                    # 状态流转: LISTENING -> TRANSCRIBING (如果是打字则是 IDLE->TRANSCRIBING，用 force=True 兼容)
                    agent.scheduler.change_state(GlobalState.TRANSCRIBING, force=True)
                    # ==============================================

                    voice_instr = "【系统提示：语音对话模式。简短、口语化、傲娇。】" if tag == "voice" else None
                    agent.submit_chat(user_input=content, hidden_instruction=voice_instr, tag=tag)

            # 2. 状态信号
            elif msg_type == "signal":
                signal = data.get("content")
                if signal == "listen_start":
                    if agent:
                        current_state = agent.scheduler.current_state

                        # ==========================================
                        # [P0 级打断判定] (Barge-in / OOB Signal)
                        # 核心逻辑：如果大模型正在 THINKING 或 SPEAKING 时，突然监听到用户出声，
                        # 则视为恶意打断。立即触发 P0 级强制刹车，截断显存流出，并扣除情绪值。
                        # ==========================================
                        if current_state != GlobalState.IDLE:
                            print(
                                Fore.YELLOW + f"👂 [Server] 敢在 {current_state.name} 状态插嘴 -> 触发 P0 级强制刹车！" + Style.RESET_ALL)
                            # 只有打断我工作/说话，才会触发暴怒！
                            agent.update_emotion("user_interrupt", intensity=0.8)
                            agent.scheduler.trigger_interrupt("User Barge-in")
                        else:
                            print(Fore.GREEN + "👂 [Server] 空闲状态，监听到用户开始说话..." + Style.RESET_ALL)
                            # 正常对话开端，不扣情绪值，乖乖切入 LISTENING 状态
                            agent.scheduler.change_state(GlobalState.LISTENING)

                        # 无论是不是打断，保底给躯壳发个清空队列的指令，确保物理静音
                        await websocket.send_json({"type": "interrupt"})

                elif signal == "speak_end":
                    # Body TTS 播报结束，真正意义上的交还发言权
                    print(Fore.CYAN + "🎤 [Server] Body 播报完毕，重置空闲状态。" + Style.RESET_ALL)
                    if agent:
                        # 仅当当前状态为 SPEAKING 时才切换到 IDLE
                        if agent.scheduler.current_state == GlobalState.SPEAKING:
                            agent.scheduler.change_state(GlobalState.IDLE)
                        else:
                            print(Fore.YELLOW + "⚠️ [Server] 忽略 speak_end，当前状态非 SPEAKING" + Style.RESET_ALL)

                elif signal == "listen_abort":
                    # ==========================================
                    # [VAD 杂音过滤防误触] (Noise Rejection)
                    # 当底层 Whisper 发现录到的是键盘声/咳嗽声且放弃转录时，下发此信号。
                    # 防御机制：只有当系统真的因为这声杂音切入了 LISTENING 时，才回退至 IDLE。
                    # 绝不允许杂音强行中断正在高速运转的 THINKING (大模型推理) 状态！
                    # ==========================================
                    if agent and agent.scheduler.current_state in [GlobalState.LISTENING, GlobalState.TRANSCRIBING,
                                                                   GlobalState.INTERRUPTED]:
                        print(Fore.YELLOW + "🔕 [Server] 杂音过滤，放弃聆听，恢复空闲。" + Style.RESET_ALL)
                        agent.scheduler.reset_stop_event()
                        agent.scheduler.change_state(GlobalState.IDLE, force=True)

            # 3. 视觉回传
            elif msg_type == "image":
                content = data.get("content")
                try:
                    img_bytes = base64.b64decode(content)
                    pil_image = Image.open(io.BytesIO(img_bytes))
                    visual_buffer.set_image(pil_image)
                except Exception as e:
                    print(Fore.RED + f"❌ [Server] 图片解码失败: {e}")


            elif msg_type == "env_sniff":
                env_data = data.get("content", {})
                window = env_data.get("window", "")
                clipboard = env_data.get("clipboard", "")
                # [新增] 给我打印出来！不然你怎么知道我闻到了没？！
                print(Fore.MAGENTA + f"🐕 [Sniffer] 嗅探到环境变化 | 窗口: {window[:20]} | 剪贴板: {clipboard[:20]}..." + Style.RESET_ALL)
                if agent:
                    agent.current_window = window
                    agent.current_clipboard = clipboard

    except WebSocketDisconnect:
        print(Fore.YELLOW + "🔌 [Server] 躯壳断开")
        if agent:
            # P0级刹车，清理任务，进入断线挂起状态
            agent.scheduler.trigger_interrupt("Client Offline")
            agent.scheduler.change_state(GlobalState.OFFLINE, force=True)

            # [删除原来的 patience = 50，换成这两句！] 躯壳断了，陷入抑郁和低迷
            agent.emotion.P = -0.6
            agent.emotion.A = -0.8
            # 断线时不走代理，手动触发一次 UI 刷新记录日志
            agent.ui.output_action("emotion_change", {"status": agent.emotion.get_status()})

    except Exception as e:
        print(Fore.RED + f"❌ [Server Error] {e}")
    finally:
        sender_task.cancel()


async def sender_loop(websocket: WebSocket):
    """ [Server -> Body] 下行神经通路 """
    # 只保留抹除工具指令的正则
    tool_pattern = re.compile(r"\[\[.*?\]\]", re.DOTALL)

    try:
        while True:
            message = await ws_ui.msg_queue.get()

            # 如果大模型已经被掐断了，抛弃队列里积压的旧文本
            if agent and agent.scheduler.stop_event.is_set():
                ws_ui.msg_queue.task_done()
                continue

            msg_type = message.get("type")
            content = message.get("content")

            if msg_type == "text_stream":
                print(Fore.RED + str(content) + Style.RESET_ALL, end="", flush=True)
            elif msg_type == "text_full":
                print()  # 换行
            elif msg_type == "action":
                action_name = message.get("action")
                if action_name == "vision_end":
                    await websocket.send_json({"type": "command", "content": "vision_end"})
                elif action_name == "emotion_change":
                    # UI 控制台打印，由于后面的 else 会将其透传给 Body，这里不需要发 ws 包
                    status = message.get("data", {}).get("status", "neutral")
                    print(Fore.MAGENTA + f"\n⚡ [Autonomic] 神经反射触发表情: {status}" + Style.RESET_ALL)
                else:
                    print(Fore.MAGENTA + f"\n⚡ [Action] {action_name}: {message.get('data')}" + Style.RESET_ALL)

            # --- 消息下发判定 ---
            if msg_type == "text_full":
                # 清洗文本：去掉所有的工具指令 [[...]]
                clean_text = tool_pattern.sub("", content).strip()
                # 只有当清洗后还有“人话”时，才发给躯壳朗读
                if clean_text:
                    await websocket.send_json({"type": "text_full", "content": clean_text})
            else:
                # 把非 text_full 的消息（比如 action 表情指令）原样透传给 Body
                await websocket.send_json(message)

            ws_ui.msg_queue.task_done()

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(Fore.RED + f"❌ [Sender Error] 神经中枢下行崩溃: {e}" + Style.RESET_ALL)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, ws_ping_interval=None)