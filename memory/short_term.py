# memory/short_term.py
from config import settings
from colorama import Fore, Style


class ShortTermMemory:
    def __init__(self, system_prompt, max_rounds=15):
        self.system_prompt = {"role": "system", "content": system_prompt}
        self.history = []  # 格式: {"role": ..., "content": ..., "tag": ...}
        self.max_rounds = max_rounds

    def add_message(self, role, content, tag=None):
        """
        role: user / assistant / system
        tag: voice / vision / tool / thought (可选)
        """
        # 如果有标签，我们稍微加工一下内容，或者存入 metadata
        # 对于目前的模型，直接在内容里注入 [标签] 是最有效的
        annotated_content = content
        if tag == "vision":
            # annotated_content = f"👤 [视觉观测] {content}"
            # 如果是 System 存入的视觉，我们根本不存进 History！
            # 视觉信息是“瞬时”的，下一轮就过期了。
            # 所以直接 return，或者存一个极简标记
            return
        elif tag == "voice":
            annotated_content = f"🎤 [语音输入] {content}"
        elif tag == "tool":
            annotated_content = f"🛠️ [工具返回] {content}"
        elif tag == "tool" and len(content) > 500:
            preview = content[:200]
            suffix = content[-100:]
            annotated_content = f"🛠️ [工具返回 - 已折叠] {preview}\n...\n{suffix}"

        self.history.append({"role": role, "content": annotated_content})
        self._trim()

    def _trim(self):
        """ 简单的滑动窗口 """
        if len(self.history) > self.max_rounds * 2:
            self.history = self.history[-(self.max_rounds * 2):]

    def get_full_context(self):
        """ 返回标准格式的 Context 列表 """
        return [self.system_prompt] + self.history

    def get_last_assistant_msg(self):
        """ 获取最后一次 AI 的回复 """
        for msg in reversed(self.history):
            if msg["role"] == "assistant":
                return msg["content"]
        return ""

    def clear(self):
        self.history = []
        print(Fore.YELLOW + "🧹 [Memory] 记忆已清空。" + Style.RESET_ALL)