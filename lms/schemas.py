from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ===== 输出模型：数据来自数据库，要开 from_attributes 才能直接从 SQLAlchemy 对象转换 =====

class BookOut(BaseModel):
    #允许把 SQLAlchemy 的 Book 对象直接丢给这个模型（v2 用 ConfigDict，v1 的 orm_mode 已废弃）
    model_config = ConfigDict(from_attributes=True)

    book_id: str
    isbn: str
    title: str
    author: str
    category: str
    call_number: str
    total_copies: int
    available_copies: int
    description: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    name: str
    phone: str
    level: str
    max_borrow: int
    current_borrow: int


class LoanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    loan_id: str
    user_id: str
    book_id: str
    borrowed_at: datetime
    due_at: datetime
    returned_at: datetime | None
    renew_count: int


class ReservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    reservation_id: str
    user_id: str
    book_id: str
    created_at: datetime
    status: str


# ===== 输入模型：客户端（以及后面的 MCP 工具）发过来的请求体 =====

class LoanCreate(BaseModel):
    user_id: str = Field(description="借书证号，例如 R2025001")
    book_id: str = Field(description="图书编号，例如 B001")


class ReservationCreate(BaseModel):
    user_id: str = Field(description="借书证号，例如 R2025001")
    book_id: str = Field(description="图书编号，例如 B001")


# ===== 动作类接口的返回：字段和文档 3.2 里工具的返回结构保持一致 =====

class LoanCreatedOut(BaseModel):
    #对应 borrow(user_id, book_id) -> {loan_id, due_at}
    loan_id: str
    due_at: datetime


class RenewOut(BaseModel):
    #对应 renew(loan_id) -> {new_due_at}
    new_due_at: datetime


class ReturnOut(BaseModel):
    #对应 return_book(loan_id) -> {returned_at, fine}
    returned_at: datetime
    fine: float


class ReservationCreatedOut(BaseModel):
    #对应 reserve(user_id, book_id) -> {reservation_id, queue_position}
    reservation_id: str
    queue_position: int


class BookAvailabilityOut(BaseModel):
    #对应文档 3.2 的 check_availability 返回结构
    book_id: str
    title: str
    call_number: str
    total_copies: int
    available_copies: int
    on_shelf_locations: str
    next_return_date: datetime | None