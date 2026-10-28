"""装在口袋里的 HTTP 客户端。Python 3.11+，零依赖。

    用法：
    import fetch
    data = fetch.get("https://example.com/api").json()

把本文件复制进你的项目即可使用。超时与 TLS 校验默认开启；
HTTP 错误默认抛出。默认缓冲响应，流式读取需显式调用。
HTTP/1.1，同步。

SPDX-License-Identifier: MIT
Copyright (c) 2026 Kenneth Reitz

（以下为 MIT 许可证原文，保持不变）

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

from __future__ import annotations

import gzip
import http.client
import http.cookiejar
import io
import json as _json
import logging
import math
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass
from email.message import Message
from functools import partial
from typing import Any, Self, TypedDict, TypeVar, Unpack, cast

__version__ = "0.1.0"
__all__ = [
    "DecodeError",
    "Error",
    "HTTPError",
    "Headers",
    "RedirectError",
    "RequestError",
    "Response",
    "Session",
    "StreamResponse",
    "Timeout",
    "delete",
    "get",
    "head",
    "options",
    "patch",
    "post",
    "put",
    "request",
    "stream",
]

_UNSET = object()
_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_REDIRECTS = {301, 302, 303, 307, 308}
_T = TypeVar("_T")
_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())


class Headers(Mapping[str, str]):
    """只读、大小写不敏感的表头映射。重复字段请用 get_all() 获取。"""

    def __init__(self, items: Iterable[tuple[str, str]] = ()) -> None:
        self._items = tuple(items)

    def __getitem__(self, name: str) -> str:
        values = self.get_all(name)
        if not values:
            raise KeyError(name)
        return values[0]

    def __iter__(self) -> Iterator[str]:
        seen = set()
        for name, _ in self._items:
            if name.lower() not in seen:
                seen.add(name.lower())
                yield name

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def get_all(self, name: str) -> list[str]:
        return [value for key, value in self._items if key.lower() == name.lower()]


class Error(Exception):
    """fetch 失败异常的基类。参数无效时抛 ValueError/TypeError。"""


class RequestError(Error):
    """连接、TLS 或 HTTP 协议失败；原始异常保存在 __cause__ 中。"""


class Timeout(RequestError):
    """某个 socket 操作超过了超时时间。"""


class DecodeError(Error):
    """响应体无法解码。"""


class HTTPError(Error):
    """HTTP 失败；.response 为缓冲或流式响应，与调用方式一致。"""

    def __init__(self, response: Response | StreamResponse) -> None:
        self.response = response
        super().__init__(f"{response.status} {response.reason} for {response.url}")


class RedirectError(HTTPError):
    """重定向超过上限，或试图跳转到不安全的目标。"""


@dataclass(frozen=True)
class Response:
    """完全读入的响应；它不持有打开的 socket，也无需调用 close()。"""

    status: int
    headers: Headers
    content: bytes
    url: str
    reason: str = ""

    def __repr__(self) -> str:
        return f"<Response [{self.status}]>"

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def text(self) -> str:
        """按响应声明的字符集解码，缺省用 UTF-8。无效输入会抛出异常。"""
        message = Message()
        message["content-type"] = self.headers.get("content-type", "")
        encoding = message.get_content_charset() or "utf-8"
        try:
            return self.content.decode(encoding)
        except (LookupError, UnicodeError) as exc:
            raise DecodeError(f"Cannot decode response as {encoding}") from exc

    def json(self) -> Any:
        """解析 JSON，支持 UTF-8/16/32 及字节序标记。"""
        try:
            return _json.loads(self.content)
        except (ValueError, UnicodeError) as exc:
            raise DecodeError("Response is not valid JSON") from exc

    def parse(self, decoder: Callable[[bytes], _T]) -> _T:
        """把响应体交给 decoder 调用一次，保留其结果类型与异常。

        例如搭配 Pydantic 使用 response.parse(User.model_validate_json)。
        此方法不会发起请求、不会检查状态码，也不会缓存结果。
        """
        return decoder(self.content)

    def raise_for_status(self) -> Response:
        if self.status >= 400:
            raise HTTPError(self)
        return self


class _BodyReader(io.RawIOBase):
    """受限读取，无需等待整块数据；同时强制遵守 Content-Length。"""

    def __init__(self, raw: Any, limit: int) -> None:
        self.raw, self.limit = raw, limit
        self.gzip = False

    def read(self, size: int = -1) -> bytes:
        # gzip 魔数探测期望恰好两个字节。其他头部读取已处理短读；
        # 响应体读取必须保持增量。
        if self.gzip and size == 2:
            data = self._read_once(2)
            while data and len(data) < 2:
                more = self._read_once(2 - len(data))
                if not more:
                    break
                data += more
            return data
        return self._read_once(size)

    def _read_once(self, size: int) -> bytes:
        size = self.limit if size < 0 else min(size, self.limit)
        if size == 0:
            return b""
        data = self.raw.read1(size)
        # 与 read() 不同，HTTPResponse.read1() 对定长响应体允许提前 EOF。
        # 绝不要把这种提前结束误认为读取成功。
        if not data and self.raw.length not in (None, 0):
            raise http.client.IncompleteRead(b"", self.raw.length)
        return data


class StreamResponse:
    """由流上下文持有的一次性响应体。元数据不会读取响应体。

    iter_bytes() 逐段产出解码后的字节；read() 显式缓冲为 Response。
    在完整读完之前关闭，会丢弃底层连接。
    """

    def __init__(self, raw: Any, url: str, discard: Callable[[Any], None]) -> None:
        self.status, self.reason, self.url = int(raw.status), raw.reason, url
        self.headers = Headers(raw.headers.raw_items())
        self._raw, self._discard = raw, discard
        self._closed = self._started = self._consumed = False
        self._buffered: Response | None = None
        self._error: BaseException | None = None

    def __repr__(self) -> str:
        return f"<StreamResponse [{self.status}]>"

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def consumed(self) -> bool:
        return self._consumed

    def raise_for_status(self) -> Self:
        if self.status >= 400:
            raise HTTPError(self)
        return self

    def close(self) -> None:
        if not self.closed:
            self._closed = True
            try:
                self._raw.close()
            finally:
                if not self.consumed:
                    self._discard(self._raw)

    def iter_bytes(self, chunk_size: int = 65536) -> Iterator[bytes]:
        """只消费一次，每次产出至多 chunk_size 个已解码字节。

        分块可能更小，不代表应用层消息边界。
        gzip 增量解码，并在 EOF 处校验校验和。
        """
        if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size < 1:
            raise ValueError("chunk_size must be a positive integer")
        if self.closed or self._started:
            raise RuntimeError("Stream is closed or its body has already been claimed")
        self._started = True
        return self._iter_bytes(chunk_size)

    def _iter_bytes(self, chunk_size: int) -> Iterator[bytes]:
        reader = _BodyReader(self._raw, chunk_size)
        decoder: gzip.GzipFile | None = None
        try:
            reader.gzip = self.headers.get("content-encoding", "").lower().strip() == "gzip"
            if reader.gzip:
                decoder = gzip.GzipFile(fileobj=reader, mode="rb")
            while True:
                if self.closed:
                    raise RuntimeError("Stream is closed")
                try:
                    data = decoder.read1(chunk_size) if decoder else reader.read(chunk_size)
                except (gzip.BadGzipFile, EOFError, zlib.error) as exc:
                    raise DecodeError("Response is not valid gzip") from exc
                if not data:
                    self._consumed = True
                    break
                yield data
        except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
            error = _network_error(exc, self.url)
            self._error = error
            raise error from exc
        except BaseException as exc:
            if not isinstance(exc, GeneratorExit):
                self._error = exc
            raise
        finally:
            if decoder:
                decoder.close()
            self.close()

    def read(self) -> Response:
        """缓冲未读的响应体；重复调用返回同一个 Response。

        一旦开始 iter_bytes()，read() 无法恢复已产出的字节。
        """
        if self._buffered is None:
            content = b"".join(self.iter_bytes())
            self._buffered = Response(self.status, self.headers, content, self.url, self.reason)
        return self._buffered


class _ReturnResponse(urllib.request.HTTPErrorProcessor):
    # urllib 默认把错误转成异常并自行跟随重定向。
    # 这里保留这两个决策，让所有动词与所有状态码行为一致。
    def http_response(self, request: Any, response: Any) -> Any:
        return response

    https_response = http_response


class _SessionTransport(urllib.request.HTTPHandler, urllib.request.HTTPSHandler):
    """复用直连连接；代理处理交给 urllib。"""

    def __init__(self, context: ssl.SSLContext | None, max_connections: int) -> None:
        urllib.request.HTTPSHandler.__init__(self, context=context)
        self.connections: dict[tuple[str, str], http.client.HTTPConnection] = {}
        self.max_connections = max_connections

    def close(self) -> None:
        for connection in self.connections.values():
            connection.close()
        self.connections.clear()

    def discard(self, response: Any) -> None:
        connection = getattr(response, "_fetch_connection", None)
        for key, cached in list(self.connections.items()):
            if cached is connection:
                del self.connections[key]
                cached.close()

    def do_open(self, http_class: Any, req: Any, **kwargs: Any) -> Any:
        if req.has_proxy() or req._tunnel_host:
            return super().do_open(http_class, req, **kwargs)
        key = (req.type, req.host)
        connection = self.connections.pop(key, None)
        if connection is None:
            connection = http_class(req.host, timeout=req.timeout, **kwargs)
        headers = {name.title(): value for name, value in req.header_items()}
        try:
            connection.timeout = req.timeout
            if connection.sock is not None:
                connection.sock.settimeout(req.timeout)
            connection.request(req.get_method(), req.selector, req.data, headers)
            response: Any = connection.getresponse()
        except BaseException:
            connection.close()
            raise
        reusable = (
            not response.will_close
            and "close"
            not in {token.strip() for token in headers.get("Connection", "").lower().split(",")}
            and response.status != 101
            and not (req.get_method() == "CONNECT" and 200 <= response.status < 300)
        )
        if reusable:
            self.connections[key] = connection
            if len(self.connections) > self.max_connections:
                self.connections.pop(next(iter(self.connections))).close()
        elif connection.sock is not None:
            # 响应的文件对象拥有未读完的响应体。关闭这个 socket 引用，
            # 让它能读完数据而不被额外保留。
            connection.sock.close()
            connection.sock = None
        response.url = req.full_url
        response.msg = response.reason
        response._fetch_connection = connection
        return response


class _SessionOptions(TypedDict, total=False):
    params: Mapping[str, Any] | Iterable[tuple[str, Any]] | None
    headers: Mapping[str, str | None] | None
    json: Any
    data: bytes | str | Mapping[str, Any] | None
    timeout: float | None
    follow_redirects: bool | None
    max_redirects: int | None
    check_status: bool | None


class Session:
    """共享默认值、Cookie 与直连 HTTP 连接复用。

    可作上下文管理器使用，或调用 close()。一个会话只用于串行使用；
    并发工作请使用独立的会话。代理连接不做缓存。已关闭的会话不可复用，
    请求失败也从不自动重试。
    """

    def __init__(
        self,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        follow_redirects: bool = True,
        max_redirects: int = 10,
        check_status: bool = True,
        trust_env: bool = False,
        context: ssl.SSLContext | None = None,
        max_connections: int = 8,
    ) -> None:
        _validate_limits(timeout, max_redirects)
        if (
            isinstance(max_connections, bool)
            or not isinstance(max_connections, int)
            or max_connections < 1
        ):
            raise ValueError("max_connections must be a positive integer")
        self.headers = _headers(headers)
        self.timeout = timeout
        self.follow_redirects = follow_redirects
        self.max_redirects = max_redirects
        self.check_status = check_status
        self.cookies = http.cookiejar.CookieJar(
            http.cookiejar.DefaultCookiePolicy(
                strict_ns_domain=http.cookiejar.DefaultCookiePolicy.DomainStrictNonDomain
            )
        )
        self._transport = _SessionTransport(context, max_connections)
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(None if trust_env else {}),
            self._transport,
            _ReturnResponse(),
        )
        self._closed = False
        self._active = False
        self._stream_response: StreamResponse | None = None

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._stream_response is not None:
            self._stream_response.close()
        self._transport.close()
        self._closed = True

    def __enter__(self) -> Self:
        if self.closed:
            raise RuntimeError("Session is closed")
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def request(self, method: str, url: str, **kwargs: Unpack[_SessionOptions]) -> Response:
        """发送一个缓冲请求，本次调用可覆盖会话默认值。"""
        with self._send(method, url, streaming=False, **kwargs) as response:
            assert isinstance(response, Response)
            return response

    @contextmanager
    def stream(
        self, method: str, url: str, **kwargs: Unpack[_SessionOptions]
    ) -> Iterator[StreamResponse]:
        """在 with 块内打开响应体；退出时关闭任何未读完的剩余部分。

        HTTP 错误在进入时抛出，.response 为已关闭的 StreamResponse。
        设置 check_status=False 可自行检查或读取错误响应体。
        退出本上下文后，才能通过该会话发起下一个请求。
        """
        with self._send(method, url, streaming=True, **kwargs) as response:
            assert isinstance(response, StreamResponse)
            yield response

    @contextmanager
    def _send(
        self,
        method: str,
        url: str,
        *,
        streaming: bool,
        params: Mapping[str, Any] | Iterable[tuple[str, Any]] | None = None,
        headers: Mapping[str, str | None] | None = None,
        json: Any = _UNSET,
        data: bytes | str | Mapping[str, Any] | None = None,
        timeout: float | None = None,
        follow_redirects: bool | None = None,
        max_redirects: int | None = None,
        check_status: bool | None = None,
    ) -> Iterator[Response | StreamResponse]:
        """按会话默认值发送；None 选项继承会话默认值。

        表头按大小写不敏感方式合并。值为 None 的表头会从本次调用中
        移除会话表头；内置传输的默认表头可能仍然生效。
        TLS 上下文与代理发现策略在会话创建时固定。
        """
        if self.closed:
            raise RuntimeError("Session is closed")
        if self._active:
            raise RuntimeError("Exit the active stream context before making another request")
        outgoing = _headers(self.headers)
        for name, value in (headers or {}).items():
            _headers({name: "" if value is None else value})
            if value is None:
                outgoing.pop(name.lower(), None)
            else:
                outgoing[name.lower()] = value
        self._active = True
        try:
            with _request(
                self._opener,
                method,
                url,
                cookies=self.cookies,
                streaming=streaming,
                discard=self._transport.discard,
                params=params,
                headers=outgoing,
                json=json,
                data=data,
                timeout=self.timeout if timeout is None else timeout,
                follow_redirects=self.follow_redirects
                if follow_redirects is None
                else follow_redirects,
                max_redirects=self.max_redirects if max_redirects is None else max_redirects,
                check_status=self.check_status if check_status is None else check_status,
            ) as response:
                if isinstance(response, StreamResponse):
                    self._stream_response = response
                yield response
        finally:
            self._active = False
            self._stream_response = None

    def get(self, url: str, **kwargs: Unpack[_SessionOptions]) -> Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Unpack[_SessionOptions]) -> Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Unpack[_SessionOptions]) -> Response:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Unpack[_SessionOptions]) -> Response:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Unpack[_SessionOptions]) -> Response:
        return self.request("DELETE", url, **kwargs)

    def head(self, url: str, **kwargs: Unpack[_SessionOptions]) -> Response:
        return self.request("HEAD", url, **kwargs)

    def options(self, url: str, **kwargs: Unpack[_SessionOptions]) -> Response:
        return self.request("OPTIONS", url, **kwargs)


def _url(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("url must be a string")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("url must not contain control characters")
    parts = urllib.parse.urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("url must be an absolute http:// or https:// URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("Put credentials in headers, not in the URL")
    # urllib 在连接前会对 authority 部分反转义。对同一视角再做一次校验，
    # 防止编码后的控制字符或分隔符绕过参数校验。
    hostname = urllib.parse.unquote(parts.hostname, errors="strict")
    if any(
        char.isspace() or ord(char) < 32 or ord(char) == 127 or char in "\\/?#@[]"
        for char in hostname
    ) or hostname.count(":") != parts.hostname.count(":"):
        raise ValueError("url hostname contains an invalid character")
    host = parts.hostname.encode("idna").decode("ascii")
    if ":" in host:
        host = f"[{host}]"
    if parts.port is not None:
        host += f":{parts.port}"
    path = urllib.parse.quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = urllib.parse.quote(parts.query, safe="/%?:@!$&'()*+,;=-._~")
    return urllib.parse.urlunsplit((parts.scheme, host, path, query, ""))


def _origin(url: str) -> tuple[str, str | None, int]:
    parts = urllib.parse.urlsplit(url)
    port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
    return parts.scheme, parts.hostname, port


def _headers(values: Mapping[str, str] | None) -> dict[str, str]:
    result = {"user-agent": f"fetch.py/{__version__}", "accept-encoding": "gzip"}
    for name, value in (values or {}).items():
        if not isinstance(name, str) or not _TOKEN.fullmatch(name):
            raise ValueError("Header names must be HTTP tokens")
        if not isinstance(value, str) or any(
            ord(c) < 32 and c != "\t" or ord(c) == 127 for c in value
        ):
            raise ValueError("Header values must be strings without control characters")
        value.encode("latin-1")
        result[name.lower()] = value
    if "transfer-encoding" in result or "content-length" in result:
        raise ValueError("fetch calculates Content-Length; do not set body framing headers")
    return result


def _validate_limits(timeout: float, max_redirects: int) -> None:
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("timeout must be a finite positive number of seconds")
    if isinstance(max_redirects, bool) or not isinstance(max_redirects, int) or max_redirects < 0:
        raise ValueError("max_redirects must be a nonnegative integer")


def request(
    method: str,
    url: str,
    *,
    params: Mapping[str, Any] | Iterable[tuple[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
    json: Any = _UNSET,
    data: bytes | str | Mapping[str, Any] | None = None,
    timeout: float = 30.0,
    follow_redirects: bool = True,
    max_redirects: int = 10,
    check_status: bool = True,
    trust_env: bool = False,
    context: ssl.SSLContext | None = None,
) -> Response:
    """用临时会话发送一次请求；调用结束后不保留任何状态。

    HTTP 4xx/5xx 默认抛出异常，除非 check_status=False。timeout 限制的是
    单个 socket 操作。请求体/查询参数/表头选项见 Session.request。
    trust_env 开启 urllib 的环境变量/系统代理发现。
    context 提供自定义 TLS 上下文，例如用于私有 CA 证书。
    """
    with Session(
        timeout=timeout,
        follow_redirects=follow_redirects,
        max_redirects=max_redirects,
        check_status=check_status,
        trust_env=trust_env,
        context=context,
    ) as session:
        return session.request(method, url, params=params, headers=headers, json=json, data=data)


@contextmanager
def stream(
    method: str,
    url: str,
    *,
    params: Mapping[str, Any] | Iterable[tuple[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
    json: Any = _UNSET,
    data: bytes | str | Mapping[str, Any] | None = None,
    timeout: float = 30.0,
    follow_redirects: bool = True,
    max_redirects: int = 10,
    check_status: bool = True,
    trust_env: bool = False,
    context: ssl.SSLContext | None = None,
) -> Iterator[StreamResponse]:
    """在 with 块内以临时会话流式读取响应。"""
    with (
        Session(
            timeout=timeout,
            follow_redirects=follow_redirects,
            max_redirects=max_redirects,
            check_status=check_status,
            trust_env=trust_env,
            context=context,
        ) as session,
        session.stream(
            method, url, params=params, headers=headers, json=json, data=data
        ) as response,
    ):
        yield response


def _network_error(exc: BaseException, url: str) -> RequestError:
    cause = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(cause, TimeoutError):
        return Timeout(f"Request timed out: {url}")
    return RequestError(f"Request failed: {url}")


def _open(
    opener: urllib.request.OpenerDirector, request: urllib.request.Request, timeout: float
) -> Any:
    """只翻译发起连接阶段的失败，不处理调用方代码的异常。"""
    try:
        return opener.open(request, timeout=timeout)
    except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
        raise _network_error(exc, request.full_url) from exc


@contextmanager
def _request(
    opener: urllib.request.OpenerDirector,
    method: str,
    url: str,
    *,
    cookies: http.cookiejar.CookieJar,
    streaming: bool,
    discard: Callable[[Any], None],
    params: Mapping[str, Any] | Iterable[tuple[str, Any]] | None,
    headers: Mapping[str, str],
    json: Any,
    data: bytes | str | Mapping[str, Any] | None,
    timeout: float,
    follow_redirects: bool,
    max_redirects: int,
    check_status: bool,
) -> Iterator[Response | StreamResponse]:
    """发送一次请求。HTTP 4xx/5xx 抛出 HTTPError，除非 check_status=False。

    params 追加查询参数；序列值会变成重复键。
    json 序列化任意 JSON 值（包括 None）。data 发送字节、UTF-8 文本
    或按表单编码的映射。json 与 data 互斥。

    timeout 是正的 socket 操作超时，不是总截止时间。

    重定向保留方法与请求体，例外：POST 遇 301/302、非 HEAD 方法遇 303
    会变成 GET。跨源跳转时剥离凭据；拒绝 HTTPS 降级到 HTTP 的重定向。
    不做任何自动重试。
    """
    if not isinstance(method, str) or not _TOKEN.fullmatch(method):
        raise ValueError("method must be an HTTP token")
    method = method.upper()
    _validate_limits(timeout, max_redirects)
    if json is not _UNSET and data is not None:
        raise ValueError("Use either json or data, not both")
    url = _url(url)
    if params is not None:
        query = urllib.parse.urlencode(
            cast(Mapping[str, Any], params) if isinstance(params, Mapping) else list(params),
            doseq=True,
        )
        if query:
            url += ("&" if urllib.parse.urlsplit(url).query else "?") + query
    outgoing = _headers(headers)
    body = None
    if json is not _UNSET:
        body = _json.dumps(json, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
            "utf-8"
        )
        outgoing.setdefault("content-type", "application/json")
    elif isinstance(data, Mapping):
        body = urllib.parse.urlencode(data, doseq=True).encode("ascii")
        outgoing.setdefault("content-type", "application/x-www-form-urlencoded")
    elif isinstance(data, str):
        body = data.encode("utf-8")
        outgoing.setdefault("content-type", "text/plain; charset=utf-8")
    elif isinstance(data, bytes):
        body = data
        outgoing.setdefault("content-type", "application/octet-stream")
    elif data is not None:
        raise TypeError("data must be bytes, str, or a mapping")

    started = time.perf_counter()
    status: int | None = None
    hop = 0

    def record(event: str, error: BaseException | None = None) -> None:
        if not _log.isEnabledFor(logging.DEBUG):
            return
        host = urllib.parse.urlsplit(url).hostname
        elapsed = 0.0 if event == "started" else time.perf_counter() - started
        # 日志记录中不包含 URL、表头、请求体或异常文本。
        detail = event
        if status is not None:
            detail += f" -> {status}"
        if error is not None:
            detail += f" [{type(error).__name__}]"
        if event != "started":
            detail += f" ({elapsed:.3f}s)"
        _log.debug(
            "%s %s %s",
            method,
            host,
            detail,
            extra={
                "fetch_event": f"request.{event}",
                "fetch_method": method,
                "fetch_host": host,
                "fetch_status": status,
                "fetch_elapsed": elapsed,
                "fetch_timeout": timeout,
                "fetch_redirects": hop,
                "fetch_error": type(error).__name__ if error is not None else None,
            },
        )

    record("started")
    streamed: StreamResponse | None = None
    error: BaseException | None = None
    try:
        for hop in range(max_redirects + 1):
            status = None
            req = urllib.request.Request(url, data=body, headers=outgoing, method=method)
            cookies.add_cookie_header(req)
            with _open(opener, req, timeout) as raw:
                # 即使缓冲响应体失败，也要保留已收到的状态码。
                status = int(raw.status)
                with closing(StreamResponse(raw, url, discard)) as live:
                    cookies.extract_cookies(raw, req)
                    response = live if streaming else live.read()
                    location = response.headers.get("location")
                    if follow_redirects and status in _REDIRECTS and location:
                        if hop == max_redirects:
                            raise RedirectError(response)
                        try:
                            target = _url(urllib.parse.urljoin(url, location))
                        except (ValueError, UnicodeError) as exc:
                            raise RedirectError(response) from exc
                        if url.startswith("https:") and target.startswith("http:"):
                            raise RedirectError(response)
                        record("redirect")
                        if _origin(url) != _origin(target):
                            for name in ("authorization", "cookie", "proxy-authorization"):
                                outgoing.pop(name, None)
                        outgoing.pop("host", None)
                        if (status in {301, 302} and method == "POST") or (
                            status == 303 and method != "HEAD"
                        ):
                            method, body = "GET", None
                            for name in list(outgoing):
                                if name.startswith("content-"):
                                    del outgoing[name]
                        url = target
                        continue
                    if check_status:
                        response.raise_for_status()
                    if isinstance(response, StreamResponse):
                        streamed = response
                    yield response
                    return
        raise AssertionError("unreachable")
    except BaseException as exc:
        error = exc
        raise
    finally:
        if streamed is not None:
            # 被捕获的响应体失败仍计入事件。应用层异常不改变
            # HTTP 响应体是完整读完还是提前关闭。
            error = streamed._error
        event = (
            "failed"
            if error is not None
            else ("closed" if streamed is not None and not streamed.consumed else "completed")
        )
        record(event, error)


get = partial(request, "GET")
post = partial(request, "POST")
put = partial(request, "PUT")
patch = partial(request, "PATCH")
delete = partial(request, "DELETE")
head = partial(request, "HEAD")
options = partial(request, "OPTIONS")
