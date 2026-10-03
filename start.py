"""一条命令启动整套服务（文档验收要求：一条命令启动后端 + Agent）。

会依次拉起三个进程：
    ① LMS 后端      FastAPI + SQLite，端口 8000
    ② MCP 服务      HTTP 模式，端口 8765
    ③ Streamlit 前端 网页界面，端口 8501

按 Ctrl+C 会一起关掉这三个进程。

用法（必须在项目根目录）：
    .venv\\Scripts\\python.exe start.py
"""
import subprocess
import sys
import time
import os

PYTHON = sys.executable


#子进程要继承的环境变量：
#  HF_HUB_OFFLINE=1 —— 模型已经在本地缓存了，别让它每次启动都去 HuggingFace 检查更新
#  （不设的话，断网环境下 MCP 服务会重试好几分钟，一直起不来）
CHILD_ENV = {**os.environ, "HF_HUB_OFFLINE": "1", "PYTHONIOENCODING": "utf-8"}

SERVICES = [
    (
        "LMS 后端",
        [PYTHON, "-m", "uvicorn", "lms.main:app", "--port", "8000"],
        4      #启动后等几秒再拉下一个
    ),
    (
        "MCP 服务",
        [PYTHON, "-m", "mcp_server.server", "--http"],
        14     #MCP 服务启动时要加载向量模型，久一点
    ),
    (
        "Streamlit 前端",
        [PYTHON, "-m", "streamlit", "run", "app/streamlit_app.py"],
        2
    )
]


def main():
    processes = []

    try:
        for name, command, wait_seconds in SERVICES:
            print("启动 " + name + " …（等待 " + str(wait_seconds) + " 秒）")
            processes.append((name, subprocess.Popen(command, env=CHILD_ENV)))
            time.sleep(wait_seconds)

        print()
        print("=" * 56)
        print("三个服务都起来了：")
        print("  接口文档（Swagger）  http://127.0.0.1:8000/docs")
        print("  MCP 服务             http://127.0.0.1:8765/mcp")
        print("  前端页面             http://localhost:8501")
        print("=" * 56)
        print("按 Ctrl+C 退出（会一起关掉三个服务）")
        print()

        #主进程在这里等第一个服务结束（或者等 Ctrl+C）
        for name, process in processes:
            process.wait()
    except KeyboardInterrupt:
        print()
        print("正在关闭服务…")
    finally:
        for name, process in processes:
            process.terminate()
        print("已关闭。")

    #启动时是在项目根目录，三个子进程的相对路径（data/...）才能对上


if __name__ == "__main__":
    main()