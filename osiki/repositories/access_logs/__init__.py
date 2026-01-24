from osiki.repositories.access_logs.base_access_log_repository import (
    BaseAccessLogRepository,
)
from osiki.repositories.access_logs.mongodb_access_log_repository import (
    MongoDBAccessLogRepository,
)

__all__ = ["BaseAccessLogRepository", "MongoDBAccessLogRepository"]
