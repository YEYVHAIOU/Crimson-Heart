# tools/search_engine.py
from ddgs import DDGS

class SearchTool:
    def __init__(self, max_results=3):
        self.max_results = max_results

    def run(self, query):
        print(f"🔍 [Tool] 正在检索互联网: {query} ...")
        results = []
        try:
            with DDGS() as ddgs:
                #增加异常捕获，防止网络波动导致崩溃
                ddgs_gen = ddgs.text(query, region='cn-zh', timelimit='y', max_results=self.max_results)
                if ddgs_gen:
                    for r in ddgs_gen:
                        results.append(f"标题: {r['title']}\n链接: {r['href']}\n摘要: {r['body']}")
        except Exception as e:
            return f"搜索出错: {str(e)}"

        if not results:
            return "未找到相关结果。"

        return "\n\n".join(results)