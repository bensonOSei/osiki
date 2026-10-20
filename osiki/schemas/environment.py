from pydantic import BaseModel


class BootstrapRead(BaseModel):
    team_manage_permission_id: str
    owner_role_id: str
