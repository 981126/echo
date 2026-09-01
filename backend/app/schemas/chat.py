"""AI 对话接口契约。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ChatIn(BaseModel):
    message: str


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    created_at: datetime


class ChatOut(BaseModel):
    reply: str
    message_id: int
