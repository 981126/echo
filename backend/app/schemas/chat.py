"""AI 对话接口契约（R-017 多会话 + 流式）。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ChatIn(BaseModel):
    message: str
    conversation_id: Optional[int] = None


class ChatStreamIn(BaseModel):
    conversation_id: Optional[int] = None
    message: str


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: Optional[int] = None
    role: str
    content: str
    created_at: datetime


class ChatOut(BaseModel):
    reply: str
    message_id: int


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationCreate(BaseModel):
    title: str = "新对话"


class ConversationUpdate(BaseModel):
    title: str
