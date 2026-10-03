from fastapi import FastAPI

from lms.models import init_db
from lms.routers import auth, books, loans, reservations, users

#启动前确保 4 张表存在：library.db 不存在会自动建，已经建过就跳过（幂等）
init_db()

app = FastAPI(
    title="Library Agent LMS",
    description="图书馆借阅助手（中难度项目）后端：FastAPI + SQLite",
    version="0.1.0"
)

app.include_router(books.router)
app.include_router(users.router)
app.include_router(loans.router)
app.include_router(reservations.router)
app.include_router(auth.router)

@app.get("/health", tags=["ops"], summary="健康检查")
def health():
    #不属于文档要求的 9 个接口，只是用来确认服务是否起来了；不需要可以删掉
    return {"status": "ok"}