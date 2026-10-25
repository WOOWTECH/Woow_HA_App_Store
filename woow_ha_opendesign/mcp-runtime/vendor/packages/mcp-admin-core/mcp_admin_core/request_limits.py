"""由產品明確啟用的 MCP 輸入界線；在驗證 token 後、轉發／SDK 驗證前執行。"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from starlette.requests import Request


class RequestLimitError(Exception):
    """可直接回傳且不含輸入內容的 HTTP／JSON-RPC 錯誤。"""

    def __init__(self, message: str, *, status: int = 413, code: int = -32602, rpc_id=None):
        """保留已解析的請求 ID，讀取／解析前的拒絕使用 null。"""
        self.status = status
        self.payload = {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}
        super().__init__(message)


@dataclass(frozen=True)
class McpRequestLimits:
    """每個 app 固定啟用的請求位元組、工具參數元素與深度上限。"""
    max_bytes: int
    max_argument_elements: int
    max_depth: int = 64

    def _check_depth(self, value: str | bytes) -> None:
        """在建立 JSON 物件前，忽略字串內容計算容器巢狀深度。"""
        # 在 json.loads 建立物件前先掃描結構；字串中的括號、跳脫引號不計入深度。
        text = value.decode("utf-8") if isinstance(value, bytes) else value
        depth = 0
        in_string = escaped = False
        for char in text:
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char in "[{":
                depth += 1
                if depth > self.max_depth:
                    raise RequestLimitError(f"MCP JSON exceeds {self.max_depth} levels of nesting")
            elif char in "]}":
                depth -= 1

    async def read_body(self, request: Request) -> bytes:
        """同時限制宣告與實際大小，超限時不再讀取後續分塊。"""
        # 轉發壓縮內容會讓上游解壓後繞過這裡的位元組界線。
        if request.headers.get("content-encoding", "identity").lower() != "identity":
            raise RequestLimitError("Compressed MCP requests are not supported", status=415)
        length = request.headers.get("content-length")
        if length is not None:
            try:
                size = int(length)
                if size < 0:
                    raise ValueError
            except ValueError:
                raise RequestLimitError("Invalid Content-Length", status=400, code=-32600)
            if size > self.max_bytes:
                raise RequestLimitError(f"MCP request exceeds {self.max_bytes} bytes")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > self.max_bytes:
                raise RequestLimitError(f"MCP request exceeds {self.max_bytes} bytes")
            body.extend(chunk)
        return bytes(body)

    def parse_and_check(self, body: bytes) -> Any:
        """以迭代器計算 batch 共用預算；回傳未修改的原始訊息。"""
        if not body:
            return None
        try:
            self._check_depth(body)
            rpc = json.loads(body)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise RequestLimitError("Invalid or excessively nested JSON", status=400, code=-32700)
        messages = rpc if isinstance(rpc, list) else [rpc]
        remaining = self.max_argument_elements
        # n8n 會把部分字串參數 JSON.parse 後當結構使用，預算也涵蓋這些解碼後的結構。
        decoded_bytes = 0
        for message in messages:
            if not isinstance(message, dict) or message.get("method") != "tools/call":
                continue
            params = message.get("params")
            if not isinstance(params, dict):
                continue
            stack = [iter((params.get("arguments"),))]
            while stack:
                try:
                    value = next(stack[-1])
                except StopIteration:
                    stack.pop()
                    continue
                if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
                    decoded_bytes += len(value.encode("utf-8", errors="surrogatepass"))
                    if decoded_bytes > self.max_bytes:
                        raise RequestLimitError("Encoded MCP arguments exceed decoding budget", rpc_id=message.get("id"))
                    try:
                        self._check_depth(value)
                        value = json.loads(value)
                    except RequestLimitError as error:
                        raise RequestLimitError(
                            error.payload["error"]["message"],
                            status=error.status,
                            code=error.payload["error"]["code"],
                            rpc_id=message.get("id"),
                        ) from None
                    except RecursionError:
                        raise RequestLimitError("Excessively nested MCP arguments", rpc_id=message.get("id"))
                    except ValueError:
                        continue
                if isinstance(value, (dict, list)):
                    if len(stack) > self.max_depth:
                        raise RequestLimitError("Excessively nested MCP arguments", rpc_id=message.get("id"))
                    remaining -= len(value)
                    if remaining < 0:
                        raise RequestLimitError(
                            f"MCP tool arguments exceed {self.max_argument_elements} elements",
                            rpc_id=message.get("id"),
                        )
                    stack.append(iter(value.values() if isinstance(value, dict) else value))
        return rpc
