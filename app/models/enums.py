from enum import Enum, IntEnum, StrEnum


class EnumBase(Enum):
    @classmethod
    def get_member_values(cls):
        return [item.value for item in cls._member_map_.values()]

    @classmethod
    def get_member_names(cls):
        return [name for name in cls._member_names_]


class MethodType(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


class DataScope(IntEnum):
    """数据权限范围"""
    ALL = 0              # 全部数据权限
    DEPT_AND_CHILD = 1   # 本部门及以下数据
    DEPT_ONLY = 2        # 仅本部门数据
    SELF_ONLY = 3        # 仅本人数据
    CUSTOM = 4           # 自定义部门
