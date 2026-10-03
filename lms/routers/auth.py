"""注册 / 登录 / 取当前登录读者。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from lms import rules
from lms.auth import create_token, current_user_id, hash_password, verify_password
from lms.models import User, get_db
from lms.schemas import LoginIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=201, summary="注册读者")
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    """创建新读者并直接发 token（注册完就等于登录了）。"""
    if len(payload.password) < 6:
        raise HTTPException(
            status_code=400,
            detail={"reason": "password_too_short", "message": "密码至少 6 位"}
        )

    if db.get(User, payload.user_id) is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "user_id_taken",
                "message": "借书证号 " + payload.user_id + " 已经被注册了"
            }
        )

    #等级白名单直接从 rules.py 的规则表取（普通/学生/教师）——
    #规则只有一份，将来加等级不用改这里
    if payload.level not in rules.MAX_BORROW_BY_LEVEL:
        raise HTTPException(
            status_code=400,
            detail={
                "reason": "invalid_level",
                "message": "读者等级只能是：" + "、".join(rules.MAX_BORROW_BY_LEVEL)
            }
        )

    user = User(
        user_id=payload.user_id,
        name=payload.name,
        phone=payload.phone,
        level=payload.level,
        #额度按等级算，同样取自 rules.py（普通 5 / 学生 8 / 教师 15）
        max_borrow=rules.max_borrow_for(payload.level),
        current_borrow=0,
        password_hash=hash_password(payload.password)
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return TokenOut(token=create_token(user.user_id), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut, summary="登录")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.get(User, payload.user_id)

    #读者不存在 和 密码不对，返回同样的提示 —— 免得被人试出"哪些编号是存在的"
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail={"reason": "bad_credentials", "message": "借书证号或密码不正确"}
        )

    return TokenOut(token=create_token(user.user_id), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut, summary="取当前登录读者")
def me(user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    """这个接口必须带 token —— 它就是前端"验证登录状态"用的。"""
    user = db.get(User, user_id)

    if user is None:
        raise HTTPException(
            status_code=404,
            detail={"reason": "user_not_found", "message": "读者不存在"}
        )

    return user