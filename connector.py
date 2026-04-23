# -*- coding: utf-8 -*-
"""
代理连接器模块
提供代理socket创建功能，支持HTTP/SOCKS5协议，包含错误类型定义
"""
import socket
import socks  # PySocks
from typing import Optional
import asyncio

from .models import ProxyEntry


# 错误类型定义
class ProxyError(Exception):
    """代理相关错误的基类"""
    pass


class ProxyExhaustedError(ProxyError):
    """代理池耗尽（无可用代理）"""
    pass


class PortBlockedError(ProxyError):
    """端口被ISP封锁（代理可用，但目标端口无法连接）"""
    pass


class ProxyDeadError(ProxyError):
    """代理本身故障（连接失败、认证失败等）"""
    pass


class ProxyUnstableError(ProxyError):
    """代理不稳定（连接被关闭等）"""
    pass


class ProxyParseError(ProxyError):
    """代理格式解析失败"""
    pass


class ProxyFetchError(ProxyError):
    """代理获取失败（网络错误、API错误等）"""
    pass


def create_proxy_socket(entry: ProxyEntry, target_host: str,
                        target_port: int, timeout: int) -> socket.socket:
    """创建通过代理连接的socket（同步版本）
    
    对应 smtpsender-v6.py 的 _make_proxy_socket 函数。
    
    Raises:
        ProxyDeadError: 代理本身故障
        PortBlockedError: 连接超时（可能是ISP封锁）
        ProxyUnstableError: 代理连接被关闭
        socket.timeout: 普通超时
        ConnectionRefusedError: 目标服务器拒绝连接
    """
    ptype_map = {
        "socks5": socks.SOCKS5,
        "socks4": socks.SOCKS4,
        "http": socks.HTTP,
        "https": socks.HTTP,  # HTTPS代理降级为HTTP CONNECT
    }
    
    ptype = ptype_map.get(str(entry.protocol).lower(), socks.SOCKS5)
    sock = socks.socksocket(socket.AF_INET, socket.SOCK_STREAM)
    
    # 设置代理参数
    sock.set_proxy(
        ptype,
        entry.host,
        entry.port,
        username=entry.username or None,
        password=entry.password or None,
        rdns=True if entry.socks_rdns is None else bool(entry.socks_rdns)
    )
    
    sock.settimeout(timeout)
    
    try:
        sock.connect((target_host, target_port))
        return sock
    except socks.ProxyConnectionError as e:
        sock.close()
        raise ProxyDeadError(f"代理连接失败: {entry.host}:{entry.port} [{e}]")
    except socks.GeneralProxyError as e:
        sock.close()
        err_str = str(e).lower()
        if "timed out" in err_str:
            raise PortBlockedError(f"代理出口超时: {target_host}:{target_port} via {entry.host}")
        elif "connection closed" in err_str:
            raise ProxyUnstableError(f"代理连接被关闭: {entry.host}:{entry.port}")
        else:
            raise ProxyDeadError(f"代理错误: {entry.host}:{entry.port} [{e}]")
    except socket.timeout:
        sock.close()
        raise PortBlockedError(f"连接超时: {target_host}:{target_port} via {entry.host}")
    except ConnectionRefusedError:
        sock.close()
        raise ConnectionRefusedError(f"目标拒绝连接: {target_host}:{target_port}")
    except OSError as e:
        sock.close()
        raise ProxyError(f"网络连接失败: {entry.host}:{entry.port} -> {target_host}:{target_port} [{e}]")


async def create_proxy_socket_async(entry: ProxyEntry, target_host: str,
                                    target_port: int, timeout: int,
                                    loop: Optional[asyncio.AbstractEventLoop] = None
                                   ) -> socket.socket:
    """异步版本（在线程池中执行）"""
    if loop is None:
        loop = asyncio.get_running_loop()
    
    return await loop.run_in_executor(
        None, create_proxy_socket, entry, target_host, target_port, timeout
    )


# 简化的_make_sock函数（兼容proxysmtp-gui.py接口）
def _make_sock(entry: ProxyEntry, host: str, port: int, timeout: int) -> socket.socket:
    """在线程池中创建独立 socks.socksocket 实例，每次调用完全独立。
    
    兼容 proxysmtp-gui.py 的 _make_sock 函数。
    """
    return create_proxy_socket(entry, host, port, timeout)