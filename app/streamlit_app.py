"""Streamlit 前端：带会话列表的图书馆借阅助手（含登录）。

启动方式（三个终端，或者直接 python start.py 一条命令）：
    ① LMS 后端：       .venv\\Scripts\\python.exe -m uvicorn lms.main:app --port 8000
    ② MCP 服务(HTTP)： .venv\\Scripts\\python.exe -m mcp_server.server --http
    ③ 前端：           .venv\\Scripts\\python.exe -m streamlit run app/streamlit_app.py

设计说明：
  * 登录后才进入对话界面；token 和读者信息放在 st.session_state 里
  * 每次页面重跑都调一次 /auth/me —— 既刷新侧栏的借阅状态，也顺便验证 token 还有效
  * 会话列表只显示"当前登录读者"的会话（多读者互不干扰）
  * 对话历史不放在 st.session_state 里，而是每次从会话库读 —— 刷新页面历史还在
"""
import asyncio
import os
import sys

#保证能从仓库根目录 import（Streamlit 会把 app/ 插到 sys.path 最前面）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import streamlit as st
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from agent import session as chat_session
from agent.loop import LibraryAgent
from agent.trace import ToolTrace

MCP_URL = "http://127.0.0.1:8765/mcp"
LMS_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="图书馆借阅助手", page_icon="📚", layout="wide")


def call_lms(method, path, json_body=None, token=None):
    """调 LMS 接口。返回 {"ok": True, "data": ...} 或 {"ok": False, "message": ...}。"""
    headers = {}

    if token:
        headers["Authorization"] = "Bearer " + token

    try:
        response = httpx.request(method, LMS_URL + path, json=json_body, headers=headers, timeout=10)
    except httpx.HTTPError as error:
        return {"ok": False, "message": "连不上 LMS 后端，请确认它已启动：" + str(error)}

    if response.status_code >= 400:
        detail = response.json().get("detail", {})
        message = detail.get("message", response.text) if isinstance(detail, dict) else str(detail)
        return {"ok": False, "message": message}

    return {"ok": True, "data": response.json()}


def show_login_page():
    """没登录时显示登录 / 注册表单。"""
    st.title("📚 图书馆借阅助手")
    st.caption("请先登录　｜　演示账号：R2025001　密码：123456")

    tab_login, tab_register = st.tabs(["登录", "注册"])

    with tab_login:
        with st.form("login_form"):
            user_id = st.text_input("借书证号", value="R2025001")
            password = st.text_input("密码", value="123456", type="password")
            submitted = st.form_submit_button("登录", use_container_width=True)

        if submitted:
            result = call_lms("POST", "/auth/login", {"user_id": user_id, "password": password})

            if result["ok"]:
                st.session_state.token = result["data"]["token"]
                st.session_state.user = result["data"]["user"]
                st.rerun()
            else:
                st.error(result["message"])

    with tab_register:
        st.caption("注册一个新读者：借书证号自己起一个（比如 R2025099）")

        with st.form("register_form"):
            new_id = st.text_input("借书证号")
            new_name = st.text_input("姓名")
            new_phone = st.text_input("联系电话（可不填）")
            new_password = st.text_input("密码（至少 6 位）", type="password")
            #演示用：可以选等级；真实系统里等级由图书馆授予，不由读者自选
            new_level = st.selectbox("读者等级", ["普通", "学生", "教师"])
            submitted = st.form_submit_button("注册并登录", use_container_width=True)

        if submitted:
            result = call_lms("POST", "/auth/register", {
                "user_id": new_id,
                "name": new_name,
                "phone": new_phone,
                "password": new_password,
                "level": new_level
            })

            if result["ok"]:
                st.session_state.token = result["data"]["token"]
                st.session_state.user = result["data"]["user"]
                st.rerun()
            else:
                st.error(result["message"])


async def ask_agent(user_id, session_id, question):
    """连一次 MCP 服务，跑一轮对话，返回助手的回答。"""
    async with streamable_http_client(MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            agent = LibraryAgent(
                session,
                user_id=user_id,
                session_id=session_id,
                trace=ToolTrace(user_id, verbose=False)
            )
            await agent.prepare()

            return await agent.chat(question)


#登录态放在 session_state 里（页面重跑不会丢）
if "user" not in st.session_state:
    st.session_state.user = None
    st.session_state.token = None

#没登录：只显示登录页（st.stop() 会让后面的对话界面不渲染）
if st.session_state.user is None:
    show_login_page()
    st.stop()

#每次页面重跑都刷新一次读者信息：既更新侧栏，也顺便验证 token 还有效
refreshed = call_lms("GET", "/auth/me", token=st.session_state.token)

if not refreshed["ok"]:
    st.warning("登录状态已失效，请重新登录")
    st.session_state.user = None
    st.session_state.token = None
    st.stop()

user = refreshed["data"]
st.session_state.user = user

#当前会话编号：只占一个编号、不写库（问第一句话时才落库）
if "session_id" not in st.session_state:
    st.session_state.session_id = chat_session.new_session_id()


# ---- 左侧：读者信息 + 会话列表 ----
with st.sidebar:
    st.title("📚 图书馆借阅助手")
    st.caption("当前读者：" + user["name"] + "（" + user["user_id"] + "）")
    st.caption(user["level"] + "读者　已借 " + str(user["current_borrow"]) + "/" + str(user["max_borrow"]) + " 本")

    if st.button("➕ 开新对话", use_container_width=True):
        st.session_state.session_id = chat_session.new_session_id()
        st.rerun()

    if st.button("退出登录", use_container_width=True):
        st.session_state.user = None
        st.session_state.token = None
        st.session_state.pop("session_id", None)
        st.rerun()

    st.divider()
    st.subheader("历史会话")

    #只看当前登录读者的会话
    for row in chat_session.list_sessions(reader_id=user["user_id"]):
        title = row["title"] if row["title"] else "（还没说话）"
        label = title + "  ·  " + str(row["message_count"]) + " 条"

        if row["session_id"] == st.session_state.session_id:
            label = "▶ " + label

        if st.button(label, key=row["session_id"], use_container_width=True):
            st.session_state.session_id = row["session_id"]
            st.rerun()


# ---- 右侧：当前会话 ----
session_id = st.session_state.session_id
st.caption("会话编号：" + session_id + "　｜　当前读者：" + user["user_id"])

for message in chat_session.load_messages(session_id):
    with st.chat_message(message["role"]):
        st.write(message["content"])

question = st.chat_input("问我点什么，比如：三体还有几本？")

if question:
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner("正在查馆藏 / 调用工具…"):
            answer = asyncio.run(ask_agent(user["user_id"], session_id, question))

        st.write(answer)