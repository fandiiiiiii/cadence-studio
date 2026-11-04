"""Local secret storage.

Windows uses DPAPI (per-user, per-machine encryption) so API keys are never
written in plaintext. On other platforms a 0600 JSON file is used as a
development fallback and the UI shows a warning.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
from ctypes import wintypes
from pathlib import Path

_ENTROPY = b"CadenceStudio/v1"


class SecretStoreError(RuntimeError):
    pass


if sys.platform == "win32":  # pragma: no cover - platform specific

    class _DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _blob(data: bytes):
        buffer = ctypes.create_string_buffer(data, len(data))
        blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
        return blob, buffer

    def _protect(payload: bytes) -> bytes:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        in_blob, in_buffer = _blob(payload)
        entropy_blob, entropy_buffer = _blob(_ENTROPY)
        out_blob = _DataBlob()
        ok = crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            "Cadence Studio secrets",
            ctypes.byref(entropy_blob),
            None,
            None,
            0,
            ctypes.byref(out_blob),
        )
        _ = in_buffer, entropy_buffer
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)

    def _unprotect(payload: bytes) -> bytes:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        in_blob, in_buffer = _blob(payload)
        entropy_blob, entropy_buffer = _blob(_ENTROPY)
        out_blob = _DataBlob()
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            ctypes.byref(entropy_blob),
            None,
            None,
            0,
            ctypes.byref(out_blob),
        )
        _ = in_buffer, entropy_buffer
        if not ok:
            raise SecretStoreError("无法解密本机凭据。请确认使用同一 Windows 用户与电脑。")
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)

else:  # pragma: no cover - platform specific

    def _protect(payload: bytes) -> bytes:
        return b"PLAIN\n" + payload

    def _unprotect(payload: bytes) -> bytes:
        if not payload.startswith(b"PLAIN\n"):
            raise SecretStoreError("当前平台没有系统级凭据加密，且文件格式不可识别。")
        return payload[len(b"PLAIN\n") :]


class SecretStore:
    """A tiny, thread-safe, write-through key/value vault."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._values: dict[str, str] = {}
        self._load()

    @property
    def secure(self) -> bool:
        return sys.platform == "win32"

    def _load(self) -> None:
        with self._lock:
            if not self.path.exists():
                return
            raw = self.path.read_bytes()
            if not raw:
                return
            try:
                decoded = _unprotect(raw).decode("utf-8")
                data = json.loads(decoded)
            except Exception as exc:  # noqa: BLE001
                raise SecretStoreError(f"凭据文件无法读取：{exc}") from exc
            if isinstance(data, dict):
                self._values = {str(k): str(v) for k, v in data.items() if v}

    def _save(self) -> None:
        payload = json.dumps(self._values, ensure_ascii=False).encode("utf-8")
        try:
            encrypted = _protect(payload)
        except Exception as exc:  # noqa: BLE001
            raise SecretStoreError(f"凭据加密失败：{exc}") from exc
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_bytes(encrypted)
        os.replace(tmp, self.path)
        if sys.platform != "win32":
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    def get(self, name: str) -> str:
        with self._lock:
            return self._values.get(name, "")

    def has(self, name: str) -> bool:
        return bool(self.get(name))

    def hint(self, name: str) -> str:
        value = self.get(name)
        if not value:
            return ""
        if len(value) <= 8:
            return "••••"
        return f"{value[:3]}••••{value[-4:]}"

    def set(self, name: str, value: str | None) -> None:
        with self._lock:
            if value is None or value == "":
                self._values.pop(name, None)
            else:
                self._values[name] = value.strip()
            self._save()

    def update(self, values: dict[str, str | None]) -> None:
        with self._lock:
            changed = False
            for name, value in values.items():
                if value is None:
                    continue
                if value == "":
                    if name in self._values:
                        self._values.pop(name, None)
                        changed = True
                else:
                    self._values[name] = value.strip()
                    changed = True
            if changed:
                self._save()

    def delete(self, name: str) -> None:
        self.update({name: ""})

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._values)
