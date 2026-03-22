"""
RAG 引擎 - 基于 claw_with_rag
"""

import os
import hashlib
from typing import List, Optional
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

import chromadb
from chromadb.config import Settings
import yaml


class RAGEngine:
    """RAG 检索引擎"""
    
    def __init__(self, config_path: str = "./config.yaml", user_id: int = None):
        """初始化 RAG 引擎
        
        Args:
            config_path: 配置文件路径
            user_id: 用户ID，用于创建独立的 collection
        """
        self.config = self._load_config(config_path)
        self.user_id = user_id
        
        # 配置 HuggingFace 镜像
        hf_endpoint = self.config.get('rag', {}).get('hf_endpoint')
        if hf_endpoint:
            os.environ['HF_ENDPOINT'] = hf_endpoint
        
        self.embeddings = self._init_embeddings()
        self.reranker = None
        self.vectorstore = None
        self.collection_name = f"user_{user_id}_kb" if user_id else "default_kb"
        
    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _init_embeddings(self) -> HuggingFaceEmbeddings:
        """初始化 Embedding 模型"""
        embedding_config = self.config['rag']['embedding']
        model_name = embedding_config['model']
        device = embedding_config.get('device', 'cpu')
        
        print(f"[RAG] 加载 Embedding 模型: {model_name}")
        return HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={'device': device},
            encode_kwargs={'normalize_embeddings': True}
        )
    
    def _init_reranker(self):
        """初始化 Reranker 模型（延迟加载）"""
        if self.reranker is not None:
            return
        
        from sentence_transformers import CrossEncoder
        reranker_config = self.config['rag']['reranker']
        model_name = reranker_config['model']
        
        print(f"[RAG] 加载 Reranker 模型: {model_name}")
        self.reranker = CrossEncoder(
            model_name,
            max_length=512,
            device=reranker_config.get('device', 'cpu')
        )
    
    def init_vectorstore(self):
        """初始化向量数据库"""
        db_config = self.config['rag']['vector_db']
        persist_dir = db_config.get('persist_directory', './data/chroma')
        os.makedirs(persist_dir, exist_ok=True)
        
        client = chromadb.PersistentClient(path=persist_dir)
        
        self.vectorstore = Chroma(
            client=client,
            embedding_function=self.embeddings,
            collection_name=self.collection_name
        )
        print(f"[RAG] 向量数据库初始化完成: {self.collection_name}")
    
    def _get_text_splitter(self) -> RecursiveCharacterTextSplitter:
        """获取文本切分器"""
        chunking_config = self.config['rag']['chunking']
        return RecursiveCharacterTextSplitter(
            chunk_size=chunking_config['chunk_size'],
            chunk_overlap=chunking_config['chunk_overlap'],
            length_function=len,
            separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]
        )
    
    def index_documents(self, documents: List[Document]) -> int:
        """索引文档
        
        Returns:
            索引的文档片段数量
        """
        if not self.vectorstore:
            self.init_vectorstore()
        
        text_splitter = self._get_text_splitter()
        split_docs = text_splitter.split_documents(documents)
        
        # 用内容 hash 去重
        ids = []
        for doc in split_docs:
            source = doc.metadata.get('source', '')
            content_hash = hashlib.md5(f"{source}:{doc.page_content}".encode()).hexdigest()
            ids.append(content_hash)
        
        print(f"[RAG] 正在索引 {len(split_docs)} 个文档片段...")
        self.vectorstore.add_documents(split_docs, ids=ids)
        print(f"[RAG] 索引完成！")
        
        return len(split_docs)
    
    def retrieve_with_rerank(self, query: str, top_k: Optional[int] = None) -> List[dict]:
        """检索并重排序"""
        if not self.vectorstore:
            self.init_vectorstore()
        
        retrieval_config = self.config['rag']['retrieval']
        top_k = top_k or retrieval_config['top_k']
        rerank_top_k = retrieval_config['rerank_top_k']
        
        # 初始检索
        docs = self.vectorstore.similarity_search(query, k=top_k)
        
        if not docs:
            return []
        
        # 加载 reranker
        self._init_reranker()
        
        # 重排序
        pairs = [[query, doc.page_content] for doc in docs]
        scores = self.reranker.predict(pairs)
        
        # 组合并排序
        scored_docs = list(zip(docs, scores))
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        
        # 过滤低分结果
        threshold = retrieval_config['similarity_threshold']
        results = []
        for doc, score in scored_docs[:rerank_top_k]:
            if score >= threshold:
                results.append({
                    'content': doc.page_content,
                    'metadata': doc.metadata,
                    'score': float(score)
                })
        
        return results
    
    def build_context(self, query: str) -> str:
        """构建 RAG 上下文（用于 LLM 输入）"""
        results = self.retrieve_with_rerank(query)
        
        if not results:
            return ""
        
        context_parts = ["以下是相关的企业内部知识：\n"]
        for i, result in enumerate(results, 1):
            context_parts.append(f"[文档{i}] (相关度: {result['score']:.2f})")
            context_parts.append(result['content'])
            context_parts.append("")
        
        return "\n".join(context_parts)


# 全局 RAG 引擎缓存
_rag_engines = {}


def get_rag_engine(user_id: int) -> RAGEngine:
    """获取用户的 RAG 引擎"""
    if user_id not in _rag_engines:
        _rag_engines[user_id] = RAGEngine(config_path="./config.yaml", user_id=user_id)
    return _rag_engines[user_id]