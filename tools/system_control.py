# tools/system_control.py
import psutil
import datetime
import platform
import pyautogui


class SystemController:
    def __init__(self):
        self.os_name = platform.system()
        # [Note] 放弃了不稳定且容易报权限错误的 Windows COM 接口。
        # 改用 PyAutoGUI 进行纯物理按键宏模拟，稳定性大幅提升，宣告物理外挂就绪。
        print(f"🔧 [System] 初始化系统控制总线 (OS: {self.os_name} | 模式: 纯物理宏模拟)...")

    def run(self, raw_command: str):
        """ 解析并执行原子指令 """
        if not raw_command: return "错误：空指令"

        parts = raw_command.split("|")
        cmd = parts[0].strip().upper()
        param = parts[1].strip() if len(parts) > 1 else ""

        try:
            # ----------------------------------
            # 1. 基础系统信息
            # ----------------------------------
            if cmd == "TIME":
                return f"当前系统时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

            # ----------------------------------
            # 2. 音频控制 (物理按键模拟)
            # ----------------------------------
            elif cmd == "VOLUME_MUTE":
                pyautogui.press("volumemute")
                return "【系统反馈】已发送 物理静音/解除静音 按键。"

            elif cmd == "VOLUME_UP":
                # Windows 默认按一下音量键增减 2%
                try:
                    increase_percent = int(param) if param else 10
                except:
                    increase_percent = 10
                steps = max(1, increase_percent // 2)
                pyautogui.press(['volumeup'] * steps)
                return f"【系统反馈】已发送 音量增加 按键 (约 +{steps * 2}%)。"

            elif cmd == "VOLUME_DOWN":
                try:
                    decrease_percent = int(param) if param else 10
                except:
                    decrease_percent = 10
                steps = max(1, decrease_percent // 2)
                pyautogui.press(['volumedown'] * steps)
                return f"【系统反馈】已发送 音量减少 按键 (约 -{steps * 2}%)。"

            # ----------------------------------
            # 3. 进程管理 (依然保留)
            # ----------------------------------
            elif cmd == "PROCESS_LIST":
                procs = []
                for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
                    try:
                        procs.append(proc.info)
                    except:
                        pass

                procs.sort(key=lambda x: x['cpu_percent'] or 0, reverse=True)
                result = "Top 8 CPU 进程:\n"
                for p in procs[:8]:
                    result += f"- {p['name']} (PID: {p['pid']}) CPU: {p['cpu_percent']}%\n"
                return result.strip()

            elif cmd == "PROCESS_KILL":
                target = param.lower()
                if not target: return "错误：未指定进程名"

                killed_count = 0
                for proc in psutil.process_iter(['pid', 'name']):
                    try:
                        if target in proc.info['name'].lower():
                            proc.kill()
                            killed_count += 1
                    except:
                        continue

                if killed_count > 0:
                    return f"已尝试结束 {killed_count} 个包含 '{target}' 的进程。"
                else:
                    return f"未找到或无法结束包含 '{target}' 的进程。"

            elif cmd == "HARDWARE":
                cpu = psutil.cpu_percent(interval=0.5)
                ram = psutil.virtual_memory().percent

                # Windows 下读取温度极其困难，我们尽力而为，读不到就嘲讽
                try:
                    temps = psutil.sensors_temperatures()
                    if temps and 'coretemp' in temps:
                        temp_str = f"CPU温度: {temps['coretemp'][0].current}°C"
                    else:
                        temp_str = "CPU温度: 传感器被 Windows 屏蔽"
                except:
                    temp_str = "CPU温度: 探针读取失败"

                # 电池状态
                battery = getattr(psutil, "sensors_battery", lambda: None)()
                batt_str = f"电池: {battery.percent}%" if battery else "供电: 交流直连"

                return f"硬件机能状态:\n- CPU 负载: {cpu}%\n- 内存占用: {ram}%\n- {temp_str}\n- {batt_str}"

            else:
                return f"未知系统指令: {cmd}"

        except Exception as e:
            return f"系统控制异常: {str(e)}"


# 本地测试
if __name__ == "__main__":
    ctrl = SystemController()
    print("--- 测试开始 ---")
    print(ctrl.run("VOLUME_DOWN|10"))  # 测试降低 20% 音量 (会按 10 次 volumedown)
    print(ctrl.run("PROCESS_LIST"))
    print("--- 测试结束 ---")