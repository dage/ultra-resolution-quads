"""
ComfyUI client utilities for running API workflows from Python.
Provides a small HTTP+WebSocket wrapper and readable, end-user errors.
Designed for CLI tools in this repo (experiments/ and backend/tools/).
"""

import json
import socket
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import requests


@dataclass(frozen=True)
class ComfyUIImageRef:
    filename: str
    subfolder: str
    folder_type: str


class ComfyUIError(RuntimeError):
    def __init__(self, message: str, *, hint: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.hint = hint
        self.details = details or {}

    def __str__(self) -> str:
        base = super().__str__()
        if self.hint:
            return f"{base}\nHint: {self.hint}"
        return base


def _ws_url(server_address: str, client_id: str) -> str:
    return f"ws://{server_address}/ws?clientId={client_id}"


def _http_url(server_address: str, path: str) -> str:
    return f"http://{server_address}{path}"


def _explain_connection_error(server_address: str, exc: BaseException) -> ComfyUIError:
    return ComfyUIError(
        f"Cannot connect to ComfyUI at {server_address}.",
        hint="Start ComfyUI and use the correct host:port (the desktop app often uses 127.0.0.1:8000).",
        details={"exception_type": type(exc).__name__, "exception": str(exc)},
    )


def _raise_for_status(resp: requests.Response, *, server_address: str) -> None:
    if resp.ok:
        return
    content_type = (resp.headers.get("content-type") or "").lower()
    body: Any = None
    if "application/json" in content_type:
        try:
            body = resp.json()
        except Exception:
            body = None
    message = f"ComfyUI request failed ({resp.status_code}) {resp.request.method} {resp.url}"
    hint = None
    if resp.status_code == 404:
        hint = "Check your ComfyUI version and server address; the endpoint may not exist."
    elif resp.status_code in (401, 403):
        hint = "Check ComfyUI authentication / reverse proxy settings."
    elif resp.status_code >= 500:
        hint = "ComfyUI returned a server error; check its console logs for details."
    raise ComfyUIError(message, hint=hint, details={"server": server_address, "body": body, "text": resp.text[:2000]})


class ComfyUIClient:
    def __init__(self, server_address: str, client_id: str, request_timeout_s: float = 60.0):
        try:
            import websocket  # type: ignore[import-not-found]  # pip install websocket-client
        except ModuleNotFoundError as e:
            raise ModuleNotFoundError(
                "Missing dependency 'websocket-client'. Install it with: pip install websocket-client"
            ) from e

        self.server_address = server_address
        self.client_id = client_id
        self._timeout = float(request_timeout_s)
        self._http = requests.Session()
        self._http.headers.update({"User-Agent": "ultra-resolution-quads/comfyui-client"})
        self._ws_timeout_exc = getattr(websocket, "WebSocketTimeoutException", None)

        self.ws = websocket.WebSocket()
        try:
            self.ws.connect(_ws_url(self.server_address, self.client_id), timeout=self._timeout)
        except (OSError, socket.error, Exception) as e:
            raise _explain_connection_error(self.server_address, e) from e

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass
        try:
            self._http.close()
        except Exception:
            pass

    def upload_image(self, filepath: Path, *, overwrite: bool = True) -> str:
        url = _http_url(self.server_address, "/upload/image")
        with filepath.open("rb") as f:
            try:
                resp = self._http.post(
                    url,
                    files={"image": f},
                    data={"overwrite": "true" if overwrite else "false"},
                    timeout=self._timeout,
                )
            except requests.RequestException as e:
                raise _explain_connection_error(self.server_address, e) from e
        _raise_for_status(resp, server_address=self.server_address)
        data = resp.json()
        name = data.get("name") or data.get("filename") or filepath.name
        return str(name)

    def queue_prompt(self, workflow: Dict[str, Any]) -> str:
        url = _http_url(self.server_address, "/prompt")
        try:
            resp = self._http.post(url, json={"prompt": workflow, "client_id": self.client_id}, timeout=self._timeout)
        except requests.RequestException as e:
            raise _explain_connection_error(self.server_address, e) from e
        _raise_for_status(resp, server_address=self.server_address)
        data = resp.json()
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI /prompt did not return prompt_id: {data}")
        return str(prompt_id)

    def wait_for_prompt(self, prompt_id: str, timeout_s: float) -> None:
        deadline = time.time() + float(timeout_s)
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for prompt_id={prompt_id}")
            self.ws.settimeout(min(self._timeout, max(0.1, remaining)))
            try:
                out = self.ws.recv()
            except (TimeoutError, socket.timeout) as _:
                continue
            except Exception as e:
                if self._ws_timeout_exc is not None and isinstance(e, self._ws_timeout_exc):
                    continue
                raise ComfyUIError(
                    f"Lost WebSocket connection to ComfyUI while waiting for prompt_id={prompt_id}.",
                    hint="Check the ComfyUI console for crashes or restarts.",
                    details={"server": self.server_address, "prompt_id": prompt_id, "exception": str(e)},
                ) from e
            if not isinstance(out, str):
                continue
            msg = json.loads(out)
            msg_type = msg.get("type")
            if msg_type == "execution_error":
                data = msg.get("data") or {}
                node_id = data.get("node_id") or data.get("node") or "unknown"
                exception_type = data.get("exception_type") or "ExecutionError"
                exception_message = data.get("exception_message") or data.get("exception") or ""
                hint = "Check ComfyUI logs for the full traceback."
                if "not found" in str(exception_message).lower() or "missing" in str(exception_message).lower():
                    hint = "A common cause is a missing/typo model name; verify model filenames in the workflow."
                raise ComfyUIError(
                    f"ComfyUI execution error at node {node_id} ({exception_type}). {exception_message}".strip(),
                    hint=hint,
                    details={"server": self.server_address, "prompt_id": prompt_id, "data": data},
                )
            if msg_type != "executing":
                continue
            data = msg.get("data") or {}
            if data.get("prompt_id") != prompt_id:
                continue
            if data.get("node") is None:
                return

    def get_history(self, prompt_id: str) -> Dict[str, Any]:
        url = _http_url(self.server_address, f"/history/{prompt_id}")
        try:
            resp = self._http.get(url, timeout=self._timeout)
        except requests.RequestException as e:
            raise _explain_connection_error(self.server_address, e) from e
        _raise_for_status(resp, server_address=self.server_address)
        return resp.json()

    def get_image_data(self, image_ref: ComfyUIImageRef) -> bytes:
        query = urllib.parse.urlencode(
            {"filename": image_ref.filename, "subfolder": image_ref.subfolder, "type": image_ref.folder_type}
        )
        url = _http_url(self.server_address, f"/view?{query}")
        try:
            resp = self._http.get(url, timeout=self._timeout)
        except requests.RequestException as e:
            raise _explain_connection_error(self.server_address, e) from e
        _raise_for_status(resp, server_address=self.server_address)
        return resp.content


def first_image_ref_from_history(history_for_prompt: Dict[str, Any], preferred_node: str) -> Optional[ComfyUIImageRef]:
    outputs = history_for_prompt.get("outputs") or {}
    if preferred_node in outputs and (outputs[preferred_node] or {}).get("images"):
        img = outputs[preferred_node]["images"][0]
        return ComfyUIImageRef(img["filename"], img.get("subfolder", ""), img.get("type", "output"))

    for _node_id, node_out in outputs.items():
        images = (node_out or {}).get("images") or []
        if images:
            img = images[0]
            return ComfyUIImageRef(img["filename"], img.get("subfolder", ""), img.get("type", "output"))
    return None
