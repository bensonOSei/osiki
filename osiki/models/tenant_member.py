from beanie import Document
from pymongo import IndexModel

from osiki.models.base import EnvironmentMixin, TimestampMixin


class TenantMember(Document, EnvironmentMixin, TimestampMixin):
    tenant_id: str
    user_id: str

    class Settings:
        name = "tenant_members"
        indexes = [
            IndexModel(
                [("environment_id", 1), ("tenant_id", 1), ("user_id", 1)], unique=True
            ),
            IndexModel([("environment_id", 1), ("user_id", 1)]),
        ]
