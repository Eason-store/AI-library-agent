from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.models import Loan, User, get_db
from lms.schemas import LoanOut, UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}", response_model=UserOut, summary="查询读者信息")
def get_user(user_id: str, db: Session = Depends(get_db)):
    user = db.get(User, user_id)

    if user is None:
        raise HTTPException(
            status_code=404,
            detail={
                "reason": "user_not_found",
                "message": f"系统中没有借书证号为 {user_id} 的读者"
            }
        )

    return user


@router.get("/{user_id}/loans", response_model=list[LoanOut], summary="查询读者的借阅记录")
def list_user_loans(user_id: str, db: Session = Depends(get_db)):
    """返回该读者的全部借阅记录（含已归还的），按借出时间倒序。"""
    user = db.get(User, user_id)

    if user is None:
        raise HTTPException(
            status_code=404,
            detail={
                "reason": "user_not_found",
                "message": f"系统中没有借书证号为 {user_id} 的读者"
            }
        )

    stmt = (
        select(Loan)
        .where(Loan.user_id == user_id)
        .order_by(Loan.borrowed_at.desc())
    )

    return db.scalars(stmt).all()