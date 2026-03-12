# tools/memory_tool.py
class MemoryTool:
    def __init__(self, ltm_instance):
        self.ltm = ltm_instance

    def run(self, fact: str):
        if not fact: return "错误：要记住的内容为空。"
        self.ltm.memorize(fact)
        return f"已成功将该情报刻入海马体：{fact}"