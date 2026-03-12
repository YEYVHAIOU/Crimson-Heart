# senses/voice.py
import edge_tts
import pygame
import asyncio
import io
from colorama import Fore, Style

class Voice:
    def __init__(self, voice_name="zh-CN-XiaoxiaoNeural"):
        self.voice_name = voice_name
        self._is_stopped = False

        try:
            pygame.mixer.quit()
            pygame.mixer.init(frequency=24000, buffer=16384, channels=1)
        except Exception as e:
            print(Fore.RED + f"❌ [Voice] 音频驱动初始化失败: {e}" + Style.RESET_ALL)

    def is_busy(self):
        return pygame.mixer.music.get_busy()

    def stop(self):
        """ 强制打断 (Barge-in) """
        if pygame.mixer.get_init():
            self._is_stopped = True
            pygame.mixer.music.stop()

    async def speak(self, text):
        """
        生成并播放语音。
        返回 True 表示自然播放完毕；返回 False 表示被强行打断。
        """
        if not text: return True

        self.stop()
        self._is_stopped = False

        try:
            communicate = edge_tts.Communicate(text, self.voice_name)
            audio_data = b""

            async for chunk in communicate.stream():
                if self._is_stopped: return False # 合成中途被打断
                if chunk["type"] == "audio":
                    audio_data += chunk["data"]

            if not audio_data: return True

            audio_stream = io.BytesIO(audio_data)
            pygame.mixer.music.load(audio_stream)
            pygame.mixer.music.play()

            # 等待播放结束，通过 asyncio.sleep 交出控制权，不阻塞其他网络接收
            while pygame.mixer.music.get_busy():
                if self._is_stopped:
                    pygame.mixer.music.stop()
                    return False # 播放中途被打断
                await asyncio.sleep(0.05)

            audio_stream.close()
            return True # 自然播放完毕

        except Exception as e:
            print(Fore.RED + f"❌ [Voice] 表达中枢故障: {e}" + Style.RESET_ALL)
            self.stop()
            return False