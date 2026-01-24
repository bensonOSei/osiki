from loguru import logger

from osiki.models.access_log import AccessLog
from osiki.repositories.access_logs.base_access_log_repository import (
    BaseAccessLogRepository,
)


class MongoDBAccessLogRepository(BaseAccessLogRepository):
    async def create(self, access_log: AccessLog) -> AccessLog:
        await access_log.insert()
        logger.debug(
            "Access log created",
            access_log_id=str(access_log.id),
            user_id=access_log.user_id,
            resource=access_log.resource,
            action=access_log.action,
            allowed=access_log.allowed,
        )
        return access_log

    async def get_by_user(
        self, user_id: str, skip: int = 0, limit: int = 100
    ) -> list[AccessLog]:
        return (
            await AccessLog.find(AccessLog.user_id == user_id)
            .sort("-timestamp")
            .skip(skip)
            .limit(limit)
            .to_list()
        )

    async def get_denials(self, skip: int = 0, limit: int = 100) -> list[AccessLog]:
        return (
            await AccessLog.find(AccessLog.allowed == False)
            .sort("-timestamp")
            .skip(skip)
            .limit(limit)
            .to_list()
        )

    async def get_by_resource(
        self,
        resource: str,
        action: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AccessLog]:
        if action:
            query = AccessLog.find(
                AccessLog.resource == resource, AccessLog.action == action
            )
        else:
            query = AccessLog.find(AccessLog.resource == resource)
        return await query.sort("-timestamp").skip(skip).limit(limit).to_list()

    async def get_recent(self, skip: int = 0, limit: int = 100) -> list[AccessLog]:
        return (
            await AccessLog.find_all()
            .sort("-timestamp")
            .skip(skip)
            .limit(limit)
            .to_list()
        )
