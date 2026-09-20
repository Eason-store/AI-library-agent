from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from lms import rules
from lms.models import Book, Loan, User, get_db
from lms.schemas import LoanCreate, LoanCreatedOut, RenewOut, ReturnOut

router = APIRouter(prefix="/loans", tags=["loans"])

#拒绝借书/续借时给的中文兜底说明（措辞由 Agent 端组织，这里只保证接口自己也能说清）
BORROW_REJECT_MESSAGES = {
    "borrow_limit_exceeded": "已达到可借上限，请先归还部分图书",
    "has_overdue_loan": "有逾期未还的图书，请先归还后再借"
}

RENEW_REJECT_MESSAGES = {
    "already_returned": "这笔借阅已经归还了，不需要续借",
    "renew_limit_reached": "每本图书最多只能续借 1 次"
}


# ===== 下面几个是 loans.py 内部用的小工具，三个接口都要用到，所以抽出来 =====

def _get_user_or_404(user_id, db):
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


def _get_book_or_404(book_id, db):
    book = db.get(Book, book_id)

    if book is None:
        raise HTTPException(
            status_code=404,
            detail={
                "reason": "book_not_found",
                "message": f"馆藏中没有编号为 {book_id} 的书"
            }
        )

    return book


def _get_loan_or_404(loan_id, db):
    loan = db.get(Loan, loan_id)

    if loan is None:
        raise HTTPException(
            status_code=404,
            detail={
                "reason": "loan_not_found",
                "message": f"没有找到编号为 {loan_id} 的借阅记录"
            }
        )

    return loan


def _active_loans_of(user_id, db):
    #这个读者当前还没归还的借阅记录
    stmt = select(Loan).where(
        Loan.user_id == user_id,
        Loan.returned_at.is_(None)
    )

    return db.scalars(stmt).all()


def _next_loan_id(db):
    #借阅编号按 L000001、L000002 递增；ID 是零填充的，所以字符串倒序的第一个就是最大号
    last = db.scalars(
        select(Loan.loan_id)
        .order_by(Loan.loan_id.desc())
        .limit(1)
    ).first()

    if last is None:
        return "L000001"

    return "L" + f"{int(last[1:]) + 1:06d}"


# ===== 三个接口 =====

@router.post("", response_model=LoanCreatedOut, status_code=201, summary="借书")
def borrow(payload: LoanCreate, db: Session = Depends(get_db)):
    """文档 3.1：借期 30 天；额度上限和逾期禁借由 rules.py 判断。"""
    now = datetime.now()

    user = _get_user_or_404(payload.user_id, db)
    book = _get_book_or_404(payload.book_id, db)

    active_loans = _active_loans_of(user.user_id, db)

    #同一本书还没还，不能重复借
    if any(loan.book_id == book.book_id for loan in active_loans):
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "already_borrowed",
                "message": f"这位读者已经借了《{book.title}》并且还没有归还"
            }
        )

    if book.available_copies <= 0:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "no_available_copies",
                "message": f"《{book.title}》当前没有在架可借的副本"
            }
        )

    ok, reason = rules.check_can_borrow(user, active_loans, now)

    if not ok:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": reason,
                "message": BORROW_REJECT_MESSAGES.get(reason, "当前无法借书")
            }
        )

    loan = Loan(
        loan_id=_next_loan_id(db),
        user_id=user.user_id,
        book_id=book.book_id,
        borrowed_at=now,
        due_at=rules.calculate_due_at(now),
        returned_at=None,
        renew_count=0
    )

    db.add(loan)

    #借出后：在架数减一，读者已借数加一
    book.available_copies -= 1
    user.current_borrow += 1

    db.commit()
    db.refresh(loan)

    return LoanCreatedOut(loan_id=loan.loan_id, due_at=loan.due_at)


@router.post("/{loan_id}/renew", response_model=RenewOut, summary="续借")
def renew(loan_id: str, db: Session = Depends(get_db)):
    """文档 3.1：每本最多续借 1 次，续借加 30 天。"""
    now = datetime.now()

    loan = _get_loan_or_404(loan_id, db)

    ok, reason = rules.check_can_renew(loan, now)

    if not ok:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": reason,
                "message": RENEW_REJECT_MESSAGES.get(reason, "当前无法续借")
            }
        )

    loan.due_at = rules.calculate_new_due_at(loan.due_at)
    loan.renew_count += 1

    db.commit()
    db.refresh(loan)

    return RenewOut(new_due_at=loan.due_at)


@router.post("/{loan_id}/return", response_model=ReturnOut, summary="还书")
def return_book(loan_id: str, db: Session = Depends(get_db)):
    """归还图书。已经归还过的记录返回 409 already_returned；
    文档 3.2 要求的"第二次归还返回已归还提示"这种幂等语义，由工具层负责翻译。
    """
    now = datetime.now()

    loan = _get_loan_or_404(loan_id, db)

    if loan.returned_at is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "already_returned",
                "message": "这笔借阅已经归还过了"
            }
        )

    book = _get_book_or_404(loan.book_id, db)
    user = _get_user_or_404(loan.user_id, db)

    fine = rules.calculate_fine(loan, now)

    loan.returned_at = now

    #归还后：在架数加一（但不超过总册数），读者已借数减一（不小于 0）
    book.available_copies = min(book.available_copies + 1, book.total_copies)
    user.current_borrow = max(0, user.current_borrow - 1)

    db.commit()
    db.refresh(loan)

    return ReturnOut(returned_at=loan.returned_at, fine=fine)