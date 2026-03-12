# config/__init__.py
import os

# 1. 动态获取项目根目录 (无论谁 clone 你的代码，放哪个盘都能算对)
# 因为 __file__ 是 config/__init__.py，所以 dirname 两次就到了 Crimson 根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 2. 拼接出缓存文件夹的绝对路径
DEFAULT_CACHE_DIR = os.path.join(PROJECT_ROOT, "hf_cache")

# 3. 注入环境变量 (如果用户系统的环境变量没配，就用我们算出来的默认值)
os.environ["HF_HOME"] = os.environ.get("HF_HOME", DEFAULT_CACHE_DIR)
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# 你可以先留着这句打印，核对一下是不是 "D:\Pycharm\Crimson\hf_cache"
print(f"🔧 [Config] 环境变量已注入 | HF_HOME: {os.environ['HF_HOME']}")