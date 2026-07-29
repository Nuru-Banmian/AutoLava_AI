from pydantic import BaseModel


class AgentSettingsPatch(BaseModel):
    enabled: bool
