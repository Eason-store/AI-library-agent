from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


#SQLite 数据库文件放在 lms/ 目录下，第一次建表时自动创建
DATABASE_URL = "sqlite:///lms/library.db"

#check_same_thread=False：FastAPI 会多线程处理请求，而 SQLite 默认禁止连接跨线程使用
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False
)


class Base(DeclarativeBase):
    pass


#文档 3.1：books 表
#description 是文档表结构漏写、但文档 3.3 要求的向量检索（书名+作者+简介）必需的字段
class Book(Base):
    __tablename__ = "books"

    book_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    isbn: Mapped[str] = mapped_column(String(20), default="")
    title: Mapped[str] = mapped_column(String(200))
    author: Mapped[str] = mapped_column(String(100), default="")
    category: Mapped[str] = mapped_column(String(50), default="")
    call_number: Mapped[str] = mapped_column(String(50), default="")
    total_copies: Mapped[int] = mapped_column(Integer, default=0)
    available_copies: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(String(500), default="")


#文档 3.1：users 表
#level 取值：普通 / 学生 / 教师；max_borrow 是可借上限，current_borrow 是已经借了几本
class User(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    phone: Mapped[str] = mapped_column(String(20), default="")
    level: Mapped[str] = mapped_column(String(10), default="普通")
    max_borrow: Mapped[int] = mapped_column(Integer, default=5)
    current_borrow: Mapped[int] = mapped_column(Integer, default=0)


#文档 3.1：loans 表（借阅记录）
#returned_at 为空表示还没还；renew_count 记录已经续借过几次
class Loan(Base):
    __tablename__ = "loans"

    loan_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"))
    book_id: Mapped[str] = mapped_column(ForeignKey("books.book_id"))
    borrowed_at: Mapped[datetime] = mapped_column(DateTime)
    due_at: Mapped[datetime] = mapped_column(DateTime)
    returned_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        default=None
    )
    renew_count: Mapped[int] = mapped_column(Integer, default=0)


#文档 3.1：reservations 表（预约记录）
#status 取值：waiting / fulfilled / cancelled
class Reservation(Base):
    __tablename__ = "reservations"

    reservation_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"))
    book_id: Mapped[str] = mapped_column(ForeignKey("books.book_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="waiting")


def init_db():
    #建表：按上面的模型在 library.db 里创建 4 张表，已经存在就跳过
    Base.metadata.create_all(engine)


def get_db():
    #FastAPI 依赖：每个请求开一个数据库会话，请求结束自动关闭
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def book_rows():
    """把 books 表读成 list[dict]，字段名和原来的 data/books.json 保持一致。

    检索层（rag）和建索引脚本都用它，保证"书是从哪来的"只有一处定义。
    """
    db = SessionLocal()

    try:
        books = db.scalars(select(Book)).all()

        return [
            {
                "book_id": book.book_id,
                "isbn": book.isbn,
                "title": book.title,
                "author": book.author,
                "category": book.category,
                "call_number": book.call_number,
                "total_copies": book.total_copies,
                "available_copies": book.available_copies,
                "description": book.description
            }
            for book in books
        ]
    finally:
        db.close()