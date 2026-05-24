"""
网络与代理探测。

在 WSL2 / 直连 / 本地代理（Clash、飞鸟等）环境下自动选择可用通道访问 Binance API。

环境变量:
  CRYPTO_NO_PROXY=1     强制直连
  CRYPTO_PROXY_URL      指定代理，如 http://172.28.144.1:7890
  CRYPTO_PROXY_PORT     优先尝试的端口
  HTTPS_PROXY / HTTP_PROXY  系统代理（可用时自动采用）
"""

from __future__ import annotations

import os
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import requests

_BINANCE_PING = "https://api.binance.com/api/v3/ping"


class BinanceConnectivityError(RuntimeError):
    """无法从当前环境访问 Binance（直连与常见本机代理均失败）。"""


def _http_proxy_from_environ() -> str | None:
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        raw = (os.environ.get(key) or "").strip().strip('"').strip("'")
        if not raw or raw.lower() in ("none", "false", "0", "off"):
            continue
        low = raw.lower()
        if low.startswith("socks"):
            continue
        if not (low.startswith("http://") or low.startswith("https://")):
            raw = "http://" + raw.lstrip("/")
        try:
            u = urlparse(raw)
            if not u.hostname:
                continue
            port = u.port or 7890
            return f"http://{u.hostname}:{port}"
        except Exception:
            continue
    return None


def _is_wsl() -> bool:
    try:
        v = open("/proc/version", encoding="utf-8", errors="ignore").read().lower()
    except OSError:
        return False
    return "microsoft" in v or "wsl" in v


def _no_proxy_env() -> bool:
    return (os.environ.get("CRYPTO_NO_PROXY") or "").strip().lower() in ("1", "true", "yes", "on")


def _looks_like_ipv4(s: str) -> bool:
    parts = s.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except ValueError:
        return False


def _wsl_default_gateway() -> str | None:
    try:
        out = subprocess.check_output(["ip", "-4", "route", "show", "default"], timeout=3, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "default" and parts[1] == "via":
            return parts[2]
    return None


def _wsl_nameserver() -> str | None:
    try:
        with open("/etc/resolv.conf", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.startswith("nameserver "):
                    return line.split()[1].strip()
    except OSError:
        pass
    return None


def _windows_vethernet_wsl_ip() -> str | None:
    ps = (
        "$a = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
        "Where-Object { $_.InterfaceAlias -match 'WSL' -and $_.IPAddress -notlike '169.254*' }; "
        "if ($a) { $a[0].IPAddress }"
    )
    try:
        out = subprocess.check_output(
            ["powershell.exe", "-NoProfile", "-Command", ps],
            timeout=12,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    for line in out.splitlines():
        s = line.strip()
        if _looks_like_ipv4(s):
            return s
    return None


def _host_docker_internal() -> str | None:
    try:
        return socket.gethostbyname("host.docker.internal")
    except OSError:
        return None


def _hosts_to_try() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []

    def add(h: str) -> None:
        h = h.strip()
        if h and h not in seen and _looks_like_ipv4(h):
            seen.add(h)
            out.append(h)

    if not _is_wsl():
        add("127.0.0.1")
        return out

    add("127.0.0.1")
    if w := _windows_vethernet_wsl_ip():
        add(w)
    if hdi := _host_docker_internal():
        add(hdi)
    add(_wsl_default_gateway() or "")
    add(_wsl_nameserver() or "")
    return out


def _ports_to_try() -> list[int]:
    raw = (os.environ.get("CRYPTO_PROXY_PORT") or "").strip()
    ports: list[int] = [int(raw)] if raw.isdigit() else []
    for p in (7890, 6478, 7897, 10809, 7891):
        if p not in ports:
            ports.append(p)
    return ports


def _session_no_env() -> requests.Session:
    s = requests.Session()
    try:
        s.trust_env = False
    except AttributeError:
        pass
    return s


def _direct_binance_ok(timeout: float = 5.0) -> bool:
    try:
        return _session_no_env().get(_BINANCE_PING, timeout=timeout).status_code == 200
    except requests.RequestException:
        return False


def _via_proxy_binance_ok(proxy_base: str, timeout: float = 6.0) -> bool:
    try:
        r = _session_no_env().get(
            _BINANCE_PING,
            proxies={"http": proxy_base, "https": proxy_base},
            timeout=timeout,
        )
        return r.status_code == 200
    except requests.RequestException:
        return False


def _discover_working_proxy_base() -> str:
    bases: list[str] = []
    if ep := (_http_proxy_from_environ() or "").strip().rstrip("/"):
        bases.append(ep)
    bases.extend(f"http://{h}:{p}" for h in _hosts_to_try() for p in _ports_to_try())

    seen: set[str] = set()
    uniq: list[str] = []
    for b in bases:
        if b not in seen:
            seen.add(b)
            uniq.append(b)

    if not uniq:
        return ""

    probe_timeout = 5.0
    with ThreadPoolExecutor(max_workers=min(12, len(uniq))) as pool:
        future_map = {pool.submit(_via_proxy_binance_ok, b, probe_timeout): b for b in uniq}
        for fut in as_completed(future_map, timeout=probe_timeout + 15.0):
            try:
                if fut.result():
                    return future_map[fut]
            except Exception:
                pass
    return ""


@lru_cache(maxsize=1)
def _cached_proxy_base_url() -> str:
    if _no_proxy_env():
        return ""

    if explicit := (os.environ.get("CRYPTO_PROXY_URL") or "").strip():
        return explicit.rstrip("/")

    if env_px := (_http_proxy_from_environ() or "").strip().rstrip("/"):
        if _via_proxy_binance_ok(env_px, timeout=8.0):
            return env_px

    if _direct_binance_ok(timeout=3.5):
        return ""

    if found := _discover_working_proxy_base():
        return found

    raise BinanceConnectivityError(
        "无法经代理或直连访问 https://api.binance.com 。\n"
        "可尝试: export CRYPTO_PROXY_URL=http://<host>:<port>\n"
        "或直连: export CRYPTO_NO_PROXY=1"
    )


def describe_network() -> str:
    """返回当前网络模式描述。"""
    u = _cached_proxy_base_url()
    return u if u else "(直连)"


def ccxt_binance_options() -> dict[str, Any]:
    """构建 ccxt.binance 初始化参数字典。"""
    opts: dict[str, Any] = {"enableRateLimit": True}
    if _no_proxy_env():
        return opts
    base = _cached_proxy_base_url()
    if base:
        opts["proxies"] = {"http": base, "https": base}
    return opts
