"""会话（session）存储：把每次对话的历史存进 SQLite。

对应导师的要求："每次对话就是一个 session"、"左边有每个 session 那种记录"。
前端要显示会话列表，就得先有地方存会话和历史 —— 所以这一步先做存储层。

设计说明：
  * 数据访问用 SQLAlchemy，和 lms/models.py 保持一致（一个项目一种写法）
  * 存在单独的文件 data/chat_sessions.sqlite，不跟图书馆业务库混在一起
    （LMS 管"书和人"，这里管"对话历史"，职责分开）
  * 只存 user / assistant 的可见内容；工具调用的细节由 data/traces/ 记录
"""
import os
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DB_PATH = "data/chat_sessions.sqlite"

#单独一个库：会话历史不属于图书馆业务数据
engine = create_engine(
    "sqlite:///" + DB_PATH,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class ChatSession(Base):
    """一次对话（一个会话）。"""

    __tablename__ = "chat_sessions"

    session_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    reader_id: Mapped[str] = mapped_column(String(20), default="")
    title: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now)


class ChatMessage(Base):
    """会话里的一条消息（只存 user / assistant 的可见内容）。"""

    __tablename__ = "chat_messages"

    message_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.session_id"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)


def init_db():
    #建表（已存在就跳过，幂等）
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    Base.metadata.create_all(engine)


def new_session_id():
    #用时间戳当会话编号，例如 20261002-183045
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def create_session(reader_id, session_id=None):
    """新建一个会话，返回它的 session_id。"""
    init_db()

    session_id = session_id or new_session_id()
    db = SessionLocal()

    try:
        #已经存在就不重复建（同一个 session_id 再传进来是幂等的）
        if db.get(ChatSession, session_id) is None:
            db.add(ChatSession(
                session_id=session_id,
                reader_id=reader_id,
                title=""
            ))
            db.commit()
    finally:
        db.close()

    return session_id


def save_message(session_id, role, content):
    """往会话里存一条消息，并更新会话的最后活动时间和标题。"""
    db = SessionLocal()

    try:
        db.add(ChatMessage(
            session_id=session_id,
            role=role,
            content=content
        ))

        record = db.get(ChatSession, session_id)

        if record is not None:
            record.updated_at = datetime.now()

            #标题：拿第一句读者提问的前 20 个字（只写一次）
            if role == "user" and not record.title:
                record.title = content[:20]

        #两条修改（插消息 + 改会话）一次提交
        db.commit()
    finally:
        db.close()


def load_messages(session_id):
    """读出一个会话的全部消息（按写入顺序），用来恢复对话。"""
    db = SessionLocal()

    try:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.message_id)
        )

        return [
            {"role": row.role, "content": row.content}
            for row in db.scalars(stmt).all()
        ]
    finally:
        db.close()


def list_sessions(reader_id=None):
    """列出会话，最近活动的排在前面（前端左侧列表直接用这个）。

    传 reader_id 就只列出这个读者的会话 —— 多读者登录时各看各的。
    """
    db = SessionLocal()

    try:
        #只列出"真的说过话"的会话：空会话不该出现在历史记录里
        stmt = (
            select(ChatSession)
            .where(
                select(ChatMessage)
                .where(ChatMessage.session_id == ChatSession.session_id)
                .exists()
            )
        )

        if reader_id is not None:
            stmt = stmt.where(ChatSession.reader_id == reader_id)

        stmt = stmt.order_by(ChatSession.updated_at.desc())
        sessions = db.scalars(stmt).all()

        results = []

        for record in sessions:
            count_stmt = select(ChatMessage).where(ChatMessage.session_id == record.session_id)

            results.append({
                "session_id": record.session_id,
                "reader_id": record.reader_id,
                "title": record.title,
                "updated_at": record.updated_at.isoformat(timespec="seconds"),
                "message_count": len(db.scalars(count_stmt).all())
            })

        return results
    finally:
        db.close()