# memory/long_term.py
import os
import chromadb
from chromadb.utils import embedding_functions
from colorama import Fore, Style
import time


class LongTermMemory:
    def __init__(self, db_path="data/chroma_db"):
        print(Fore.CYAN + "🧠 [Hippocampus] 正在唤醒长期记忆中枢 (ChromaDB)..." + Style.RESET_ALL)
        os.makedirs(db_path, exist_ok=True)

        # 挂载本地持久化数据库
        self.client = chromadb.PersistentClient(path=db_path)

        # 使用轻量级多语言句向量模型，完美支持中文语义检索
        self.ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="paraphrase-multilingual-MiniLM-L12-v2"
        )

        self.collection = self.client.get_or_create_collection(
            name="crimson_core_memory",
            embedding_function=self.ef
        )
        print(
            Fore.GREEN + f"✅ [Hippocampus] 记忆库挂载成功，当前沉淀记忆: {self.collection.count()} 条。" + Style.RESET_ALL)

    def memorize(self, text: str):
        """ 主动刻录：将重要情报刻入长期记忆 """
        doc_id = f"mem_{int(time.time() * 1000)}"
        self.collection.add(
            documents=[text],
            ids=[doc_id],
            metadatas=[{"timestamp": time.time()}]
        )
        return True

    def recall(self, query: str, n_results=2):
        """ 潜意识回响：根据当前对话唤起最相关的记忆 """
        if self.collection.count() == 0:
            return []

        results = self.collection.query(
            query_texts=[query],
            n_results=min(n_results, self.collection.count())
        )

        if results and results['documents'] and results['documents'][0]:
            return results['documents'][0]
        return []