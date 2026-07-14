"""回收站相关 Schema"""
from enum import Enum
from pydantic import BaseModel


class RecycleBinType(str, Enum):
    site = "site"
    gmail = "gmail"
    account = "account"
    provider = "provider"


class RecycleBinQuery(BaseModel):
    type: RecycleBinType
    page: int = 1
    page_size: int = 10
    keyword: str = ""


class RecycleBinAction(BaseModel):
    type: RecycleBinType
    id: int


class RecycleBinEmpty(BaseModel):
    type: RecycleBinType
