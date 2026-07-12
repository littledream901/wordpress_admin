from app.core.crud import CRUDBase
from app.models.config import Config
from app.schemas.config import ConfigCreate, ConfigUpdate


class ConfigController(CRUDBase[Config, ConfigCreate, ConfigUpdate]):
    def __init__(self):
        super().__init__(model=Config)

    async def get_by_name(self, name: str) -> Config | None:
        return await self.model.filter(name=name).first()

    async def get_by_category(self, category: str):
        return await self.model.filter(category=category).order_by('sort_order').all()

    async def get_categories(self) -> list[str]:
        rows = await self.model.all().distinct().values_list('category', flat=True)
        return list(dict.fromkeys(rows))


config_controller = ConfigController()
