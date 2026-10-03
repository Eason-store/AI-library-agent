"""工具调用轨迹（trace）。

每次调用工具都记一笔：什么时候、调了哪个工具、传了什么参数、返回了什么。

用途有两个：
  1. 调试和演示：能回看 Agent 到底做了什么（终端里那两行 [调用工具]/[工具返回] 的打印也由它负责）
  2. 评测：文档六-3 要算"工具调用正确率（Tool Name + 参数是否命中）"，没有轨迹就算不出来

轨迹文件默认写到 data/traces/ 下，文件名带时间戳，一次会话（或一次评测）一份。
"""
import json
import os
from datetime import datetime

TRACE_DIR = "data/traces"


class ToolTrace:
    """一次会话（或一条评测用例）的工具调用记录。"""

    def __init__(self, reader_id, verbose=True):
        self.reader_id = reader_id
        self.verbose = verbose      #是否在终端打印；评测时关掉，免得刷屏
        self.calls = []             #内存里的轨迹，评测代码直接读它

    def record(self, name, arguments, result_text):
        """记录一次工具调用，并（可选地）在终端打印出来。"""
        call = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "tool": name,
            "arguments": arguments,
            "result": result_text[:500]
        }

        self.calls.append(call)

        if self.verbose:
            print("  [调用工具] " + name + " " + json.dumps(arguments, ensure_ascii=False))
            print("  [工具返回] " + result_text[:120].replace("\n", " "))

        return call

    def save(self, label="session"):
        """把轨迹写到 data/traces/ 下，返回文件路径。"""
        os.makedirs(TRACE_DIR, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(TRACE_DIR, stamp + "-" + label + ".json")

        with open(path, "w", encoding="utf-8") as file:
            json.dump(
                {"reader_id": self.reader_id, "calls": self.calls},
                file,
                ensure_ascii=False,
                indent=2
            )

        return path