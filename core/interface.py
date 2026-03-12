# core/interface.py
from abc import ABC, abstractmethod


class BaseInterface(ABC):
    """
    Crimson Agent 的输出接口协议。
    任何想接管 Crimson 输出的前端（控制台、WebSocket、PyQt）都必须实现这个类。
    """

    @abstractmethod
    def output_text(self, text: str):
        """ 输出流式文本片段 (正在说话) """
        pass

    @abstractmethod
    def output_final(self, text: str):
        """ 一句话说完后的完整文本 (用于 TTS 或 记录) """
        pass

    @abstractmethod
    def output_action(self, action_type: str, data: dict = None):
        """ 输出非语言动作 (表情、动作、状态变化) """
        pass

    @abstractmethod
    def system_log(self, text: str, level: str = "info"):
        """ 系统日志输出 (比如 '正在搜索...', '视觉采样中...') """
        pass

    @abstractmethod
    def interrupt(self):
        """ 强制打断当前的输出/动作 """
        pass