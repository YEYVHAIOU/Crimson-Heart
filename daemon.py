# daemon.py
import sys
import threading
import asyncio
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QAction
from PyQt6.QtCore import pyqtSignal, QObject, Qt
import config

"""
======================================================================
[模块] Crimson 后台守护进程 (The Daemon)
======================================================================
Crimson 的静默运行模式，隐藏于系统托盘的“猩红之眼”。
- 实时监控：通过信号槽机制绑定调度器的状态变化，实时更新图标。
- 视觉直观化：通过不同颜色的托盘图标，让用户一眼看穿 AI 的当前思维状态。
- 安全保障：提供“强制唤醒”与“一键切断”的高危操作接口，防止 AI 逻辑死循环。
======================================================================
"""
from core.agent import CrimsonAgent
from core.scheduler import GlobalState
from main import LocalAdvancedUI, local_snapshot_callback
from colorama import init, Fore, Style

init(autoreset=True)


class StateSignal(QObject):
    """[机制] 跨线程信号发射器：负责将 Agent 后台线程的状态同步至 GUI 主线程"""
    state_changed = pyqtSignal(GlobalState)


class CrimsonDaemon(QApplication):
    def __init__(self, sys_argv):
        super().__init__(sys_argv)
        self.setQuitOnLastWindowClosed(False)

        print(Fore.RED + "👁️ [Daemon] 正在唤醒猩红之眼，进入守护模式..." + Style.RESET_ALL)

        # 1. 托盘初始化
        self.tray_icon = QSystemTrayIcon(self)
        self.set_eye_color(QColor(0, 255, 0))

        # 2. 托盘右键菜单
        menu = QMenu()
        wake_action = QAction("强制唤醒 (打断)", self)
        wake_action.triggered.connect(self.force_wake)
        menu.addAction(wake_action)

        quit_action = QAction("切断供电 (退出)", self)
        quit_action.triggered.connect(self.quit_daemon)
        menu.addAction(quit_action)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.show()

        # 3. 异步状态映射
        self.signaler = StateSignal()
        self.signaler.state_changed.connect(self.update_tray_icon)

        # 4. 后台启动 Crimson 内核
        self.agent_thread = threading.Thread(target=self.boot_crimson_core, daemon=True)
        self.agent_thread.start()

    def set_eye_color(self, color: QColor):
        """ [UI] 动态绘制状态指示灯 """
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(4, 4, 56, 56)
        painter.end()
        self.tray_icon.setIcon(QIcon(pixmap))

    def update_tray_icon(self, state: GlobalState):
        """ [Logic] 根据调度器状态映射眼睛颜色 """
        if state == GlobalState.IDLE:
            self.set_eye_color(QColor(0, 255, 0))  # 绿：待命
            self.tray_icon.setToolTip("Crimson: 待命状态")
        elif state == GlobalState.LISTENING:
            self.set_eye_color(QColor(255, 0, 0))  # 红：监听中
            self.tray_icon.setToolTip("Crimson: 正在聆听...")
        elif state in [GlobalState.THINKING, GlobalState.EXECUTING_TOOL]:
            self.set_eye_color(QColor(255, 200, 0))  # 黄：推理中
            self.tray_icon.setToolTip("Crimson: 大脑高速运转中...")
        elif state == GlobalState.SPEAKING:
            self.set_eye_color(QColor(0, 150, 255))  # 蓝：播报中
            self.tray_icon.setToolTip("Crimson: 正在回复...")

    def force_wake(self):
        """ [P0级操作] 强制介入打断，防止程序陷入死锁 """
        if hasattr(self, 'agent'):
            self.agent.scheduler.trigger_interrupt("User Manual Wake")

    def quit_daemon(self):
        print(Fore.RED + "👋 [Daemon] 切断供电，猩红之眼闭合。" + Style.RESET_ALL)
        self.quit()

    def boot_crimson_core(self):
        """ [核心] 启动守护线程，挂载全部感知神经与任务队列 """
        try:
            local_ui = LocalAdvancedUI(mode="voice")
            self.agent = CrimsonAgent(ui=local_ui)
            local_ui.agent = self.agent
            self.agent.tool_manager.set_snapshot_callback(local_snapshot_callback)

            # [事件绑定] 将调度器状态变化映射到 GUI 信号
            self.agent.scheduler.add_state_listener(lambda s: self.signaler.state_changed.emit(s))

            self.agent.scheduler.change_state(GlobalState.IDLE, force=True)

            from senses.listener import Ear
            ear = Ear(model_size="medium", device="cpu", compute_type="int8")
            local_ui.ear = ear

            def on_voice_detected():
                self.agent.scheduler.trigger_interrupt("Daemon Barge-in")
                local_ui.interrupt()

            print(Fore.GREEN + "🟢 [Daemon] 听觉神经已挂载，后台静默运行中..." + Style.RESET_ALL)

            # 录音死循环
            while True:
                user_text = ear.listen_continuous(state_callback=on_voice_detected)
                if user_text and len(user_text) > 1:
                    print(Fore.BLUE + f"🎤 [Mic]: {user_text}" + Style.RESET_ALL)
                    self.agent.scheduler.reset_stop_event()
                    self.agent.scheduler.change_state(GlobalState.TRANSCRIBING, force=True)

                    voice_instr = "【系统提示：语音模式。简短、傲娇。】"
                    self.agent.submit_chat(user_text, hidden_instruction=voice_instr, tag="voice")
                else:
                    if self.agent.scheduler.current_state in [GlobalState.LISTENING, GlobalState.INTERRUPTED]:
                        self.agent.scheduler.reset_stop_event()
                        self.agent.scheduler.change_state(GlobalState.IDLE, force=True)
        except Exception as e:
            print(Fore.RED + f"❌ [Daemon Core Error] 神经中枢崩溃: {e}" + Style.RESET_ALL)


if __name__ == "__main__":
    app = CrimsonDaemon(sys.argv)
    sys.exit(app.exec())