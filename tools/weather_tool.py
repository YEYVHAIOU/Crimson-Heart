# tools/weather_tool.py
import requests
from colorama import Fore, Style


class WeatherTool:
    def run(self, location=""):
        """ 使用绝对稳定的 Open-Meteo 气象卫星 """
        try:
            # 如果没提供城市，就用 IP 强行定位你的物理老巢
            if not location:
                print(Fore.CYAN + "🌩️ [Probe] 未指定地点，正在通过 IP 定位物理坐标..." + Style.RESET_ALL)
                try:
                    # [Security] 使用 HTTPS 协议的 ipapi 进行 IP 嗅探，防止明文劫持
                    ip_info = requests.get("https://ipapi.co/json/", timeout=5).json()
                    location = ip_info.get("city", "Beijing")  # 默认保底北京
                except:
                    location = "Beijing"
            else:
                print(Fore.CYAN + f"🌩️ [Probe] 正在解析 [{location}] 的地理坐标..." + Style.RESET_ALL)

            # 1. 将城市名转换为经纬度 (Geocoding)
            geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={location}&count=1&language=zh"
            geo_resp = requests.get(geo_url, timeout=5).json()

            if not geo_resp.get("results"):
                return f"【错误】气象卫星找不到名为 '{location}' 的坐标。"

            lat = geo_resp["results"][0]["latitude"]
            lon = geo_resp["results"][0]["longitude"]
            city_name = geo_resp["results"][0].get("name", location)

            print(Fore.CYAN + f"📡 [Probe] 坐标锁定 ({lat}, {lon})，拉取大气数据..." + Style.RESET_ALL)

            # 2. 读取气象数据
            weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
            w_resp = requests.get(weather_url, timeout=5).json()
            current = w_resp.get("current_weather", {})

            temp = current.get("temperature", "未知")
            wind = current.get("windspeed", "未知")

            # 简单映射天气代码
            code = current.get("weathercode", 0)
            weather_desc = "晴朗" if code <= 1 else "多云" if code <= 3 else "雾" if code <= 49 else "降水"

            return f"【物理世界气象情报】\n- 坐标点: {city_name}\n- 天气概况: {weather_desc}\n- 当前温度: {temp}°C\n- 表面风速: {wind} km/h"

        except Exception as e:
            return f"气象探针连接彻底断裂: {str(e)}"


# 测试
if __name__ == "__main__":
    tool = WeatherTool()
    print("--- 探测上海 ---")
    print(tool.run("Shanghai"))
    print("\n--- 探测本地IP ---")
    print(tool.run())