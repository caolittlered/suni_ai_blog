"""
OpenClaw Gateway WebSocket 客户端
"""

import json
import asyncio
from typing import Optional, Callable, AsyncGenerator
import websockets
import yaml
import os

# 加载配置
CONFIG_PATH = os.getenv("SUNI_CONFIG", "./config.yaml")
with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)


class OpenClawClient:
    """OpenClaw Gateway WebSocket 客户端"""
    
    def __init__(
        self,
        gateway_url: str = None,
        token: str = None,
        session_key: str = None
    ):
        self.gateway_url = gateway_url or config['openclaw']['gateway_url']
        self.token = token or os.getenv("OPENCLAW_GATEWAY_TOKEN") or config['openclaw'].get('token', '')
        self.session_key = session_key
        self.ws = None
        self.request_id = 0
    
    async def connect(self):
        """建立 WebSocket 连接"""
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        
        self.ws = await websockets.connect(
            self.gateway_url,
            extra_headers=headers
        )
        print(f"[OpenClaw] 已连接到 Gateway: {self.gateway_url}")
    
    async def close(self):
        """关闭连接"""
        if self.ws:
            await self.ws.close()
            self.ws = None
    
    async def _send_request(self, method: str, params: dict = None) -> dict:
        """发送请求并等待响应"""
        if not self.ws:
            await self.connect()
        
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params or {}
        }
        
        await self.ws.send(json.dumps(request))
        
        # 等待响应
        while True:
            response = await self.ws.recv()
            data = json.loads(response)
            
            # 检查是否是我们请求的响应
            if data.get("id") == self.request_id:
                return data
            
            # 如果是事件（如 chat 消息），忽略继续等待
            if "method" in data:
                continue
    
    async def create_session(self, label: str = None) -> str:
        """创建新的会话
        
        Returns:
            session_key
        """
        params = {}
        if label:
            params["label"] = label
        
        response = await self._send_request("sessions.create", params)
        
        if "error" in response:
            raise Exception(f"创建会话失败: {response['error']}")
        
        self.session_key = response.get("result", {}).get("sessionKey")
        return self.session_key
    
    async def send_message(
        self,
        message: str,
        session_key: str = None,
        context: str = None
    ) -> dict:
        """发送消息到 OpenClaw
        
        Args:
            message: 用户消息
            session_key: 会话 key（不填则使用实例的 session_key）
            context: RAG 上下文（会附加到消息前面）
        
        Returns:
            响应结果，包含 runId
        """
        sk = session_key or self.session_key
        if not sk:
            raise ValueError("未指定 session_key")
        
        # 如果有上下文，附加到消息前面
        if context:
            message = f"{context}\n\n用户问题：{message}"
        
        params = {
            "sessionKey": sk,
            "message": message
        }
        
        response = await self._send_request("chat.send", params)
        
        if "error" in response:
            raise Exception(f"发送消息失败: {response['error']}")
        
        return response.get("result", {})
    
    async def stream_chat(
        self,
        message: str,
        session_key: str = None,
        context: str = None,
        on_event: Callable[[dict], None] = None
    ) -> AsyncGenerator[str, None]:
        """流式获取聊天响应
        
        Yields:
            助手回复的文本片段
        """
        sk = session_key or self.session_key
        if not sk:
            raise ValueError("未指定 session_key")
        
        if not self.ws:
            await self.connect()
        
        # 发送消息
        if context:
            message = f"{context}\n\n用户问题：{message}"
        
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": "chat.send",
            "params": {
                "sessionKey": sk,
                "message": message
            }
        }
        await self.ws.send(json.dumps(request))
        
        # 流式接收响应
        assistant_text = ""
        while True:
            response = await self.ws.recv()
            data = json.loads(response)
            
            # 聊天事件
            if data.get("method") == "chat":
                event = data.get("params", {})
                event_type = event.get("type")
                
                if event_type == "assistant" and "delta" in event:
                    # 文本增量
                    delta = event["delta"]
                    assistant_text += delta
                    yield delta
                
                elif event_type == "assistant" and "text" in event:
                    # 完整文本
                    assistant_text = event["text"]
                
                elif event_type == "done":
                    # 完成
                    break
            
            # 响应结果
            elif data.get("id") == self.request_id:
                if "error" in data:
                    raise Exception(f"聊天失败: {data['error']}")
                # 这是 chat.send 的 ack，继续等待 chat 事件
                continue
        
        return assistant_text
    
    async def get_history(self, session_key: str = None, limit: int = 50) -> list:
        """获取聊天历史"""
        sk = session_key or self.session_key
        if not sk:
            raise ValueError("未指定 session_key")
        
        params = {
            "sessionKey": sk,
            "limit": limit
        }
        
        response = await self._send_request("chat.history", params)
        
        if "error" in response:
            raise Exception(f"获取历史失败: {response['error']}")
        
        return response.get("result", {}).get("messages", [])


# 用户客户端缓存
_user_clients = {}


async def get_user_client(user_id: int, session_key: str = None) -> OpenClawClient:
    """获取用户的 OpenClaw 客户端"""
    key = f"{user_id}_{session_key}" if session_key else str(user_id)
    
    if key not in _user_clients:
        client = OpenClawClient(session_key=session_key)
        await client.connect()
        
        if not session_key:
            # 创建新会话
            await client.create_session(label=f"user_{user_id}")
        
        _user_clients[key] = client
    
    return _user_clients[key]