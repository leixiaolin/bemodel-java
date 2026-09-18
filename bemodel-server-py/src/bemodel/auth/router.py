import bcrypt
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from bemodel.config import settings
from bemodel.core.base_dao import BaseDAO
from bemodel.core.database import get_session
from bemodel.core.exceptions import BizException
from bemodel.core.result import ok
from .entities import PlatformUser
from .jwt_service import JwtService

router = APIRouter(prefix="/api/auth")


@router.post("/login")
def login(body: dict, session: Session = Depends(get_session)):
    user = BaseDAO(session, PlatformUser).select_one(PlatformUser.username == body.get("username"))
    password = body.get("password")
    if user is None or password is None or not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
        raise BizException("用户名或密码错误")
    return ok({"token": JwtService(settings.jwt_secret).issue(user), "username": user.username,
               "displayName": user.display_name, "role": user.role})


@router.get("/me")
def me(request: Request, session: Session = Depends(get_session)):
    name = request.state.claims["sub"]
    user = BaseDAO(session, PlatformUser).select_one(PlatformUser.username == name)
    if user is None:
        raise BizException("用户不存在: " + name)
    return ok({"username": user.username, "displayName": user.display_name, "role": user.role})
