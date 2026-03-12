# interfaces/console.py
from core.interface import BaseInterface
from colorama import Fore, Style


class ConsoleUI(BaseInterface):
    def output_text(self, text: str):
        # 红色字体代表 Crimson 正在说话
        print(Fore.RED + text + Style.RESET_ALL, end="", flush=True)

    def output_final(self, text: str):
        # 换行
        print()

    def output_action(self, action_type: str, data: dict = None):
        if action_type == "emotion_change":
            status = data.get("status", "neutral")
            print(Fore.MAGENTA + f"\n⚡ [Active] 情绪变化: {status}" + Style.RESET_ALL)
        else:
            print(Fore.YELLOW + f"\n⚡ [Action] {action_type}: {data}" + Style.RESET_ALL)

    def system_log(self, text: str, level: str = "info"):
        # 根据日志级别显示不同颜色
        color = Fore.BLUE
        if level == "warn": color = Fore.YELLOW
        if level == "error": color = Fore.RED
        if level == "success": color = Fore.GREEN

        print(color + f"{text}" + Style.RESET_ALL)

    def interrupt(self):
        """ 强制打断当前的输出/动作 """
        pass