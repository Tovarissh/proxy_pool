# -*- coding: utf-8 -*-
"""
代理池数据模型定义
包含代理条目、协议枚举、状态枚举、配置类等
"""
from enum import Enum
from typing import Optional, Union, List, Dict, Any
from dataclasses import dataclass, field
import time
import socks  # PySocks


class ProxyProto(str, Enum):
    """代理协议枚举"""
    SOCKS5 = "socks5"
    SOCKS4 = "socks4"  # 注意：有些源文件可能不支持，但保留兼容性
    HTTP = "http"
    HTTPS = "https"


class ProxyStatus(str, Enum):
    """代理健康状态（用于健康检测状态机）"""
    UNTESTED = "untested"
    ALIVE = "alive"
    DEAD = "dead"
    UNSTABLE = "unstable"
    TIMEOUT = "timeout"


@dataclass
class ProxyEntry:
    """统一代理条目
    
    合并 smtpsender-v6.py 与 proxysmtp-gui.py 两套定义，兼容10种常见格式解析。
    支持隧道模式（tunnel_idx/tunnel_active）与预检测信息（RBL、延迟、GeoIP）。
    """
    # --- 核心连接字段 ---
    host: str
    port: int
    username: str = ""
    password: str = ""
    # 协议字段：优先使用 ProxyProto，但保留字符串兼容性
    protocol: Union[ProxyProto, str] = ProxyProto.SOCKS5
    # 健康状态（None=未测试，True=存活，False=死亡）
    alive: Optional[bool] = None
    # SOCKS5 专用：True=代理解析域名，False=本机解析后再连
    socks_rdns: Optional[bool] = None
    
    # --- 预检测字段（从代理端 API 获取）---
    country_code: str = ""           # ISO 3166-1 alpha-2 国家代码
    rbl_count: int = 0               # RBL 黑名单命中数
    latency_ms: float = 0.0          # TCP 延迟（毫秒）
    precheck_time: float = 0.0       # 上次检测时间戳
    
    # --- 上游隧道模式字段 ---
    tunnel_idx: int = -1             # 隧道端口索引（用于 /proxy/{idx} 查询）
    tunnel_active: int = 0           # 当前活跃连接数
    
    # --- 内部管理字段 ---
    last_used: float = 0.0           # 上次被取出的时间戳
    fail_count: int = 0              # 连续失败次数
    success_count: int = 0           # 连续成功次数
    total_used: int = 0              # 累计使用次数
    
    def __str__(self) -> str:
        """转换为标准代理 URL 格式"""
        if self.username:
            return f"{self.protocol}://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"{self.protocol}://{self.host}:{self.port}"
    
    @classmethod
    def parse(cls, raw: str, default_proto: str = "socks5") -> Optional["ProxyEntry"]:
        """10种常见格式解析（兼容 proxysmtp-gui.py 逻辑）
        
        支持格式：
        1. socks5://user:pass@host:port
        2. http://host:port
        3. curl --proxy socks5://...
        4. user:pass@host:port
        5. host:port:user:pass
        6. host:port
        7. 纯 host:port:user:pass（含冒号的密码）
        """
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            return None
        
        # socks4/4a 协议目前不支持，明确拒绝而不是误映射为 SOCKS5
        raw_lower = raw.lower()
        if raw_lower.startswith("socks4://") or raw_lower.startswith("curl --proxy socks4://"):
            return None
        
        # 保存原始协议类型
        original_proto: Optional[ProxyProto] = None
        for prefix in ("socks5://", "socks4://", "http://", "https://",
                       "curl --proxy socks5://", "curl --proxy socks4://",
                       "curl --proxy http://", "curl --proxy https://",
                       "curl -x "):
            if raw_lower.startswith(prefix.lower()):
                prefix_lower = prefix.lower().rstrip(":/")
                if "socks" in prefix_lower:
                    original_proto = ProxyProto.SOCKS5
                elif "https" in prefix_lower:
                    original_proto = ProxyProto.HTTPS
                else:
                    original_proto = ProxyProto.HTTP
                raw = raw[len(prefix):].split()[0]
                break
        
        # 使用 urlparse 解析
        from urllib.parse import urlparse
        parsed = urlparse(f"x://{raw}" if "://" not in raw else raw)
        host = parsed.hostname or ""
        user = parsed.username or ""
        pw = parsed.password or ""
        
        # 捕获端口解析异常
        try:
            port = parsed.port or 0
        except ValueError:
            port = 0
            host = ""
        
        # 纯 host:port:user:pass（密码段可含 ':'，需合并 parts[3:]）
        parts = raw.split(":")
        if not host and len(parts) >= 2:
            try:
                host = parts[0]
                port = int(parts[1])
                user = parts[2] if len(parts) > 2 else ""
                pw = ":".join(parts[3:]) if len(parts) > 3 else ""
            except (ValueError, IndexError):
                return None
        
        # urlparse 会把 host:port:user:pass 误解析成仅有 host/port、无认证信息
        if host and port and not user and not pw and len(parts) >= 4:
            try:
                host = parts[0]
                port = int(parts[1])
                user = parts[2]
                pw = ":".join(parts[3:])
            except (ValueError, IndexError):
                return None
        
        if not host or not port:
            return None
        
        # 确定协议
        if original_proto is None:
            # 使用默认协议
            if default_proto.lower() == "socks5":
                original_proto = ProxyProto.SOCKS5
            elif default_proto.lower() == "socks4":
                original_proto = ProxyProto.SOCKS4
            elif default_proto.lower() == "http":
                original_proto = ProxyProto.HTTP
            elif default_proto.lower() == "https":
                original_proto = ProxyProto.HTTPS
            else:
                original_proto = ProxyProto.SOCKS5
        
        return cls(
            host=host,
            port=port,
            username=user,
            password=pw,
            protocol=original_proto,
            alive=None,
            socks_rdns=None,
        )
    
    def to_pysocks_args(self) -> dict:
        """转换为 PySocks 的 set_proxy 参数字典"""
        proto_map = {
            "socks5": socks.SOCKS5,
            "socks4": socks.SOCKS4,
            "http": socks.HTTP,
            "https": socks.HTTP,  # HTTPS 代理降级为 HTTP CONNECT
        }
        proxy_type = proto_map.get(str(self.protocol).lower(), socks.SOCKS5)
        return {
            "proxy_type": proxy_type,
            "addr": self.host,
            "port": self.port,
            "username": self.username or None,
            "password": self.password or None,
            "rdns": True if self.socks_rdns is None else bool(self.socks_rdns),
        }
    
    def is_rbl_clean(self) -> bool:
        """检查是否未被 RBL 黑名单列入"""
        return self.rbl_count == 0
    
    def is_low_latency(self, threshold_ms: float = 5000) -> bool:
        """检查延迟是否低于阈值"""
        return self.latency_ms > 0 and self.latency_ms <= threshold_ms
    
    def update_latency(self, latency_ms: float):
        """更新延迟并重置健康状态"""
        self.latency_ms = latency_ms
        self.precheck_time = time.time()


# ============================================================================
# 配置类
# ============================================================================

@dataclass
class ApiProxyConfig:
    """API 代理配置（对应 smtpsender-v6.py ApiProxyConfig）"""
    url: str = ""
    username: str = ""
    password: str = ""
    protocol: str = "socks5"
    order: str = "random"          # random / asc / desc
    fetch_count: int = 0           # 0=无限制
    refresh_min: float = 10.0      # 刷新间隔（分钟）
    auto_remove_dead: bool = True
    pause_on_fail: bool = False
    enabled: bool = False
    tunnel_mode: bool = False
    tunnel_api_base: str = ""


@dataclass
class RotateConfig:
    """轮转代理配置（对应 proxysmtp-gui.py RotateConfig）"""
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""
    proto: ProxyProto = ProxyProto.SOCKS5
    enabled: bool = False
    dnsbl_enabled: bool = True
    geoip_enabled: bool = True
    rotation_mode: str = "sticky"   # sticky / dynamic
    sticky_ttl_minutes: int = 0
    socks5_remote_dns: bool = True


@dataclass
class PoolConfig:
    """代理池全局配置"""
    max_size: int = 1000
    health_check_interval: int = 300      # 秒
    health_check_timeout: int = 10        # 秒
    health_check_target: tuple = ("smtp.gmail.com", 465)
    enable_geoip: bool = True
    enable_dnsbl: bool = True
    retry_dead_after: int = 600           # 死亡代理重试间隔（秒）