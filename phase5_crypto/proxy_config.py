"""
WSL2 下 Windows 侧 VPN/本地代理（飞鸟、Clash 等）常见端口 7890、7897。
在 WSL 内访问 127.0.0.1 未必等于 Windows；镜像网络下也可能与 10.255.255.254
等 nameserver 行为不一致。

本模块在首次使用时自动探测：
  1) 环境变量 HTTPS_PROXY / HTTP_PROXY（WSL 常与 Windows 同步，如 127.0.0.1:6478）
  2) 直连 api.binance.com 是否可用 → 不用代理
  3) 否则并行尝试 本机/WSL 网关/Windows vEthernet(WSL)/常见端口，
     用「经代理访问 Binance /api/v3/ping」验证。

环境变量:
  CRYPTO_NO_PROXY=1       强制直连（忽略系统代理）
  CRYPTO_PROXY_URL        指定代理，如 http://172.28.144.1:7890
  CRYPTO_PROXY_PORT       优先尝试的端口（仍会扫常见备用端口）
  HTTPS_PROXY / HTTP_PROXY  若已设置且可用，会自动采用（无需再设 CRYPTO_PROXY_URL）

飞鸟等需在软件内开启「允许局域网连接」，否则仅监听 127.0.0.1 时
从 WSL 经非环回 IP 无法连上。
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


def _http_proxy_from_environ() -> str | None:
    """
    读取 shell 里的 HTTPS_PROXY / HTTP_PROXY 等（WSL 里常由 Windows 同步为 127.0.0.1:端口）。
    忽略 SOCKS；无 scheme 时补 http://。
    """
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
            port = u.port
            if port is None:
                port = 7890
            return f"http://{u.hostname}:{port}"
        except Exception:
            continue
    return None


class BinanceConnectivityError(RuntimeError):
    """无法从当前环境访问 Binance（直连与常见本机代理均失败）。"""


def _is_wsl() -> bool:
    try:
        v = open("/proc/version", encoding="utf-8", errors="ignore").read().lower()
    except OSError:
        return False
    return "microsoft" in v or "wsl" in v


def _no_proxy_env() -> bool:
    return (os.environ.get("CRYPTO_NO_PROXY") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def no_proxy_enforced() -> bool:
    return _no_proxy_env()


def _wsl_default_gateway() -> str | None:
    try:
        out = subprocess.check_output(
            ["ip", "-4", "route", "show", "default"],
            timeout=3,
            text=True,
        )
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
    """在 WSL 里调 Windows PowerShell，取 vEthernet(WSL) 在 Windows 上的 IPv4（连代理常用）。"""
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


def _looks_like_ipv4(s: str) -> bool:
    parts = s.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except ValueError:
        return False


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
    w = _windows_vethernet_wsl_ip()
    if w:
        add(w)
    hdi = _host_docker_internal()
    if hdi:
        add(hdi)
    add(_wsl_default_gateway() or "")
    add(_wsl_nameserver() or "")
    return out


def _ports_to_try() -> list[int]:
    raw = (os.environ.get("CRYPTO_PROXY_PORT") or "").strip()
    ports: list[int] = []
    if raw.isdigit():
        ports.append(int(raw))
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
    s = _session_no_env()
    try:
        r = s.get(_BINANCE_PING, timeout=timeout)
        return r.status_code == 200
    except requests.RequestException:
        return False


def _via_proxy_binance_ok(proxy_base: str, timeout: float = 6.0) -> bool:
    s = _session_no_env()
    p = {"http": proxy_base, "https": proxy_base}
    try:
        r = s.get(_BINANCE_PING, proxies=p, timeout=timeout)
        return r.status_code == 200
    except requests.RequestException:
        return False


@lru_cache(maxsize=1)
def _cached_proxy_base_url() -> str:
    """
    返回可带 ccxt 的代理根 URL；空字符串表示不使用代理（直连已通或探测失败走直连）。
    """
    if _no_proxy_env():
        return ""

    explicit = (os.environ.get("CRYPTO_PROXY_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")

    env_px = (_http_proxy_from_environ() or "").strip().rstrip("/")
    if env_px and _via_proxy_binance_ok(env_px, timeout=8.0):
        return env_px

    if _direct_binance_ok(timeout=3.5):
        return ""

    found = _discover_working_proxy_base()
    if found:
        return found

    raise BinanceConnectivityError(
        "无法经代理或直连访问 https://api.binance.com 。\n"
        "1) 若 shell 里已有 HTTPS_PROXY（如飞鸟同步的 127.0.0.1:6478），请确认该端口为 HTTP 混合代理且进程已启动。\n"
        "2) 飞鸟可开启「允许局域网连接」；在 Windows「ipconfig」取「vEthernet (WSL …)」的 IPv4，执行:\n"
        "   export CRYPTO_PROXY_URL=http://<该IPv4>:<HTTP代理端口>\n"
        "3) 若本机可直连币安: export CRYPTO_NO_PROXY=1 后再运行。"
    )


def _discover_working_proxy_base() -> str:
    """并行探测，尽快找到能访问 Binance 的 HTTP 代理。"""
    bases: list[str] = []
    ep = (_http_proxy_from_environ() or "").strip().rstrip("/")
    if ep:
        bases.append(ep)
    bases.extend(f"http://{h}:{p}" for h in _hosts_to_try() for p in _ports_to_try())
    seen: set[str] = set()
    uniq: list[str] = []
    for b in bases:
        if b not in seen:
            seen.add(b)
            uniq.append(b)
    bases = uniq
    if not bases:
        return ""

    workers = min(12, len(bases))
    probe_timeout = 5.0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(_via_proxy_binance_ok, b, probe_timeout): b for b in bases}
        for fut in as_completed(future_map, timeout=probe_timeout + 15.0):
            try:
                if fut.result():
                    return future_map[fut]
            except Exception:
                pass
    return ""


def default_proxy_base_url() -> str:
    u = _cached_proxy_base_url()
    return u if u else "(直连)"


def clear_proxy_url_cache() -> None:
    _cached_proxy_base_url.cache_clear()


def proxies_dict() -> dict[str, str] | None:
    if _no_proxy_env():
        return None
    base = _cached_proxy_base_url()
    if not base:
        return None
    return {"http": base, "https": base}


def ccxt_binance_options() -> dict[str, Any]:
    opts: dict[str, Any] = {"enableRateLimit": True}
    p = proxies_dict()
    if p is not None:
        opts["proxies"] = p
    return opts
