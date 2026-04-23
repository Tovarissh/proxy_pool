# -*- coding: utf-8 -*-
"""
代理池独立模块 - 将SMTP系统中的代理IP池代码拆分为独立Python包
提供代理管理、调度、健康检测、连接器等功能
"""
from .models import (
    ProxyEntry,
    ProxyProto,
    ProxyStatus,
    ApiProxyConfig,
    RotateConfig,
    PoolConfig,
)
from .pool import ProxyPool, MixedPool
from .fetcher import FileProxyFetcher, ApiProxyFetcher, SimpleProxyLoader
from .health import HealthChecker, SyncHealthChecker
from .connector import (
    create_proxy_socket,
    create_proxy_socket_async,
    _make_sock,
    ProxyError,
    ProxyExhaustedError,
    PortBlockedError,
    ProxyDeadError,
    ProxyUnstableError,
    ProxyParseError,
    ProxyFetchError,
)
from .config import ProxyPoolConfig, default_config

__version__ = "1.0.0"
__all__ = [
    # 模型
    "ProxyEntry",
    "ProxyProto",
    "ProxyStatus",
    "ApiProxyConfig",
    "RotateConfig",
    "PoolConfig",
    # 池
    "ProxyPool",
    "MixedPool",
    # 采集器
    "FileProxyFetcher",
    "ApiProxyFetcher",
    "SimpleProxyLoader",
    # 健康检测
    "HealthChecker",
    "SyncHealthChecker",
    # 连接器
    "create_proxy_socket",
    "create_proxy_socket_async",
    "_make_sock",
    "ProxyError",
    "ProxyExhaustedError",
    "PortBlockedError",
    "ProxyDeadError",
    "ProxyUnstableError",
    "ProxyParseError",
    "ProxyFetchError",
    # 配置
    "ProxyPoolConfig",
    "default_config",
]