"""登录与鉴权：密码哈希 + JWT 签发/校验。

为什么单独一个文件：登录是"跨路由的能力"（前端要拿它确定"当前是谁"），
不属于某一张表的业务规则，所以单独成模块。

密码怎么存：绝不存明文。用标准库的 PBKDF2（加随机盐、十万次迭代），
把"盐$摘要"一起存进 users.password_hash。
"""
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from fastapi import Header, HTTPException

load_dotenv()

#密钥至少 32 字节（HS256 的要求，短了 PyJWT 会报 InsecureKeyLengthWarning）
#真实项目请用环境变量 JWT_SECRET 传一个随机长字符串，不要用这个默认值
JWT_SECRET = os.environ.get("JWT_SECRET", "library-agent-demo-secret-0123456789")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 12

PBKDF2_ITERATIONS = 100000


def hash_password(password, salt=None):
    """把密码变成"盐$摘要"。同一个密码每次调用结果都不同（因为盐是随机的）。"""
    salt = salt or os.urandom(16).hex()

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        PBKDF2_ITERATIONS
    ).hex()

    return salt + "$" + digest


def verify_password(password, stored):
    """校验密码。stored 是数据库里存的"盐$摘要"。"""
    if not stored or "$" not in stored:
        return False

    salt, _ = stored.split("$", 1)

    #用 compare_digest 做常数时间比较，避免"根据比对耗时猜密码"（时序攻击）
    return hmac.compare_digest(hash_password(password, salt), stored)


def create_token(user_id):
    """签发 token：里面写着"是谁"（sub）和"什么时候过期"（exp）。"""
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    }

    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token):
    """校验 token 并取出读者编号；无效或过期都返回 None。"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None

    return payload.get("sub")


def current_user_id(authorization: str | None = Header(default=None)):
    """FastAPI 依赖：从请求头 Authorization 里取出当前读者的编号。

    用法：路由函数写 user_id: str = Depends(current_user_id) 就自动带上登录校验。
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"reason": "missing_token", "message": "请先登录"}
        )

    user_id = decode_token(authorization[7:])

    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail={"reason": "invalid_token", "message": "登录状态已失效，请重新登录"}
        )

    return user_id