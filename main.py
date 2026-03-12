# main.py
import os
import threading
import asyncio
import pyautogui
import re
import time

import config

from core.agent import CrimsonAgent
from core.scheduler import GlobalState
from core.interface import BaseInterface
from colorama import init, Fore, Style

init(autoreset=True)

# --- 本地全功能 UI 代理 ---
class LocalAdvancedUI(BaseInterface):
    def __init__(self, mode="text"):
        self.mode = mode
        self.agent = None  # 稍后绑定
        self.voice = None
        self.ear = None  # 稍后绑定 (仅语音模式用到)

        if self.mode == "voice":
            from senses.voice import Voice
            self.voice = Voice()
            self.audio_queue = asyncio.Queue()
            self.loop = asyncio.new_event_loop()

            self.voice_thread = threading.Thread(target=self._start_voice_loop, daemon=True)
            self.voice_thread.start()

    def _start_voice_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._process_audio_queue())

    async def _process_audio_queue(self):
        """ 独立的 TTS 播放队列 """
        while True:
            text = await self.audio_queue.get()

            if self.ear: self.ear.pause()

            finished = await self.voice.speak(text)
            self.audio_queue.task_done()

            # 播放完毕，切回 IDLE
            if finished and self.audio_queue.empty():
                if self.agent and self.agent.scheduler.current_state == GlobalState.SPEAKING:
                    self.agent.scheduler.change_state(GlobalState.IDLE)
                if self.ear: self.ear.resume()

    def output_text(self, text: str):
        print(Fore.RED + text + Style.RESET_ALL, end="", flush=True)

    def output_final(self, text: str):
        print()  # 换行

        # ==========================================
        # [并发同步控制] 状态机自旋锁 (Spinlock for State Machine)
        # 因为 LLM 吐字完毕和状态机切入 SPEAKING 之间存在微秒级的异步时间差。
        # 这里使用轻量级轮询死等，确保系统确实切入了播报状态后，再由本方法安全地将其拉回 IDLE。
        # 从而完美避免下一轮对话提前抢占麦克风。
        # ==========================================
        def delayed_idle_reset():
            for _ in range(30):  # 最多轮询等待 3 秒
                time.sleep(0.1)
                if self.agent and self.agent.scheduler.current_state == GlobalState.SPEAKING:
                    self.agent.scheduler.change_state(GlobalState.IDLE)
                    break

        if self.mode == "voice":
            clean_text = re.sub(r"\[\[.*?(?:\]\]|\]\}|\]\)|\]）|\]|$)", "", text, flags=re.DOTALL).strip()
            if clean_text:
                asyncio.run_coroutine_threadsafe(self.audio_queue.put(clean_text), self.loop)
            else:
                threading.Thread(target=delayed_idle_reset).start()
        else:
            # 文本模式瞬间输出完毕，触发轮询复位
            threading.Thread(target=delayed_idle_reset).start()

    def output_action(self, action_type: str, data: dict = None):
        if action_type == "emotion_change":
            print(Fore.MAGENTA + f"\n⚡ [Emotion] 情绪切换为: {data.get('status')}" + Style.RESET_ALL)

    def system_log(self, text: str, level: str = "info"):
        color = Fore.BLUE
        if level == "warn": color = Fore.YELLOW
        if level == "error": color = Fore.RED
        if level == "success": color = Fore.GREEN
        print(color + text + Style.RESET_ALL)

    def interrupt(self):
        if self.mode == "voice" and self.voice:
            self.voice.stop()
            while not self.audio_queue.empty():
                try:
                    self.audio_queue.get_nowait()
                    self.audio_queue.task_done()
                except:
                    break


def local_snapshot_callback():
    print(Fore.YELLOW + "📸 [Local] 正在截取本机屏幕..." + Style.RESET_ALL)
    return pyautogui.screenshot()

def check_environment():
    import torch
    if not torch.cuda.is_available():
        print(Fore.YELLOW + "⚠️ [Warning] 未检测到 NVIDIA GPU 加速，Crimson-Heart 将以纯 CPU 模式运行，速度会非常缓慢！" + Style.RESET_ALL)
    else:
        vram = torch.cuda.get_device_properties(0).total_memory / 1024**3
        if vram < 6: # 小于 6GB 显存警告
            print(Fore.YELLOW + f"⚠️ [Warning] 显存仅 {vram:.1f}GB，运行 7B 模型可能会遇到 OOM (内存溢出) 崩溃。" + Style.RESET_ALL)

# --- 主程序 ---
def main():
    print(Fore.RED + "🧱 [SYSTEM] Booting Crimson (Local Integrated Mode)..." + Style.RESET_ALL)

    print(Fore.CYAN + "请选择启动模式:" + Style.RESET_ALL)
    print("1. 💬 纯文本模式 (适合安静敲字调试，无日志穿插)")
    print("2. 🎤 语音+视觉全功能 (本地闭环，对标 C/S 架构)")
    choice = input(Fore.CYAN + "请输入 1 或 2: " + Style.RESET_ALL).strip()

    mode = "voice" if choice == "2" else "text"

    try:
        local_ui = LocalAdvancedUI(mode=mode)
        agent = CrimsonAgent(ui=local_ui)
        local_ui.agent = agent

        agent.tool_manager.set_snapshot_callback(local_snapshot_callback)
        agent.scheduler.change_state(GlobalState.IDLE, force=True)

        # ================== A: 纯文本模式 ==================
        if mode == "text":
            print(Fore.GREEN + "🟢 本地纯文本模式已就绪。" + Style.RESET_ALL)
            while True:
                try:
                    # ==========================================
                    # [UI 体验优化] 控制台标准输出锁 (Stdout Lock)
                    # 严密阻塞：只有当底层状态机彻底回到 IDLE (非思考、非调用工具) 时，
                    # 才允许展示 "👤 You: " 提示符。
                    # 这确保了大模型的 Debug 日志和工具输出绝对不会污染用户的打字区域。
                    # ==========================================
                    while agent.scheduler.current_state != GlobalState.IDLE:
                        time.sleep(0.1)

                    user_input = input(Fore.BLUE + "\n👤 You: " + Style.RESET_ALL)
                    if not user_input.strip(): continue
                    if user_input.lower() in ['exit', 'quit']: break

                    # 视觉直通指令： /img 图片路径 [附加文字]
                    if user_input.startswith("/img "):
                        parts = user_input.split(" ", 2)
                        img_path = parts[1].strip('"').strip("'")  # 去除可能的引号
                        prompt = parts[2] if len(parts) > 2 else "这是一张什么图片？评价一下。"

                        agent.submit_image_chat(img_path, prompt)
                        continue  # 直接跳过普通的 submit_chat

                    agent.submit_chat(user_input, tag="text")

                except KeyboardInterrupt:
                    print("\n👋 下线。")
                    break

        # ================== B: 语音全功能模式 ==================
        elif mode == "voice":
            from senses.listener import Ear
            print(Fore.GREEN + "🟢 本地语音模式已就绪。耳朵已张开..." + Style.RESET_ALL)
            ear = Ear(model_size="medium", device="cpu", compute_type="int8")
            local_ui.ear = ear

            def on_voice_detected():
                agent.scheduler.trigger_interrupt("Local User Barge-in")
                local_ui.interrupt()

            while True:
                try:
                    user_text = ear.listen_continuous(state_callback=on_voice_detected)

                    if user_text and len(user_text) > 1:
                        print(Fore.BLUE + f"🎤 [Mic]: {user_text}" + Style.RESET_ALL)

                        agent.scheduler.reset_stop_event()
                        agent.scheduler.change_state(GlobalState.TRANSCRIBING, force=True)

                        voice_instr = "【系统提示：语音对话模式。简短、口语化。】"
                        agent.submit_chat(user_text, hidden_instruction=voice_instr, tag="voice")
                    else:
                        if agent.scheduler.current_state in [GlobalState.LISTENING, GlobalState.INTERRUPTED]:
                            agent.scheduler.reset_stop_event()
                            agent.scheduler.change_state(GlobalState.IDLE, force=True)

                except KeyboardInterrupt:
                    print("\n👋 下线。")
                    break

    except Exception as e:
        print(Fore.RED + f"❌ 致命错误: {e}")


if __name__ == "__main__":
    check_environment()
    main()