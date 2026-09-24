"""Threaded, bounded JSON-RPC transport for stdio language servers."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from queue import Empty, Full, Queue
import math
import threading
import time
from typing import Any, Callable

from .semantic_lsp_framing import LspFramingError, encode_message, read_message
from .semantic_lsp_process import ManagedLanguageServerProcess
from .semantic_lsp_protocol import (
    CONTENT_MODIFIED,
    LspProtocolError,
    LspRemoteError,
    classify_message,
    make_error_response,
    make_notification,
    make_request,
    make_response,
    parse_response,
)
from .semantic_lsp_types import ServerSpec


class LanguageServerTerminatedError(RuntimeError):
    pass


class LspRequestTimeout(TimeoutError):
    pass


class TooManyPendingRequests(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _PendingResult:
    result: Any = None
    error: BaseException | None = None


RequestHandler = Callable[[Any], Any]
NotificationHandler = Callable[[Any], None]
TerminationHandler = Callable[[BaseException | None], None]


class StdioJsonRpcTransport:
    def __init__(
        self,
        spec: ServerSpec,
        *,
        content_modified_retry_methods: frozenset[str] = frozenset(),
        max_content_modified_retries: int = 2,
        process: ManagedLanguageServerProcess | None = None,
    ):
        if type(max_content_modified_retries) is not int or not 0 <= max_content_modified_retries <= 10:
            raise ValueError("max_content_modified_retries outside supported bounds")
        self.spec = spec
        self.process = process or ManagedLanguageServerProcess(spec)
        self.content_modified_retry_methods = content_modified_retry_methods
        self.max_content_modified_retries = max_content_modified_retries
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._next_id = 1
        self._pending: dict[int, Queue[_PendingResult]] = {}
        self._request_handlers: dict[str, RequestHandler] = {}
        self._notification_handlers: dict[str, list[NotificationHandler]] = {}
        self._termination_handlers: list[TerminationHandler] = []
        self._reader: threading.Thread | None = None
        self._closed = threading.Event()
        self._terminated = threading.Event()
        self._termination_error: BaseException | None = None
        self._server_request_slots = threading.BoundedSemaphore(16)
        self._server_request_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="px-lsp-server-request")

    def register_request_handler(self, method: str, handler: RequestHandler) -> None:
        if not method or not callable(handler):
            raise ValueError("request handler requires method and callable")
        self._request_handlers[method] = handler

    def register_notification_handler(self, method: str, handler: NotificationHandler) -> None:
        if not method or not callable(handler):
            raise ValueError("notification handler requires method and callable")
        self._notification_handlers.setdefault(method, []).append(handler)

    def register_termination_handler(self, handler: TerminationHandler) -> None:
        if not callable(handler):
            raise ValueError("termination handler must be callable")
        self._termination_handlers.append(handler)

    def start(self) -> None:
        if self._reader is not None:
            raise RuntimeError("transport already started")
        try:
            self.process.start()
            self._reader = threading.Thread(
                target=self._reader_loop,
                name=f"px-lsp-reader-{self.spec.server_id}",
                daemon=True,
            )
            self._reader.start()
        except BaseException:
            self.process.terminate_tree(timeout=self.spec.shutdown_timeout_seconds)
            raise

    def is_running(self) -> bool:
        return not self._closed.is_set() and self.process.is_running() and not self._terminated.is_set()

    def _allocate_pending(self) -> tuple[int, Queue[_PendingResult]]:
        with self._pending_lock:
            if len(self._pending) >= self.spec.max_pending_requests:
                raise TooManyPendingRequests("language-server pending request budget exhausted")
            request_id = self._next_id
            self._next_id += 1
            queue: Queue[_PendingResult] = Queue(maxsize=1)
            self._pending[request_id] = queue
            return request_id, queue

    def _finish_pending(self, request_id: int, item: _PendingResult) -> bool:
        with self._pending_lock:
            queue = self._pending.get(request_id)
        if queue is None:
            return False
        try:
            queue.put_nowait(item)
        except Full:
            return False
        return True

    def _pop_pending(self, request_id: int) -> None:
        with self._pending_lock:
            self._pending.pop(request_id, None)

    def _send(self, payload: dict[str, Any]) -> None:
        if self._closed.is_set() or self._terminated.is_set():
            raise LanguageServerTerminatedError("language-server transport is closed")
        framed = encode_message(payload, max_message_bytes=self.spec.max_message_bytes)
        with self._write_lock:
            try:
                stream = self.process.stdin
                stream.write(framed)
                stream.flush()
            except (BrokenPipeError, OSError) as exc:
                self._terminate(LanguageServerTerminatedError(f"language-server write failed: {exc}"))
                raise LanguageServerTerminatedError("language-server write failed") from exc

    def notify(self, method: str, params: Any = None) -> None:
        self._send(make_notification(method, params))

    def request(self, method: str, params: Any = None, *, timeout: float | None = None) -> Any:
        attempts = 0
        while True:
            try:
                return self._request_once(method, params, timeout=timeout)
            except LspRemoteError as exc:
                if (
                    exc.code == CONTENT_MODIFIED
                    and method in self.content_modified_retry_methods
                    and attempts < self.max_content_modified_retries
                ):
                    attempts += 1
                    time.sleep(min(0.05 * attempts, 0.2))
                    continue
                raise

    def _request_once(self, method: str, params: Any, *, timeout: float | None) -> Any:
        request_id, queue = self._allocate_pending()
        effective_timeout = self.spec.request_timeout_seconds if timeout is None else timeout
        if (
            isinstance(effective_timeout, bool)
            or not isinstance(effective_timeout, (int, float))
            or not math.isfinite(float(effective_timeout))
            or effective_timeout <= 0
            or effective_timeout > 3600
        ):
            self._pop_pending(request_id)
            raise ValueError("request timeout must be finite, > 0 and <= 3600 seconds")
        try:
            self._send(make_request(method, request_id, params))
            try:
                item = queue.get(timeout=effective_timeout)
            except Empty as exc:
                # Remove before cancellation so any racing late response is ignored.
                self._pop_pending(request_id)
                try:
                    self.notify("$/cancelRequest", {"id": request_id})
                except LanguageServerTerminatedError:
                    pass
                raise LspRequestTimeout(f"LSP request timed out: {method}") from exc
            if item.error is not None:
                raise item.error
            return item.result
        finally:
            self._pop_pending(request_id)

    def cancel(self, request_id: int) -> None:
        self.notify("$/cancelRequest", {"id": request_id})

    def _reader_loop(self) -> None:
        error: BaseException | None = None
        try:
            while not self._closed.is_set():
                payload = read_message(self.process.stdout, max_message_bytes=self.spec.max_message_bytes)
                kind = classify_message(payload)
                if kind == "response":
                    parsed = parse_response(payload)
                    if isinstance(parsed.request_id, int):
                        item = _PendingResult(parsed.result, parsed.error)
                        self._finish_pending(parsed.request_id, item)
                elif kind == "request":
                    self._dispatch_server_request(payload)
                else:
                    self._dispatch_notification(payload)
        except EOFError as exc:
            if not self._closed.is_set():
                error = LanguageServerTerminatedError("language-server stdout closed")
                error.__cause__ = exc
        except (LspFramingError, LspProtocolError, OSError) as exc:
            if not self._closed.is_set():
                error = LanguageServerTerminatedError(f"language-server protocol channel failed: {exc}")
                error.__cause__ = exc
        except BaseException as exc:
            if not self._closed.is_set():
                error = LanguageServerTerminatedError(f"language-server reader failed: {exc}")
                error.__cause__ = exc
        finally:
            self._terminate(error)

    def _dispatch_notification(self, payload: dict[str, Any]) -> None:
        method = payload["method"]
        params = payload.get("params", {})
        for handler in tuple(self._notification_handlers.get(method, ())):
            try:
                handler(params)
            except BaseException:
                # Notifications are advisory. One observer must not kill the protocol channel.
                continue

    def _dispatch_server_request(self, payload: dict[str, Any]) -> None:
        request_id = payload["id"]
        method = payload["method"]
        params = payload.get("params", {})
        if not self._server_request_slots.acquire(blocking=False):
            self._send(make_error_response(request_id, -32000, "PX client request-handler budget exhausted"))
            return

        def work() -> None:
            try:
                handler = self._request_handlers.get(method)
                if handler is None:
                    response = make_error_response(request_id, -32601, f"method not handled by PX client: {method}")
                else:
                    try:
                        response = make_response(request_id, handler(params))
                    except BaseException as exc:
                        response = make_error_response(request_id, -32603, "PX client handler failed", str(exc)[:1024])
                try:
                    self._send(response)
                except LanguageServerTerminatedError:
                    pass
            finally:
                self._server_request_slots.release()

        try:
            self._server_request_pool.submit(work)
        except RuntimeError:
            self._server_request_slots.release()

    def _terminate(self, error: BaseException | None) -> None:
        if self._terminated.is_set():
            return
        self._termination_error = error
        self._terminated.set()
        pending_error = error or LanguageServerTerminatedError("language-server transport stopped")
        with self._pending_lock:
            pending = tuple(self._pending.values())
        for queue in pending:
            try:
                queue.put_nowait(_PendingResult(error=pending_error))
            except Full:
                pass
        for handler in tuple(self._termination_handlers):
            try:
                handler(error)
            except BaseException:
                continue

    def close(self, *, terminate_process: bool = False) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        # The transport owns its subprocess.  A close operation may not leave a
        # live language server behind, regardless of whether the caller reached
        # the graceful LSP shutdown path first.  ``terminate_process`` remains
        # accepted for API compatibility but process liveness is authoritative.
        if self.process.is_running():
            self.process.terminate_tree(timeout=self.spec.shutdown_timeout_seconds)
        else:
            self.process.close_streams()
        self._server_request_pool.shutdown(wait=False, cancel_futures=True)
        if self._reader is not None and self._reader is not threading.current_thread():
            self._reader.join(timeout=0.5)
        self._terminate(None)

    @property
    def termination_error(self) -> BaseException | None:
        return self._termination_error
