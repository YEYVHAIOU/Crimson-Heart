# core/llm_engine.py
import torch
import threading
import queue
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TextIteratorStreamer,
    BitsAndBytesConfig,
    StoppingCriteria,
    StoppingCriteriaList
)
from config import settings
from colorama import Fore, Style


class LLMEngine:
    """
    底层大语言模型推理引擎 (4-bit Quantized VRAM Optimizer)

    特点：
    1. 独占锁机制 (_inference_lock)：防止并发对话导致显存爆炸或死锁。
    2. 双重刹车系统 (DualStopCriteria)：同时监听全局打断事件 (Barge-in) 和局部超时事件，
       实现在模型生成中途的毫秒级切断。
    """
    def __init__(self):
        print(Fore.RED + "⚙️ [Core] 正在初始化神经回路 (加入独立防复活锁)..." + Style.RESET_ALL)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.tokenizer = None
        self.model = None
        self._inference_lock = threading.Lock()
        self._load_model()

    def _load_model(self):
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(settings.MODEL_PATH, trust_remote_code=True)
            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
            ) if settings.LOAD_IN_4BIT else None

            self.model = AutoModelForCausalLM.from_pretrained(
                settings.MODEL_PATH,
                device_map="auto",
                quantization_config=quantization_config,
                trust_remote_code=True,
                low_cpu_mem_usage=True
            )
            print(Fore.GREEN + "✅ [Core] 模型挂载完毕，神经通路已锁定。")
        except Exception as e:
            print(Fore.RED + f"❌ [Fatal] 神经回路断路: {e}" + Style.RESET_ALL)
            raise e

    def generate_stream(self, messages, global_stop_event: threading.Event):
        # 加入超时机制！如果 2 秒拿不到锁，说明底层彻底死锁。
        # 绝不能卡住主线程，直接强行返回错误并放弃本次生成！
        if not self._inference_lock.acquire(timeout=2.0):
            print(Fore.RED + "❌ [Engine] 检测到 GPU 推理锁死，强行跳过本次生成。" + Style.RESET_ALL)
            yield "（系统提示：脑部神经回路暂时过载，请稍后再试。）"
            return

        local_stop_event = threading.Event()

        class DualStopCriteria(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return global_stop_event.is_set() or local_stop_event.is_set()

        processed_messages = self._preprocess_context(messages)
        text = self.tokenizer.apply_chat_template(processed_messages, tokenize=False, add_generation_prompt=True)
        model_inputs = self.tokenizer([text], return_tensors="pt").to(self.device)

        streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True, timeout=15.0)

        generation_kwargs = dict(
            model_inputs,
            streamer=streamer,
            max_new_tokens=settings.MAX_NEW_TOKENS,
            temperature=settings.TEMPERATURE,
            repetition_penalty=1.1,
            do_sample=True,
            top_p=0.9,
            stopping_criteria=StoppingCriteriaList([DualStopCriteria()])
        )

        def run_generate_safely():
            try:
                self.model.generate(**generation_kwargs)
            except Exception as e:
                print(Fore.RED + f"\n❌ [LLM Error] GPU 推理底层崩溃: {e}" + Style.RESET_ALL)
            finally:
                # 极其关键！无论模型是正常算完、被打断还是崩溃，
                # 都必须手动调用 streamer.end()，否则等待队列会永远挂起，导致全局卡死！
                if hasattr(streamer, 'end'):
                    streamer.end()
                self._inference_lock.release()

        threading.Thread(target=run_generate_safely).start()

        try:
            for new_text in streamer:
                if global_stop_event.is_set():
                    break
                yield new_text
        except queue.Empty:
            print(Fore.RED + "\n❌ [Engine] 推理超时，已强行释放。" + Style.RESET_ALL)
            yield "（系统提示：思考负担过重，出现短暂的神经断裂。）"
        finally:
            local_stop_event.set()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def _preprocess_context(self, messages, max_chars=6000):
        if len(messages) <= 2: return messages
        total_chars = sum(len(m['content']) for m in messages)
        if total_chars < max_chars: return messages

        system_msg = messages[0]
        recent_msgs = messages[-5:]

        # [Critical] Qwen 模型的 Template 极度严格，上下文截断后第一句必须是 'user' 角色。
        # 这里做强制校验和剔除，防止底层 Transformers 库默默崩溃导致线程死锁。
        while recent_msgs and recent_msgs[0]['role'] != 'user':
            recent_msgs.pop(0)

        if not recent_msgs:
            # 如果历史删光了，强行找出最后一句 user 的话保底
            for m in reversed(messages):
                if m['role'] == 'user':
                    recent_msgs = [m]
                    break

        return [system_msg] + recent_msgs