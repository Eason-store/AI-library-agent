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
    book_title: str = ""      #借阅列表里带上书名（由 books 表 join 得到），方便展示
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

# ===== 登录相关 =====

class RegisterIn(BaseModel):
    user_id: str = Field(description="借书证号，例如 R2025051")
    name: str = Field(description="姓名")
    phone: str = Field(default="", description="联系电话（可不填）")
    password: str = Field(description="密码，至少 6 位")
    #演示用：允许注册时选等级。真实系统里等级应该由图书馆授予，不能自己选（否则人人都选"教师"借 15 本）
    level: str = Field(default="普通", description="读者等级：普通 / 学生 / 教师")


class LoginIn(BaseModel):
    user_id: str = Field(description="借书证号")
    password: str = Field(description="密码")


class TokenOut(BaseModel):
    token: str = Field(description="登录令牌；后续请求放在请求头 Authorization: Bearer <token>")
    user: UserOut