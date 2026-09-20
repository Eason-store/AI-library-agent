from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from lms import rules
from lms.models import Book, Reservation, User, get_db
from lms.schemas import ReservationCreate, ReservationCreatedOut, ReservationOut

router = APIRouter(prefix="/reservations", tags=["reservations"])


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


def _get_reservation_or_404(reservation_id, db):
    reservation = db.get(Reservation, reservation_id)

    if reservation is None:
        raise HTTPException(
            status_code=404,
            detail={
                "reason": "reservation_not_found",
                "message": f"没有找到编号为 {reservation_id} 的预约记录"
            }
        )

    return reservation


def _expire_stale_reservations(db, now):
    """文档 3.1：预约在 3 天内未取书自动失效。
    本档不做后台定时任务，改成“惰性清理”：每次预约相关接口被调用时扫一遍，把超期的 waiting 改成 cancelled。
    """
    stmt = select(Reservation).where(Reservation.status == "waiting")

    expired = [
        reservation
        for reservation in db.scalars(stmt).all()
        if rules.is_reservation_expired(reservation, now)
    ]

    for reservation in expired:
        reservation.status = "cancelled"

    if expired:
        db.commit()

    return expired


def _next_reservation_id(db):
    #预约编号按 RS000001、RS000002 递增
    last = db.scalars(
        select(Reservation.reservation_id)
        .order_by(Reservation.reservation_id.desc())
        .limit(1)
    ).first()

    if last is None:
        return "RS000001"

    return "RS" + f"{int(last[2:]) + 1:06d}"


def _queue_position(book_id, reservation_id, db):
    #同一本书还在 waiting 的预约按创建时间排队，返回当前这条的位次（从 1 开始）
    stmt = (
        select(Reservation.reservation_id)
        .where(
            Reservation.book_id == book_id,
            Reservation.status == "waiting"
        )
        .order_by(
            Reservation.created_at.asc(),
            Reservation.reservation_id.asc()
        )
    )

    ids = list(db.scalars(stmt).all())

    return ids.index(reservation_id) + 1


@router.post("", response_model=ReservationCreatedOut, status_code=201, summary="预约图书")
def reserve(payload: ReservationCreate, db: Session = Depends(get_db)):
    """读者对暂时借不到的书排队预约，返回预约编号和当前排队位次。"""
    now = datetime.now()

    _expire_stale_reservations(db, now)

    user = _get_user_or_404(payload.user_id, db)
    book = _get_book_or_404(payload.book_id, db)

    #【文档未规定的补充规则】有在架副本的书不需要预约，直接借就行；README 里要写进“与文档的差异”
    if book.available_copies > 0:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "book_available",
                "message": f"《{book.title}》当前有在架副本，可以直接借阅"
            }
        )

    stmt = select(Reservation).where(
        Reservation.user_id == user.user_id,
        Reservation.book_id == book.book_id,
        Reservation.status == "waiting"
    )

    if db.scalars(stmt).first() is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "reservation_exists",
                "message": f"这位读者已经预约过《{book.title}》，正在排队中"
            }
        )

    reservation = Reservation(
        reservation_id=_next_reservation_id(db),
        user_id=user.user_id,
        book_id=book.book_id,
        created_at=now,
        status="waiting"
    )

    db.add(reservation)
    db.commit()
    db.refresh(reservation)

    return ReservationCreatedOut(
        reservation_id=reservation.reservation_id,
        queue_position=_queue_position(book.book_id, reservation.reservation_id, db)
    )


@router.delete("/{reservation_id}", response_model=ReservationOut, summary="取消预约")
def cancel_reservation(reservation_id: str, db: Session = Depends(get_db)):
    """取消一条还在排队的预约。已取消或已取书的预约会返回 409。"""
    now = datetime.now()

    _expire_stale_reservations(db, now)

    reservation = _get_reservation_or_404(reservation_id, db)

    if reservation.status == "cancelled":
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "already_cancelled",
                "message": "这条预约已经取消过了"
            }
        )

    if reservation.status == "fulfilled":
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "reservation_fulfilled",
                "message": "这条预约已经取书完成，不能取消"
            }
        )

    reservation.status = "cancelled"

    db.commit()
    db.refresh(reservation)

    return reservation