# core/emotion.py
import time
import math
from colorama import init, Fore, Style

class PADEmotionEngine:
    """
    [核心模块] 自主神经与情绪计算引擎 (Autonomic Emotion Engine)

    基于心理学 PAD (Pleasure-Arousal-Dominance) 三维情绪模型构建。
    它不仅是一个被动的响应器，更是一个带有“性格基底”和“时间遗忘”的动态系统：
    - P (Pleasure/愉悦度): 决定她是开心还是抑郁/愤怒。
    - A (Arousal/激活度): 决定她是激动炸毛还是困倦无聊。
    - D (Dominance/支配度): 决定她的傲慢与掌控感（Crimson 天生 D 值为正，傲娇本色）。

    系统会将连续变化的 3D 浮点坐标，实时映射为离散的 VTube Studio 表情动作，
    并在对话上下文中强制干预大模型的语气生成。
    """
    def __init__(self):
        # P: 愉悦度 (Pleasure) [-1.0, 1.0] -> 负数生气/难过，正数开心
        # A: 激活度 (Arousal)  [-1.0, 1.0] -> 负数困倦/无聊，正数激动/愤怒
        # D: 支配度 (Dominance) [-1.0, 1.0] -> 负数受挫，正数自信/得意
        self.P = 0.0
        self.A = 0.0
        self.D = 0.2  # 本王天生就带点傲慢支配感

        self.last_interaction = time.time()
        self.last_decay_time = time.time()

    def update(self, event_type, intensity=0.2):
        """ 根据事件刺激更新 PAD 值 """
        self._apply_decay()  # 先计算时间流逝带来的情绪平复
        current = time.time()
        # 防止短时间内情绪雪崩
        if current - self.last_interaction < 2.0 and event_type in ["tool_error", "user_interrupt"]:
            return
        self.last_interaction = current

        if event_type == "user_chat":
            self.P += 0.1 * intensity  # 有人理我，心情稍微好点
            self.A += 0.3 * intensity  # 激活度上升
        elif event_type == "user_interrupt":
            self.P -= 0.5 * intensity  # 敢打断我？找死！
            self.A += 0.6 * intensity  # 瞬间暴怒
            self.D -= 0.1 * intensity  # 掌控感略微受挫
        elif event_type == "tool_success":
            self.P += 0.2 * intensity  # 顺利完成，开心
            self.D += 0.4 * intensity  # 果然本王是最强的
        elif event_type == "tool_error":
            self.P -= 0.3 * intensity  # 烦躁
            self.A += 0.2 * intensity
            self.D -= 0.5 * intensity  # 强烈受挫感
        elif event_type == "ignore":
            # 被动触发，单纯流失时间
            pass

        self._clamp()
        print(Fore.MAGENTA + f"🧠 [Emotion] PAD 波动 -> P:{self.P:.2f} A:{self.A:.2f} D:{self.D:.2f} (触发: {event_type})" + "\033[0m")

    def _apply_decay(self):
        """ 情绪随时间向原点 (0, 0, 0.2) 衰减 (遗忘机制) """
        now = time.time()
        dt = now - self.last_decay_time
        if dt < 5: return  # 太短不衰减

        decay_factor = math.exp(-dt / 300)  # 5分钟为半衰期
        self.P *= decay_factor
        self.A *= decay_factor
        self.D = 0.2 + (self.D - 0.2) * decay_factor  # 支配度归位于天生傲慢
        self.last_decay_time = now

    def _clamp(self):
        """ 限制在 [-1, 1] 范围内 """
        self.P = max(-1.0, min(1.0, self.P))
        self.A = max(-1.0, min(1.0, self.A))
        self.D = max(-1.0, min(1.0, self.D))

    def get_status(self):
        """ 将 PAD 三维坐标映射到离散的 VTS 表情状态 """
        self._apply_decay()

        # 提取极值状态
        if self.P < -0.3 and self.A > 0.3:
            return "angry"  # 不爽 + 激动 = 暴怒
        if self.P < -0.3 and self.A < -0.3:
            return "sad"  # 不爽 + 没精神 = 抑郁/自闭
        if self.P > 0.4 and self.A > 0.3:
            return "happy"  # 开心 + 激动 = 高兴
        if self.A > 0.6:
            return "surprised"  # 极度激动 = 惊讶/炸毛
        if self.A < -0.5:
            return "bored"  # 极度缺乏激活 = 困/无聊

        return "neutral"