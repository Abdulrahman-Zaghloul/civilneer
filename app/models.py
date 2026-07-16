from pydantic import BaseModel


class Issue(BaseModel):
    issue: str
    severity: str
    category: str
    reason: str
    suggested_fix: str
