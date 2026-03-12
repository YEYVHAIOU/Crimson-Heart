# tools/vision_tool.py
import os
import torch
from PIL import Image
from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
from qwen_vl_utils import process_vision_info
from colorama import Fore, Style
from threading import Event

import config

class VisionTool:
    def __init__(self, device="cpu"):
        torch.set_num_threads(8)
        print(Fore.CYAN + f"👁️ [Tool] 正在装载视觉模组 (Qwen2-VL)..." + Style.RESET_ALL)
        try:
            self.model = Qwen2VLForConditionalGeneration.from_pretrained(
                "Qwen/Qwen2-VL-2B-Instruct",
                dtype=torch.float32,
                device_map=device
            )
            self.processor = AutoProcessor.from_pretrained("Qwen/Qwen2-VL-2B-Instruct", use_fast=True)
            self.device = device
            print(Fore.CYAN + "✅ [Tool] 视觉模组就绪。" + Style.RESET_ALL)
        except Exception as e:
            print(Fore.RED + f"❌ [Tool] 视觉模组加载失败: {e}" + Style.RESET_ALL)
            self.model = None

    def run(self, prompt="详细描述屏幕内容", image: Image.Image = None, stop_event: Event = None):
        if not self.model: return "（视觉系统离线）"

        # 仅在刚进门时拦截：如果网络等待阶段被掐断了，就不浪费 GPU 了
        if (stop_event and stop_event.is_set()) or image == "TIMEOUT" or image is None:
            return "（视觉采样已放弃）"

        print(Fore.CYAN + "📸 [Vision] 正在分析远端视觉信号 (原子操作)..." + Style.RESET_ALL)
        try:
            target_image = image
            target_image.thumbnail((640, 480))

            messages = [{
                "role": "user",
                "content": [
                    {"type": "image", "image": target_image},
                    {"type": "text", "text": prompt},
                ],
            }]

            text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            image_inputs, video_inputs = process_vision_info(messages)

            inputs = self.processor(
                text=[text],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt",
            ).to(self.device)

            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            # [核心改动] 移除所有 stop_event 补丁。
            # 视觉处理极快(通常<1秒)，让它作为原子操作一次性跑完，绝不半路截断导致显存卡死。
            generated_ids = self.model.generate(
                **inputs,
                max_new_tokens=128,
                repetition_penalty=1.2,
                do_sample=False
            )

            generated_ids_trimmed = [
                out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            output_text = self.processor.batch_decode(
                generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )[0]

            print(Fore.CYAN + f"👁️ 看到: {output_text}" + Style.RESET_ALL)
            return output_text
        except Exception as e:
            return f"视觉分析错误: {e}"