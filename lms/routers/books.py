from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from lms import rules
from lms.models import Book, Loan, get_db
from lms.schemas import BookAvailabilityOut, BookOut

router = APIRouter(prefix="/books", tags=["books"])


@router.get("", response_model=list[BookOut], summary="按关键字和类目检索馆藏")
def list_books(
    q: str | None = None,
    category: str | None = None,
    db: Session = Depends(get_db)
):
    """q 在书名、作者、简介里做模糊匹配；category 按类目精确匹配。两个参数都可以不传。"""
    stmt = select(Book)

    if category:
        stmt = stmt.where(Book.category == category)

    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            Book.title.like(like)
            | Book.author.like(like)
            | Book.description.like(like)
        )

    return db.scalars(stmt).all()


@router.get("/{book_id}", response_model=BookOut, summary="查询单本图书")
def get_book(book_id: str, db: Session = Depends(get_db)):
    book = db.get(Book, book_id)

    if book is None:
        #错误结构见文档 3.2：reason 是给程序看的标识，message 是给人看的说明
        raise HTTPException(
            status_code=404,
            detail={
                "reason": "book_not_found",
                "message": f"馆藏中没有编号为 {book_id} 的书"
            }
        )

    return book



@router.get("/{book_id}/availability", response_model=BookAvailabilityOut, summary="查询某本书的可借状态")
def get_book_availability(book_id: str, db: Session = Depends(get_db)):
    """给 check_availability 工具用：总册数、在架册数、在架位置、最近一次应还日期。"""
    book = db.get(Book, book_id)

    if book is None:
        raise HTTPException(
            status_code=404,
            detail={
                "reason": "book_not_found",
                "message": f"馆藏中没有编号为 {book_id} 的书"
            }
        )

    #最近应还日期 = 这本书所有未归还借阅里最早的那个 due_at
    stmt = (
        select(Loan.due_at)
        .where(
            Loan.book_id == book_id,
            Loan.returned_at.is_(None)
        )
        .order_by(Loan.due_at.asc())
        .limit(1)
    )

    next_return_date = db.scalars(stmt).first()

    return {
        "book_id": book.book_id,
        "title": book.title,
        "call_number": book.call_number,
        "total_copies": book.total_copies,
        "available_copies": book.available_copies,
        "on_shelf_locations": rules.shelf_location(book.call_number),
        "next_return_date": next_return_date
    }