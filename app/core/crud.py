from contextlib import asynccontextmanager
from typing import Any, Dict, Generic, List, NewType, Tuple, Type, TypeVar, Union

from pydantic import BaseModel
from tortoise.expressions import Q
from tortoise.models import Model
from tortoise.transactions import in_transaction

Total = NewType("Total", int)
ModelType = TypeVar("ModelType", bound=Model)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class CRUDBase(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    def __init__(self, model: Type[ModelType]):
        self.model = model

    async def get(self, id: int) -> ModelType:
        return await self.model.get(id=id)

    async def get_or_none(self, id: int) -> ModelType | None:
        return await self.model.filter(id=id).first()

    async def exists(self, **filters) -> bool:
        return await self.model.filter(**filters).exists()

    async def list(self, page: int, page_size: int, search: Q = Q(), order: list = []) -> Tuple[Total, List[ModelType]]:
        query = self.model.filter(search)
        return await query.count(), await query.offset((page - 1) * page_size).limit(page_size).order_by(*order)

    async def create(self, obj_in: CreateSchemaType) -> ModelType:
        if isinstance(obj_in, Dict):
            obj_dict = obj_in
        else:
            obj_dict = obj_in.model_dump()
        obj = self.model(**obj_dict)
        await obj.save()
        return obj

    async def bulk_create(self, objs_in: List[CreateSchemaType]) -> List[ModelType]:
        """批量创建，使用单事务保证原子性"""
        obj_dicts = [
            obj_in if isinstance(obj_in, Dict) else obj_in.model_dump()
            for obj_in in objs_in
        ]
        objs = [self.model(**d) for d in obj_dicts]
        async with in_transaction():
            await self.model.bulk_create(objs)
        return objs

    async def update(self, id: int, obj_in: Union[UpdateSchemaType, Dict[str, Any]]) -> ModelType:
        if isinstance(obj_in, Dict):
            obj_dict = obj_in
        else:
            obj_dict = obj_in.model_dump(exclude_unset=True, exclude={"id"})
        obj = await self.get(id=id)
        obj = obj.update_from_dict(obj_dict)
        await obj.save()
        return obj

    async def bulk_update(self, ids: List[int], updates: Dict[str, Any]) -> int:
        """批量更新指定 ID 的记录，返回更新行数"""
        return await self.model.filter(id__in=ids).update(**updates)

    async def remove(self, id: int) -> None:
        obj = await self.get(id=id)
        await obj.delete()

    async def bulk_remove(self, ids: List[int]) -> int:
        """批量硬删除，返回删除行数"""
        return await self.model.filter(id__in=ids).delete()

    async def soft_remove(self, id: int) -> None:
        """软删除（模型需有 is_deleted 字段）"""
        await self.model.filter(id=id).update(is_deleted=True)

    @asynccontextmanager
    async def transaction(self):
        """事务上下文管理器"""
        async with in_transaction():
            yield
