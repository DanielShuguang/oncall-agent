"""PDF 解析的子进程隔离（ADR-0032）。

上传文件是不可信输入：PDF 解析库面对畸形文件可能崩溃、卡死或耗光内存。解析放到
独立进程后，最坏情况只是子进程被杀，API 进程仍能返回 422。父进程用管道拿结果，
超时则 terminate/kill；错误类型仍映射为 `ParseError`，上传接口的错误口径不变。
"""

from __future__ import annotations

import multiprocessing as mp
from multiprocessing.connection import Connection
from typing import Any

from app.rag.parse import ParsedDoc, ParseError

#: 单份 PDF 的解析预算：10MB 上限的文本层 PDF 在慢机器上也能跑完；不含 OCR。
PDF_PARSE_TIMEOUT_S = 60.0


def parse_pdf_isolated(
    filename: str,
    data: bytes,
    *,
    timeout_s: float | None = None,
) -> ParsedDoc:
    """在 spawn 子进程里解析 PDF；超时/崩溃都收敛成 `ParseError`。"""
    timeout = PDF_PARSE_TIMEOUT_S if timeout_s is None else timeout_s
    context = mp.get_context("spawn")
    parent_conn, child_conn = context.Pipe(duplex=False)
    process = context.Process(
        target=_parse_worker,
        args=(child_conn, filename, data),
        daemon=True,
    )
    try:
        process.start()
    except Exception as exc:  # pragma: no cover - 进程起不来通常是环境问题
        parent_conn.close()
        child_conn.close()
        raise ParseError(f"PDF 解析进程启动失败: {exc}") from exc
    child_conn.close()

    try:
        if not parent_conn.poll(timeout):
            _terminate(process)
            raise ParseError(f"PDF 解析超时（>{timeout:g} 秒），请拆分或压缩后重试")
        try:
            status, payload = parent_conn.recv()
        except EOFError as exc:
            raise ParseError("PDF 解析进程异常退出，请确认文件完整后重试") from exc
        except Exception as exc:  # pragma: no cover - 管道/pickle 损坏属于环境异常
            raise ParseError(f"PDF 解析结果读取失败: {exc}") from exc
    finally:
        parent_conn.close()
        process.join(timeout=1)
        if process.is_alive():
            _terminate(process)

    if status == "ok":
        return payload
    if status == "parse_error":
        raise ParseError(payload)
    raise ParseError(f"PDF 解析失败: {payload}")


def _parse_worker(conn: Connection, filename: str, data: bytes) -> None:
    # 延迟导入：parse 模块只在调用时才反过来导入本模块，模块级导入会成环。
    from app.rag.parse import _parse_pdf_inprocess

    try:
        parsed = _parse_pdf_inprocess(filename, data)
    except ParseError as exc:
        conn.send(("parse_error", str(exc)))
    except Exception as exc:  # 子进程要把任何异常带回父进程
        conn.send(("error", f"{type(exc).__name__}: {exc}"))
    else:
        conn.send(("ok", parsed))
    finally:
        conn.close()


def _terminate(process: Any) -> None:
    process.terminate()
    process.join(timeout=2)
    if process.is_alive():
        process.kill()
        process.join(timeout=1)
