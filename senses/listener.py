# senses/listener.py
import time
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from colorama import Fore, Style
import queue
import collections
import threading


class Ear:
    def __init__(self, model_size="medium", device="cpu", compute_type="int8"):
        print(Fore.CYAN + f"👂 [Senses] 听觉神经初始化 ({model_size})..." + Style.RESET_ALL)
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

        self.SAMPLERATE = 16000
        self.CHUNK_SIZE = 1024
        self.SILENCE_LIMIT = 1.5
        self.PRE_ROLL_SECONDS = 0.5

        self.q = queue.Queue()
        self.is_listening_active = False

        # [核心] 使用 Event 替代普通的 boolean，支持优雅阻塞
        self.active_event = threading.Event()
        self.active_event.set()  # 默认张开耳朵

        self.min_threshold = 0.2
        self.threshold = self.min_threshold
        self.energy_history = collections.deque(maxlen=20)

    def pause(self):
        """ 暂时性耳聋 (阻塞录音进程) """
        if self.active_event.is_set():
            self.active_event.clear()
            with self.q.mutex:
                self.q.queue.clear()

    def resume(self):
        """ 恢复听觉 """
        if not self.active_event.is_set():
            with self.q.mutex:
                self.q.queue.clear()
            self.active_event.set()

    def callback(self, indata, frames, time, status):
        # [防爆防线] 如果耳朵被捂住了，底层的声卡数据直接丢弃，不进队列
        if self.active_event.is_set():
            self.q.put(indata.copy())

    def listen_continuous(self, state_callback=None):
        audio_buffer = []
        pre_roll = collections.deque(maxlen=int(self.SAMPLERATE / self.CHUNK_SIZE * self.PRE_ROLL_SECONDS))
        silence_start = None
        has_voice = False

        print(Fore.CYAN + "👂 [Senses] 持续监听中..." + Style.RESET_ALL)

        try:
            with sd.InputStream(samplerate=self.SAMPLERATE, channels=1, callback=self.callback,
                                blocksize=self.CHUNK_SIZE):
                while True:
                    # [核心] 如果耳朵被 pause()，这里会优雅挂起，不占 CPU，直到 resume()
                    self.active_event.wait()

                    try:
                        # 加上 timeout 防止队列空时卡死无法响应 pause
                        data = self.q.get(timeout=0.1)
                    except queue.Empty:
                        continue

                    energy = np.sqrt(np.mean(data ** 2)) * 10

                    if not has_voice:
                        self.energy_history.append(energy)
                        avg = sum(self.energy_history) / len(self.energy_history)
                        self.threshold = max(self.min_threshold, avg * 1.3)
                        pre_roll.append(data)

                    if energy > self.threshold:
                        if not has_voice:
                            # 触发 LISTENING 状态信号给服务端
                            if state_callback: state_callback()
                            print(Fore.GREEN + f"🎤 [Senses] 捕捉声波 (E={energy:.2f})..." + Style.RESET_ALL)
                            has_voice = True
                            self.is_listening_active = True
                            audio_buffer.extend(list(pre_roll))

                        audio_buffer.append(data)
                        silence_start = None
                    else:
                        if has_voice:
                            audio_buffer.append(data)
                            if silence_start is None:
                                silence_start = time.time()
                            elif time.time() - silence_start > self.SILENCE_LIMIT:
                                break
        finally:
            self.is_listening_active = False

        if len(audio_buffer) < 5: return None

        print(Fore.CYAN + "⏹️ [Senses] 录音结束，转录中..." + Style.RESET_ALL)
        full_audio = np.concatenate(audio_buffer, axis=0).flatten()
        return self.transcribe(full_audio)

    def transcribe(self, audio_data):
        try:
            segments, _ = self.model.transcribe(
                audio_data, beam_size=5, language="zh",
                initial_prompt="Crimson, 助手, 傲娇, 毒舌, 科技, 简短",
                vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500)
            )
            text = "".join([s.text for s in segments]).strip()

            # ==========================================
            # [Developer Note] Whisper 幻觉过滤网 (Hallucination Net)
            # 机制说明：Whisper 模型在遇到纯环境白噪音或低音量时，极易触发训练集数据泄漏，
            # 狂暴吐出诸如“未经作者授权”、“李宗盛词曲”、“Amara.org”等无意义的片尾字幕。
            # 必须在此做物理级的词库拦截，防止 Crimson 听到幻觉后疯狂自言自语。
            # ==========================================
            hallucinations = ["谢谢", "字幕", "点赞", "订阅", "观看", "李宗盛", "词曲", "未经作者", "Amara",
                              "Subtitles", "Copyright"]
            for h in hallucinations:
                if h in text: return ""

            if not any(char.isalnum() for char in text): return ""
            if len(text) < 2: return ""

            return text
        except Exception as e:
            print(Fore.RED + f"❌ 转录失败: {e}" + Style.RESET_ALL)
            return ""