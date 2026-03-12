# core/agent.py
import threading
import time
import random
import re
from config import settings
from core.llm_engine import LLMEngine
from memory.short_term import ShortTermMemory
from core.data_manager import DataLogger
from tools.dispatcher import ToolManager
from memory.long_term import LongTermMemory
from tools.memory_tool import MemoryTool
from core.emotion import PADEmotionEngine
from core.scheduler import TaskScheduler, GlobalState, TaskPriority
from colorama import Fore, Style
from core.interface import BaseInterface
from interfaces.console import ConsoleUI


class CrimsonAgent:
    """
    数字生命体的思维中枢。
    负责统筹 LLM 引擎、长短期记忆 (海马体)、PAD 情绪计算以及工具链调度。
    核心逻辑包含一个改良版的 ReAct (Reasoning and Acting) 思考循环。
    """
    def __init__(self, ui: BaseInterface = None, scheduler: TaskScheduler = None):
        self.ui = ui if ui else ConsoleUI()
        self.ui.system_log("⚙️ [Agent] 正在重塑思维中枢...", "warn")

        self.engine = LLMEngine()
        self.memory = ShortTermMemory(system_prompt=settings.DEFAULT_SYSTEM_PROMPT, max_rounds=15)
        self.logger = DataLogger()
        self.tool_manager = ToolManager()
        self.ltm = LongTermMemory()
        self.tool_manager.registry["MEM"] = MemoryTool(self.ltm)
        self.emotion = PADEmotionEngine()
        self.emotion.last_interaction = time.time()

        self.scheduler = scheduler if scheduler else TaskScheduler()
        self.tool_manager.set_stop_event(self.scheduler.stop_event)

        self.running = True
        self.visual_summary = "暂无观察记录"
        self.last_vision_time = time.time()

        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()

        self.current_window = "未知"
        self.current_clipboard = ""

    def submit_chat(self, user_input, hidden_instruction=None, tag=None):
        self.scheduler.submit_task(
            priority=TaskPriority.P1_USER_REQUEST,
            name="ChatProcessing",
            func=self._process_chat,
            user_input=user_input,
            hidden_instruction=hidden_instruction,
            tag=tag
        )

    # --- ReAct 循环处理逻辑 ---
    def _process_chat(self, user_input, hidden_instruction=None, tag=None):
        """
        [核心] 代理的思考与行动循环 (ReAct Loop)

        工作流：
        1. 抢占 THINKING 状态锁。
        2. 备份当前记忆（防止工具返回的巨量日志污染显存）。
        3. 流式生成回复。检测到 [[工具名: 参数]] 格式时，截断生成。
        4. 切入 EXECUTING_TOOL 状态，挂起大模型，执行本地代码/视觉检测/搜索。
        5. 将工具结果作为 Observation 喂回大模型，继续下一轮循环 (最多 3 次)。
        6. 完成后，回滚记忆，仅保留最终的“人话”输出。
        """

        import re  # 用于最后清理废话文本

        # 1. 任务开始前的双重检查
        if self.scheduler.stop_event.is_set():
            self.scheduler.reset_stop_event()

        # 尝试抢占思考状态
        if not self.scheduler.change_state(GlobalState.THINKING):
            return

        self.update_emotion("user_chat", 0.5)

        # ================= [防显存爆炸：记忆备份] =================
        # 我们把当前的纯净历史记录保存下来。
        # 等系统完全思考完毕后，直接“时光倒流”，把中间庞大的搜索结果全部扔掉！
        history_backup = list(self.memory.history)
        # ========================================================

        self.memory.add_message("user", user_input, tag=tag)
        context = self._get_enhanced_context(hidden_instruction)

        self.ui.output_action("start_speaking", {"round": 1})

        # [Developer Note] 限制最大 ReAct 循环次数为 3。
        # 当前 7B 级别的模型在工具链连续调用时容易陷入逻辑死循环（血的教训）。
        # 强制熔断机制，防止显存爆炸和 API 无限递归。
        max_loops = 3
        current_loop = 0
        final_response = ""

        try:
            while current_loop < max_loops:
                # A. 吐字生成
                response = self._generate_and_print(context)

                # B. 生成被强行打断，直接退出，不要留恋
                if self.scheduler.stop_event.is_set() or not response:
                    return

                # C. [核心时序] 快速预判：模型是不是打算用工具？
                if "[[" in response and "]]" in response:

                    # 1. 【先锁门】在干耗时的重活之前，先把状态切到“执行工具”，昭告天下我正在用GPU！
                    if not self.scheduler.change_state(GlobalState.EXECUTING_TOOL):
                        return

                    self.memory.add_message("assistant", response)

                    # 2. 【再干活】安心执行工具 (这里可能会耗时十几秒，但状态已经安全了)
                    has_tool, tool_result = self.tool_manager.detect_and_execute(response)

                    # 3. 【解除专注】如果是看图，看完图马上让躯壳把捂住耳朵的手放下来
                    if "[[VISION:" in response:
                        self.ui.output_action("vision_end")
                        self.visual_summary = "（刚刚主动观察过）"

                    # 4. 【醒来安检】干完活醒来，检查一下刚才这十几秒里，有没有人喊“闭嘴”？
                    if self.scheduler.stop_event.is_set():
                        self.ui.system_log("🛑 [Agent] 工具执行期间被用户打断，安全退出。", "warn")
                        return

                    # 5. 【分析结果】如果真的执行了工具
                    if has_tool:
                        if "异常" in tool_result or "错误" in tool_result or "Error" in tool_result:
                            self.update_emotion("tool_error", 0.6)  # 报错了，本王很烦躁
                        else:
                            self.update_emotion("tool_success", 0.5)  # 成功了，哼，天才如我

                        # 显存救星：长文本暴力截断 (最多只给大模型看 600 字)
                        if len(tool_result) > 600:
                            tool_result = tool_result[:600] + "\n... (结果过长，已强行截断)"

                        observation = f"【系统观察】工具输出结果：\n{tool_result}\n\n请直接根据上述结果简短回答用户。"
                        self.ui.system_log(f"🔄 [ReAct] 第 {current_loop + 1} 轮工具调用完成，继续思考...", "info")

                        self.memory.add_message("user", observation, tag="tool")
                        context = self.memory.get_full_context()  # 刷新上下文，把结果塞进去

                        # 每次轮回前，强制清理显存碎片！
                        import torch
                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()

                        # 切回 THINKING，让大模型读结果，进入下一次 while 循环
                        if not self.scheduler.change_state(GlobalState.THINKING):
                            return
                        current_loop += 1
                        continue
                    else:
                        # 如果是假警报（格式写错了导致没触发工具），直接切回 THINKING 然后跳出循环
                        self.scheduler.change_state(GlobalState.THINKING)
                        final_response = response
                        break

                else:
                    # D. --- 普通回复分支 (无工具) ---
                    final_response = response
                    break  # 结束循环

            # ================= [防显存爆炸：记忆回滚] =================
            if final_response:
                # 1. 恢复到刚开始对话前的纯净状态
                self.memory.history = history_backup

                # 2. 存入用户真正问的话
                self.memory.add_message("user", user_input, tag=tag)

                # 3. 清理 AI 最终回答中可能残留的工具代码，只留下“干净的人话”
                clean_final = re.sub(r"\[\[.*?\]\]", "", final_response, flags=re.DOTALL).strip()
                if clean_final:
                    self.memory.add_message("assistant", clean_final)
                    self.logger.log_interaction(settings.DEFAULT_SYSTEM_PROMPT, user_input, clean_final)
            # ========================================================

        finally:
            # 无论是因为死循环跳出、报错跳出、还是正常结束，只要能走到这里，绝对回滚记忆！
            # 保证下一轮对话的 Prompt 永远是干净的！
            if not self.scheduler.stop_event.is_set():
                self.memory.history = history_backup
                self.memory.add_message("user", user_input, tag=tag)

                # 提取最后一次生成的 response，清洗干净存进去
                if response:
                    clean_final = re.sub(r"\[\[.*?\]\]", "", response, flags=re.DOTALL).strip()
                    if clean_final:
                        self.memory.add_message("assistant", clean_final)
                        self.logger.log_interaction(settings.DEFAULT_SYSTEM_PROMPT, user_input, clean_final)

            # 只有当依然处于 THINKING 状态时 (没被打断)，才切换到 SPEAKING 等待躯壳读完
            if self.scheduler.current_state == GlobalState.THINKING:
                # 检查我这轮到底有没有说出真正的“人话”
                clean_for_speech = re.sub(r"\[\[.*?\]\]", "", response, flags=re.DOTALL).strip() if response else ""

                if clean_for_speech:
                    # 如果有话要说，才切换到 SPEAKING 等待躯壳读完
                    self.scheduler.change_state(GlobalState.SPEAKING)
                else:
                    # 如果只有动作或指令，直接切换回 IDLE，放开麦克风！
                    self.scheduler.change_state(GlobalState.IDLE)

    def _generate_and_print(self, context):
        """ 包装生成器，响应外部打断 """
        self.scheduler.reset_stop_event()  # 再次确保手刹松开
        full_response = ""
        streamer = self.engine.generate_stream(context, self.scheduler.stop_event)

        try:
            for new_text in streamer:
                # 严密监控：如果状态不再是 THINKING (被切成 INTERRUPTED 了)，立刻停止
                if self.scheduler.stop_event.is_set():
                    self.ui.system_log("🛑 [Interrupt] 生成流被截断", "warn")
                    return ""

                self.ui.output_text(new_text)
                full_response += new_text
        except Exception as e:
            self.ui.system_log(f"❌ [Generate Error] {e}", "error")
            return ""

        if not full_response: return ""
        self.ui.output_final(full_response)
        return full_response

    # --- 后台任务修复 ---
    def _heartbeat_loop(self):
        self.ui.system_log("💓 [Agent] 脑波监测进程已就绪...", "success")
        while self.running:
            time.sleep(1)

            # 必须是真正闲着才做事
            if self.scheduler.current_state != GlobalState.IDLE:
                continue

            current_time = time.time()

            # 间隔拉长到 300秒 (5分钟)，大幅减少冲突概率
            if current_time - self.last_vision_time > 300:
                self.scheduler.submit_task(TaskPriority.P3_BACKGROUND, "PassiveLook", self._passive_look_task)
                self.last_vision_time = current_time

            # 情绪搭话逻辑不变
            self.update_emotion("ignore")
            status = self.emotion.get_status()
            if status != "neutral":
                prob = 0.1 if status == "bored" else 0.2
                if random.random() < prob:
                    self.scheduler.submit_task(TaskPriority.P3_BACKGROUND, "ActiveSpeech", self._active_speech_task,
                                               status)

    def _passive_look_task(self):
        """ 后台原子级视觉采样 (做事时别吵吵) """
        # 1. 霸占状态：明明白白告诉系统我现在用着 GPU，别当我是闲人
        if not self.scheduler.change_state(GlobalState.EXECUTING_TOOL):
            return

        self.ui.system_log("🕵️ [Agent] 后台视觉采样 (占用大模型中，保持专注)...", "info")
        try:
            res = self.tool_manager.run_tool_direct("VISION", "简短描述屏幕上的内容")
            if res and "TIMEOUT" not in res and "打断" not in res:
                self.visual_summary = res
        except Exception:
            pass
        finally:
            self.last_vision_time = time.time()
            # 采图完成，通知躯壳解锁
            self.ui.output_action("vision_end")
            # 2. 状态交还：如果这期间用户插嘴了(状态变了)，就不要强行切回 IDLE，顺其自然
            if self.scheduler.current_state == GlobalState.EXECUTING_TOOL:
                self.scheduler.change_state(GlobalState.IDLE)

    def _active_speech_task(self, status):
        """ 发起主动抱怨 """
        if time.time() - self.emotion.last_interaction < 30: return
        if not self.scheduler.change_state(GlobalState.THINKING): return

        try:
            self.ui.output_action("emotion_change", {"status": status})
            prompt = f"系统提示：你现在处于 {status} 状态。请用一句话简短地向用户抱怨。"
            vision_hint = f"\n【即时观察：用户正在 {self.visual_summary}】"
            temp_input = [{"role": "system", "content": settings.DEFAULT_SYSTEM_PROMPT},
                          {"role": "user", "content": prompt + vision_hint}]

            self.ui.output_action("start_speaking", {"type": "active"})
            response = self._generate_and_print(temp_input)
            if response:
                self.memory.add_message("assistant", response)
                self.emotion.last_interaction = time.time()
        finally:
            if self.scheduler.current_state == GlobalState.THINKING:
                self.scheduler.change_state(GlobalState.SPEAKING)

    def _get_enhanced_context(self, hidden_instruction):
        context = [msg.copy() for msg in self.memory.get_full_context()]
        hints = []
        if hidden_instruction:
            hints.append(hidden_instruction)
        if self.visual_summary != "暂无观察记录":
            hints.append(f"\n【系统背景视觉：{self.visual_summary}】")

        # ==========================================
        # [Feature] 海马体潜意识回响 (Subconscious Recall)
        # 在发送给大模型前，截获用户的最新发言，
        # 并通过 ChromaDB 向量检索，将相关的长期记忆作为隐性 Prompt 悄悄注入上下文。
        # ==========================================
        last_user_msg = ""
        if context and context[-1]['role'] == 'user':
            # 提取用户最新说的一句话（去除前面的标签干扰）
            raw_content = context[-1]['content']
            # 简单剥离可能存在的 "🎤 [语音输入]" 前缀
            last_user_msg = raw_content.split("] ")[-1] if "] " in raw_content else raw_content

        if last_user_msg:
            past_memories = self.ltm.recall(last_user_msg)
            if past_memories:
                mem_str = "\n".join([f"- {m}" for m in past_memories])
                # 把记忆作为隐性提示塞给大模型
                hints.append(
                    f"【潜意识回响 (过去的记忆)】：\n{mem_str}\n(注：这是你以前记住的关于用户的信息。结合当前对话自然地使用它，别像机器人一样生硬地念出来。)")

        # 1. 注入当前环境信息
        hints.append(f"【系统环境】：用户当前正在看窗口 [{self.current_window}]。")
        if self.current_clipboard:
            hints.append(f"【剪贴板内容】：{self.current_clipboard}")

        # 2. [新增] 注入底层情绪状态，强行矫正大模型的语气！
        current_mood = self.emotion.get_status()
        hints.append(f"【生理警告】：你目前的底层情绪状态为 '{current_mood}'，请务必用这种情绪的语气来回复用户！")

        total_hint = "\n".join(hints)
        if total_hint and context and context[-1]['role'] == 'user':
            context[-1]['content'] = f"{total_hint}\n\n{context[-1]['content']}"
        return context

    def update_emotion(self, event_type, intensity=0.2):
        """ 情绪中枢代理：计算 PAD 并自动触发表情动作 """
        old_status = self.emotion.get_status()
        self.emotion.update(event_type, intensity)
        new_status = self.emotion.get_status()

        # [核心机制] 只要情绪阈值跨越了某个区间（比如从 neutral 变成 angry），立刻控制躯壳做表情！
        if old_status != new_status:
            self.ui.system_log(f"🎭 [Autonomic] 自主神经触发表情: {old_status} -> {new_status}", "warn")
            self.ui.output_action("emotion_change", {"status": new_status})

    def submit_image_chat(self, img_path, user_text="帮我看看这张图"):
        """
        [Command] 视觉直通注入 (Vision Direct Injection)
        用于处理如 `/img` 等终端直发图片的指令。
        它会绕过标准的多轮 ReAct 思考循环，直接强制挂起大模型，
        驱动底层 Qwen2-VL 视觉皮层进行原子化解析，并作为一段“强制记忆”塞回给语言中枢。
        """
        self.scheduler.submit_task(
            priority=TaskPriority.P1_USER_REQUEST,
            name="ImageInjection",
            func=self._process_uploaded_image,
            img_path=img_path,
            user_text=user_text
        )

    def _process_uploaded_image(self, img_path, user_text):
        """ 视觉直通处理逻辑：绕过 ReAct 循环，原子化处理图片后直接注入上下文 """
        import os
        from PIL import Image

        if not os.path.exists(img_path):
            self.ui.system_log(f"❌ [Vision] 找不到物理路径下的图像文件: {img_path}", "error")
            return

        # 1. 直接抢占 GPU 状态
        if not self.scheduler.change_state(GlobalState.EXECUTING_TOOL):
            return

        try:
            img = Image.open(img_path)
            self.ui.system_log(f"📸[Vision] 成功捕获物理图像 ({img.width}x{img.height})，正在解析...", "success")

            # 2. 直接原子化调用 Vision Tool！
            res = self.tool_manager.registry["VISION"].run("详细描述这张图片的内容，包括文字、风格、主体等", image=img,
                                                           stop_event=self.scheduler.stop_event)

            # 3. 将视觉结果包装成“一段记忆”，强行喂给日常的聊天循环
            observation = f"【系统提示：用户向你直接上传了一张本地图片】\n底层视觉皮层的分析结果如下：\n{res}\n\n用户附言：{user_text}"

            self.ui.system_log("🧠 [Vision] 解析完毕，图像记忆已注入神经中枢。", "info")

            # 4. 把包装好的信息扔进普通的对话处理流中！
            self.scheduler.change_state(GlobalState.THINKING, force=True)
            self._process_chat(observation, tag="image")

        except Exception as e:
            self.ui.system_log(f"❌ [Vision] 图像皮层处理崩溃: {e}", "error")
            self.scheduler.change_state(GlobalState.IDLE, force=True)