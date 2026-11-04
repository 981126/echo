"""R-241：进程级共享 httpx.Client 池（按 base_url + follow_redirects + trust_env 维度复用连接）。

背景（审计 L7）：TikHub 媒体卡/封面/头像/联网搜索/DeepSeek Fetch 每次请求都新建
`httpx.Client`（或顶层 `httpx.get/post`），反复做 TCP/TLS 握手；本模块提供跨调用共享的
Client，一次建连后续 keep-alive 复用。

约定：
- Client **线程安全**（httpx 官方保证），可被多个 service/线程共享；
- `get_client()` 只负责「取/建」客户端；**每次请求请显式传 timeout**（本模块不把 timeout
  固化到请求里，避免不同业务超时互相覆盖）；
- base_url 仅作为连接池分区键（可传服务根地址，也可传业务标识如 "cdn"）；`follow_redirects`、
  `trust_env` 与 base_url 一起构成 key；
- R-246：`trust_env=False` 时不读取系统/环境代理（macOS 系统代理会让 TikHub 请求走 CONNECT
  隧道，httpcore 隧道建立失败会泄漏连接池槽位）；默认 True 保持其它服务旧行为；
- R-246：`reset_client()` 关闭并丢弃指定 Client，下次 `get_client()` 重建全新连接池
  （TikHub 遇 `PoolTimeout` 时自愈用）；
- 测试 monkeypatch `httpx.Client` 时会重建客户端（缓存条目的类身份不匹配即丢弃），避免
  跨用例复用测试替身；
- 进程退出时 `close_all()` 关闭全部连接（atexit 注册）。
"""

from __future__ import annotations

import atexit
import threading

import httpx

# 每服务连接上限：单进程内并发请求数远小于此（uvicorn 单进程 + 线程池并发 ≤ 数十）
_DEFAULT_LIMITS = httpx.Limits(max_connections=16, max_keepalive_connections=8, keepalive_expiry=120)
_DEFAULT_TIMEOUT = httpx.Timeout(connect=15, read=60, write=60, pool=20)

_CLIENTS: dict[tuple[str, bool, bool], tuple[httpx.Client, type]] = {}
_LOCK = threading.Lock()


def get_client(
    base_url: str = "",
    *,
    timeout: httpx.Timeout | float | None = None,
    follow_redirects: bool = False,
    trust_env: bool = True,
) -> httpx.Client:
    """取（或惰性创建）共享 httpx.Client。

    Args:
        base_url: 连接池分区键（服务根地址或业务标识）；不同业务可共用 ""，
            连接池会按实际 host 自动分池。
        timeout: 仅影响新建时的默认超时；**业务请求请显式传 timeout**。
        follow_redirects: 是否自动跟随重定向（与 base_url 一起构成缓存 key）。
        trust_env: 是否读取系统/环境代理；默认 True（旧行为）。R-246：TikHub 传 False
            直连，避免 macOS 系统代理隧道建立失败泄漏连接池槽位。
    """
    key = ((base_url or "").rstrip("/"), bool(follow_redirects), bool(trust_env))
    with _LOCK:
        cached = _CLIENTS.get(key)
        if cached is not None:
            client, client_cls = cached
            # 测试里 monkeypatch httpx.Client 时丢弃旧替身，避免跨用例复用（生产恒等）
            if client_cls is httpx.Client:
                return client
        client = httpx.Client(
            timeout=timeout if timeout is not None else _DEFAULT_TIMEOUT,
            follow_redirects=follow_redirects,
            limits=_DEFAULT_LIMITS,
            trust_env=trust_env,
        )
        _CLIENTS[key] = (client, httpx.Client)
        return client


def reset_client(
    base_url: str = "",
    *,
    follow_redirects: bool = False,
    trust_env: bool = True,
) -> bool:
    """R-246：关闭并丢弃指定共享 Client；下次 `get_client` 重建全新连接池。

    Args:
        base_url: 与 `get_client` 相同的分区键。
        follow_redirects / trust_env: 与 `get_client` 一致，共同构成缓存 key。

    Returns:
        True=命中并已摘除/关闭；False=缓存里没有该 Client（可能已被其它线程重置）。
    """
    key = ((base_url or "").rstrip("/"), bool(follow_redirects), bool(trust_env))
    with _LOCK:
        entry = _CLIENTS.pop(key, None)
    if entry is None:
        return False
    try:
        entry[0].close()
    except Exception:  # noqa: BLE001 关闭失败不影响后续重建
        pass
    return True


def close_all() -> None:
    """关闭全部共享 Client（atexit；测试也可主动调用）。"""
    with _LOCK:
        entries = list(_CLIENTS.values())
        _CLIENTS.clear()
    for client, _cls in entries:
        try:
            client.close()
        except Exception:  # noqa: BLE001 关闭失败不影响退出
            pass


atexit.register(close_all)
