from pydantic import BaseModel


class LoginBody(BaseModel):
    username: str
    password: str
    remember: bool = False
