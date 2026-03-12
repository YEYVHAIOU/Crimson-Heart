# tools/vts_adapter.py
import pyvts
import asyncio
import os
from colorama import Fore, Style
import config

class VTSController:
    def __init__(self, port=8001):
        self.port = port
        self.plugin_info = {
            "plugin_name": "Crimson Agent",
            "developer": "The Inheritor",
            "authentication_token_path": os.path.join(config.PROJECT_ROOT, "token.txt")
        }
        self.vts = pyvts.vts(plugin_info=self.plugin_info)
        self.connected = False

    async def connect(self):
        """ 健壮的连接逻辑：自动处理 Token 失效 """
        print(Fore.MAGENTA + "🎭 [VTS] 正在连接皮套..." + Style.RESET_ALL)
        try:
            await self.vts.connect()

            # 尝试验证现有 Token
            try:
                await self.vts.request_authenticate()
                self.connected = True
                print(Fore.GREEN + "✅ [VTS] 鉴权成功，皮套已链接！" + Style.RESET_ALL)
            except Exception:
                # 如果鉴权失败（Token 过期或文件损坏），则重新申请
                print(Fore.YELLOW + "⚠️ [VTS] 鉴权失败，正在尝试重新申请 Token..." + Style.RESET_ALL)
                await self._re_authenticate()

        except ConnectionRefusedError:
            print(
                Fore.RED + "❌ [VTS] 连接被拒绝。请确保 VTube Studio 已打开且插件 API 已开启 (端口 8001)。" + Style.RESET_ALL)
            self.connected = False
        except Exception as e:
            print(Fore.RED + f"❌ [VTS] 未知错误: {e}" + Style.RESET_ALL)
            self.connected = False

    async def _re_authenticate(self):
        """ 重新申请流程 """
        # 1. 删除旧 Token 文件 (如果有)
        token_path = os.path.join(config.PROJECT_ROOT, "token.txt")
        if os.path.exists(token_path):
            os.remove(token_path)

        # 2. 请求新 Token
        print(Fore.YELLOW + "🔔 [VTS] 请在 VTube Studio 弹窗中点击 'Allow'..." + Style.RESET_ALL)
        try:
            await self.vts.request_authenticate_token()
            await self.vts.request_authenticate()
            await self.vts.write_token()  # 写入新 Token
            self.connected = True
            print(Fore.GREEN + "✅ [VTS] 新 Token 获取成功并已保存！" + Style.RESET_ALL)
        except Exception as e:
            print(Fore.RED + f"❌ [VTS] Token 申请失败: {e}" + Style.RESET_ALL)

    async def trigger_hotkey(self, hotkey_name):
        """ 触发表情热键 """
        if not self.connected: return
        try:
            # 这里的 hotkey_name 必须和你在 VTS 里设置的一模一样 (不区分大小写)
            await self.vts.request(self.vts.vts_request.requestTriggerHotKey(hotkey_name))
            print(Fore.MAGENTA + f"🎭 [VTS Action] 触发表情: {hotkey_name}" + Style.RESET_ALL)
        except Exception as e:
            print(Fore.RED + f"⚠️ [VTS] 热键触发失败: {e}" + Style.RESET_ALL)

    async def close(self):
        await self.vts.close()