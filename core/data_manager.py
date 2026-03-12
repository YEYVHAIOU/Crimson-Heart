# core/data_manager.py
import json
import os
from datetime import datetime
import config

class DataLogger:
    def __init__(self, save_path=None):
        # 动态绑定到项目根目录下的 data 文件夹
        self.save_path = save_path or os.path.join(config.PROJECT_ROOT, "data", "dataset_alpaca.jsonl")
        os.makedirs(os.path.dirname(self.save_path), exist_ok=True)

    def log_interaction(self, system_prompt, user_input, assistant_output):
        """
        [数据沉淀] 自动构建高质量 SFT (监督微调) 数据集
        彻底抛弃传统的全量上下文冗余日志，仅提取当前轮次的 (Instruction -> Output)。
        直接将其格式化为标准的 Alpaca jsonl 格式。
        这赋予了 Crimson "自我迭代" 的潜力：聊得越多，越能提纯出优质语料用于未来的模型微调。
        """
        record = {
            "timestamp": datetime.now().isoformat(),
            # 微调三要素：指令(User)、输入(空)、输出(AI)
            "instruction": user_input,
            "input": "",
            "output": assistant_output,
            "system": system_prompt
        }

        # 这样存下来的数据，每一行都是独立的训练样本，清爽多了
        with open(self.save_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")