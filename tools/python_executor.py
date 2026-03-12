# tools/python_executor.py
import sys
import io
import contextlib
import traceback
import subprocess
from colorama import Fore, Style


class PythonExecutor:
    """
    [高危模块] 本地 Python 沙盒执行器
    允许 LLM 编写并动态执行 Python 代码。
    请注意：这里当前并未做严格的 Docker 沙盒隔离，仅做了基础的关键字过滤。
    这是赋予 Crimson "数字生命" 改变系统环境能力的核心，但也伴随着极大的安全风险。
    """

    def __init__(self):
        # 危险库黑名单 (虽然你是主人，但防一手总是好的)
        self.forbidden_modules = ["shutil.rmtree", "os.remove", "os.rmdir", "format_drives",
            "mkfs", "fdisk", "dd"]

    def run(self, code):
        """
        在本地环境中执行 Python 代码并捕获输出。
        警告：这是极其危险的功能。
        """
        print(Fore.MAGENTA + "🐍 [Executor] 正在执行代码..." + Style.RESET_ALL)
        # print(Fore.BLACK + Style.BRIGHT + code + Style.RESET_ALL) # 调试时可以开启

        # 1. 简单的安全检查
        for bad in self.forbidden_modules:
            if bad in code:
                return f"安全拦截：代码包含禁止操作 ({bad})"

        # 1. 危险关键词二次拦截
        dangerous_keywords = ["rmtree", "remove", "popen", "system", "truncate"]
        for kw in dangerous_keywords:
            if kw in code.lower():
                return f"【安全警告】操作包含高危指令 '{kw}'，已被系统底层拦截。\n请告诉用户你需要权限，不要擅自执行。"

        # 2. 捕获标准输出
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        try:
            with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
                # 创建一个受限的全局命名空间
                # 可以在这里预置一些变量，比如 `agent` 本身，让代码能控制 agent
                exec_globals = {
                    "__builtins__": __builtins__,
                    "subprocess": subprocess,
                    "print": print,
                    "os": __import__("os"),  # 常用库预导入
                    "sys": sys
                }

                # 执行代码
                exec(code, exec_globals)

            output = stdout_capture.getvalue()
            error = stderr_capture.getvalue()

            result = ""
            if output:
                result += f"【标准输出】:\n{output}\n"
            if error:
                result += f"【错误输出】:\n{error}\n"

            if not result:
                result = "[System] 代码执行成功（无屏幕输出）。"

            return result

        except Exception:
            # 捕获代码本身的报错
            tb = traceback.format_exc()
            return f"【运行时异常】:\n{tb}\n\n请检查你的代码逻辑（如路径是否存在、模块是否导入）。"


# 测试
if __name__ == "__main__":
    tool = PythonExecutor()
    print(tool.run("import os; print(os.getcwd())"))