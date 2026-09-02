import datetime as dt

from pydantic import BaseModel


class AdminActionResponse(BaseModel):
    id: str
    admin_id: str
    action_type: str
    target_type: str
    target_id: str
    payload: dict
    created_at: dt.datetime


class ListAdminActionsResponse(BaseModel):
    items: list[AdminActionResponse]
