# core/scheduler.py
import threading
import queue
import time
from enum import Enum, IntEnum
from dataclasses import dataclass, field
from typing import Callable
from colorama import Fore, Style


# ==========================================
# 1. 状态定义与转移矩阵 (State Machine)
#
# [设计哲学] 为什么需要这个状态机？
# 因为全双工多模态系统面临极高的并发冲突风险（例如：AI正在说话时，用户突然插嘴打断；
# AI正在截图时，环境音触发了录音）。
# 本状态机通过严格的 DAG (有向无环图) 转移矩阵，确保麦克风、GPU大模型、TTS音频队列
# 三者之间绝对的互斥与安全切断。
# ==========================================
class GlobalState(Enum):
    OFFLINE = "OFFLINE"  # 躯壳未连接/断开
    IDLE = "IDLE"  # 绝对空闲，允许系统主动思考
    LISTENING = "LISTENING"  # 麦克风正在捕捉音频
    TRANSCRIBING = "TRANSCRIBING"  # 录音完毕，Whisper 转录中
    THINKING = "THINKING"  # 大模型正在推理生成
    EXECUTING_TOOL = "EXECUTING_TOOL"  # 大模型挂起，等待工具回调(如截图)
    SPEAKING = "SPEAKING"  # 躯壳正在播报TTS
    INTERRUPTED = "INTERRUPTED"  # [瞬态] 被强行打断，用于清理内存


# 定义合法的状态转移路径 (DAG有向图)
VALID_TRANSITIONS = {
    GlobalState.OFFLINE: {GlobalState.IDLE},
    GlobalState.IDLE: {GlobalState.LISTENING, GlobalState.THINKING,  GlobalState.EXECUTING_TOOL, GlobalState.OFFLINE},
    GlobalState.LISTENING: {GlobalState.TRANSCRIBING, GlobalState.IDLE, GlobalState.INTERRUPTED, GlobalState.OFFLINE},
    GlobalState.TRANSCRIBING: {GlobalState.THINKING, GlobalState.LISTENING, GlobalState.INTERRUPTED,
                               GlobalState.OFFLINE},
    GlobalState.THINKING: {GlobalState.SPEAKING, GlobalState.EXECUTING_TOOL, GlobalState.INTERRUPTED,
                           GlobalState.OFFLINE},
    GlobalState.EXECUTING_TOOL: {GlobalState.THINKING, GlobalState.IDLE, GlobalState.INTERRUPTED, GlobalState.OFFLINE},
    GlobalState.SPEAKING: {GlobalState.IDLE, GlobalState.LISTENING, GlobalState.INTERRUPTED, GlobalState.OFFLINE},
    GlobalState.INTERRUPTED: {GlobalState.LISTENING, GlobalState.IDLE, GlobalState.OFFLINE}
}


# ==========================================
# 2. 优先级定义与任务封装 (Task Management)
# ==========================================
class TaskPriority(IntEnum):
    P0_SYSTEM_INTERRUPT = 0  # 最高级：掉线清理、紧急刹车
    P1_USER_REQUEST = 1  # 高级：用户聊天文本、唤醒指令
    P2_SYSTEM_CALLBACK = 2  # 中级：工具执行完毕的数据回调 (如视觉截图回传)
    P3_BACKGROUND = 3  # 低级：主动搭话、后台视觉采样 (可被丢弃)


@dataclass(order=True)
class Task:
    priority: TaskPriority
    timestamp: float
    name: str = field(compare=False)
    func: Callable = field(compare=False)
    args: tuple = field(compare=False, default_factory=tuple)
    kwargs: dict = field(compare=False, default_factory=dict)


# ==========================================
# 3. 核心调度器 (Bulletproof Scheduler)
# ==========================================
class TaskScheduler:
    """
    Crimson 的中央状态机与并发调度器 (Bulletproof Scheduler)。

    采用严密的 DAG (有向无环图) 状态转移矩阵，确保系统的：
    - 麦克风收音 (LISTENING)
    - 大模型推理 (THINKING)
    - 语音播报 (SPEAKING)
    三者之间绝对互斥。

    内置 `stop_event` 全局手刹机制，支持毫秒级的用户中断 (Barge-in) 响应。
    """

    def __init__(self):
        self._state_lock = threading.Lock()
        self._current_state = GlobalState.OFFLINE  # 初始状态为离线

        # 优先级队列，保证高优先级任务优先出队
        self.task_queue = queue.PriorityQueue()

        # 全局神经刹车：Event 触发时，大模型和工具必须立即停止
        self.stop_event = threading.Event()

        self._state_callbacks = []
        self.stop_signal = False

        # 启动唯一的后台消费者线程，保证所有逻辑串行，避免多线程数据竞争
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="Crimson_Worker")
        self.worker_thread.start()

    @property
    def current_state(self):
        with self._state_lock:
            return self._current_state

    # --- 状态流转控制 ---
    def change_state(self, new_state: GlobalState, force=False):
        """
        严密的状态切换机制。
        force=True 时忽略合法性检查 (通常用于 P0 级别的崩溃和中断恢复)
        """
        with self._state_lock:
            if self._current_state == new_state:
                return True

            if not force and new_state not in VALID_TRANSITIONS[self._current_state]:
                print(
                    Fore.RED + f"⚠️ [Scheduler] 拒绝非法状态跳跃: {self._current_state.name} -> {new_state.name}" + Style.RESET_ALL)
                return False

            # 状态颜色日志输出
            color = Fore.WHITE
            if new_state == GlobalState.LISTENING:
                color = Fore.GREEN
            elif new_state == GlobalState.THINKING:
                color = Fore.YELLOW
            elif new_state == GlobalState.SPEAKING:
                color = Fore.CYAN
            elif new_state in (GlobalState.INTERRUPTED, GlobalState.OFFLINE):
                color = Fore.RED
            elif new_state == GlobalState.EXECUTING_TOOL:
                color = Fore.MAGENTA

            print(color + f"🔄 [State] {self._current_state.name} -> {new_state.name}" + Style.RESET_ALL)

            self._current_state = new_state

        # 释放锁后通知监听器，防止在回调中引发死锁
        self._notify_listeners(new_state)
        return True

    def add_state_listener(self, callback: Callable):
        self._state_callbacks.append(callback)

    def _notify_listeners(self, new_state: GlobalState):
        for cb in self._state_callbacks:
            try:
                cb(new_state)
            except Exception as e:
                print(Fore.RED + f"❌ [Scheduler] Callback Error: {e}" + Style.RESET_ALL)

    # --- 任务提交与清空 ---
    def submit_task(self, priority: TaskPriority, name: str, func: Callable, *args, **kwargs):
        """ 外部向调度器提交任务的唯一入口 """
        # [防堆积优化] 如果是低优先级的后台闲聊/观察任务，但系统不在 IDLE，直接丢弃
        if priority == TaskPriority.P3_BACKGROUND and self.current_state != GlobalState.IDLE:
            # print(Fore.BLACK + Style.BRIGHT + f"🗑️ [Scheduler] 系统忙碌，丢弃后台任务: {name}" + Style.RESET_ALL)
            return

        task = Task(priority=priority, timestamp=time.time(), name=name, func=func, args=args, kwargs=kwargs)
        self.task_queue.put(task)

    def clear_pending_tasks(self, keep_p0=True):
        """ 清空积压的任务 (通常在被打断或掉线时调用) """
        with self.task_queue.mutex:
            if not keep_p0:
                self.task_queue.queue.clear()
            else:
                # 过滤出 P0 任务保留，其他的扔掉
                retained = [t for t in self.task_queue.queue if t.priority == TaskPriority.P0_SYSTEM_INTERRUPT]
                self.task_queue.queue.clear()
                self.task_queue.queue.extend(retained)
        print(Fore.YELLOW + "🧹 [Scheduler] 任务队列已清理。" + Style.RESET_ALL)

    # --- 核心机制：紧急刹车 (Barge-in / OOB Signal) ---
    def trigger_interrupt(self, reason="User Barge-in"):
        """
        [P0级操作] 带外信号触发。不排队，直接强行改变状态并拉起手刹。
        """
        print(Fore.RED + f"🛑 [Interrupt] 收到系统级中断信号: {reason}" + Style.RESET_ALL)

        # 1. 设置刹车标志，正在运行的 LLM 或 工具 内部检测到此标志必须立即 return
        self.stop_event.set()

        # 2. 清理积压的普通任务
        self.clear_pending_tasks(keep_p0=True)

        # 3. 强行切入 INTERRUPTED 瞬态，然后再切入 LISTENING
        self.change_state(GlobalState.INTERRUPTED, force=True)
        self.change_state(GlobalState.LISTENING, force=True)

    def reset_stop_event(self):
        """ 解除手刹 (通常在下一次 LLM 推理开始前调用) """
        if self.stop_event.is_set():
            self.stop_event.clear()

    # --- Worker 消费者线程 ---
    def _worker_loop(self):
        """ 调度器的唯一执行体，杜绝多线程竞争 """
        while not self.stop_signal:
            try:
                # 阻塞获取任务，超时设为0.5秒以便能够响应 stop_signal
                task: Task = self.task_queue.get(timeout=0.5)

                # [二次校验] 取出 P3 任务时如果状态已经不是 IDLE，再次丢弃
                if task.priority == TaskPriority.P3_BACKGROUND and self.current_state != GlobalState.IDLE:
                    self.task_queue.task_done()
                    continue

                # 执行任务
                try:
                    task.func(*task.args, **task.kwargs)
                except Exception as e:
                    print(Fore.RED + f"❌ [Scheduler Worker] 执行任务 '{task.name}' 时崩溃: {e}" + Style.RESET_ALL)
                finally:
                    self.task_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                print(Fore.RED + f"❌ [Scheduler Worker] 严重调度错误: {e}" + Style.RESET_ALL)