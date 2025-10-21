from pydantic import BaseModel

class UserLogin(BaseModel):
    identifier: str
    password: str