# tools/dispatcher.py
import re
from colorama import Fore, Style
from tools.search_engine import SearchTool
from tools.python_executor import PythonExecutor
from tools.vision_tool import VisionTool # 新引入
from tools.system_control import SystemController  # <--- 别漏了导入
from tools.weather_tool import WeatherTool
from threading import Event

class ToolManager:
    def __init__(self):
        # 注册中心：指令 -> 工具实例
        self.registry = {
            "SEARCH": SearchTool(max_results=3),
            "EXEC": PythonExecutor(), # 注册代码执行器
            "VISION": VisionTool(device="cpu"), #视觉工具
            "SYS": SystemController(),  # [新增] 注册 SYS 工具
            "WEATHER": WeatherTool()
        }
        self.snapshot_callback = None  # [新增] 截图回调
        self.stop_event = None  # [新增] 停止信号

    def set_snapshot_callback(self, func):
        self.snapshot_callback = func

    def set_stop_event(self, event: Event):
        """注入全局停止信号 """
        self.stop_event = event

    def detect_and_execute(self, text):
        """ 检测并执行工具，返回 (是否触发, 结果) """
        # 改进的正则：支持多行输入和空格容错
        pattern = r"\[\[([A-Z_]+):\s*(.*?)\]\]"
        matches = re.finditer(pattern, text, re.DOTALL)

        results = []
        triggered = False

        for match in matches:
            cmd = match.group(1)
            arg = match.group(2).strip()

            if cmd in self.registry:
                triggered = True
                print(Fore.YELLOW + f"🛠️ [Dispatcher] 激活工具: {cmd} -> {arg[:30]}..." + Style.RESET_ALL)
                try:
                    # ==========================================
                    # [机制] 视觉工具的特殊劫持 (Vision Tool Hijack)
                    # 视觉工具极其特殊，它依赖躯壳端 (Body) 物理摄像头的截图回传。
                    # 这里触发阻塞式的 snapshot_callback，让大模型在此安静挂起等待，
                    # 直到 Body 通过 WebSocket 把 Base64 图片传回来（或者超时被打断）。
                    # ==========================================
                    if cmd == "VISION":
                        # 1. 检查是否有远程回调 (Server模式)
                        target_image = None
                        if self.snapshot_callback:
                            print(Fore.MAGENTA + "📡 [Dispatcher] 调用远程视觉接口..." + Style.RESET_ALL)
                            # 这一步会阻塞，直到 Body 把图片发回来，或者超时
                            target_image = self.snapshot_callback()

                        # 2. 补充默认参数
                        if not arg: arg = "详细描述屏幕内容"

                        # 3. 传入图片给工具
                        # 注意：如果 target_image 是 None，VisionTool 内部会自动截取 Server 本机的屏
                        # [关键] 传入 stop_event
                        # 注意：如果之前有逻辑判断 image is None，这里要确保参数传递正确
                        res = self.registry[cmd].run(arg, image=target_image, stop_event=self.stop_event)

                    else:
                        # 其他工具 (SEARCH, EXEC) 照常运行
                        res = self.registry[cmd].run(arg)
                    # ==========================================

                    print(Fore.CYAN + f"🔍 [Tool Result] {res}" + Style.RESET_ALL)  # 新增

                    results.append(f"工具[{cmd}]返回：\n{res}")
                except Exception as e:
                    results.append(f"工具[{cmd}]执行异常: {str(e)}")
            else:
                results.append(f"错误：未知指令 {cmd}")

        if triggered:
            return True, "\n---\n".join(results)
        return False, None

    # [新增] 提供给 Agent 后台调用的接口
    def run_tool_direct(self, name, arg):
        """ 提供给 Agent 后台被动采样用的接口 """
        if name in self.registry:
            # 被动采样时，我们同样希望能用到远程图片
            # 所以逻辑是一样的
            target_image = None
            if name == "VISION" and self.snapshot_callback:
                target_image = self.snapshot_callback()

            # 这里的 run 方法签名必须支持 image 参数 (我们在 vision_tool.py 改过了)
            if name == "VISION":
                return self.registry[name].run(arg, image=target_image, stop_event=self.stop_event)
            else:
                return self.registry[name].run(arg)
        return None