from pydantic import BaseModel, ConfigDict, Field


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
