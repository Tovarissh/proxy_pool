# -*- coding: utf-8 -*-
"""
代理采集模块
提供从文件和API加载代理的功能
"""
import os
import time
import random
import logging
import threading
from typing import List, Optional, Callable, Dict, Any
from urllib.parse import urlparse
import asyncio

# 可选依赖
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False
    aiohttp = None

from .models import ProxyEntry, ApiProxyConfig
from .connector import ProxyError

logger = logging.getLogger(__name__)


class FileProxyFetcher:
    """从文件加载代理（支持热重载）"""
    
    def __init__(self, filepath: str, default_proto: str = "socks5"):
        self.filepath = filepath
        self.default_proto = default_proto
        self._last_mtime = 0
        self._lock = threading.Lock()
    
    def load(self) -> List[ProxyEntry]:
        """加载文件中的所有代理"""
        try:
            mtime = os.path.getmtime(self.filepath)
            if mtime == self._last_mtime:
                return []  # 文件未修改
            
            with open(self.filepath, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            
            entries = []
            for line in lines:
                entry = ProxyEntry.parse(line.strip(), self.default_proto)
                if entry:
                    entries.append(entry)
            
            with self._lock:
                self._last_mtime = mtime
            return entries
            
        except (OSError, IOError) as e:
            logger.warning(f"读取代理文件失败: {e}")
            return []
    
    def watch(self, callback: Callable[[List[ProxyEntry]], None], 
              interval: int = 10) -> threading.Thread:
        """启动文件监视线程（热重载）"""
        def watcher():
            while True:
                entries = self.load()
                if entries:
                    callback(entries)
                time.sleep(interval)
        
        thread = threading.Thread(target=watcher, daemon=True)
        thread.start()
        return thread


class ApiProxyFetcher:
    """从 API 加载代理（支持隧道模式与预检测信息）"""
    
    def __init__(self, config: ApiProxyConfig):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
        self._lock = threading.Lock()
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    async def fetch(self) -> List[ProxyEntry]:
        """从 API 拉取代理列表"""
        if not self.config.url:
            return []
        
        if not HAS_AIOHTTP:
            raise ImportError(
                "aiohttp 未安装，无法使用 API 代理获取功能。"
                "请安装: pip install aiohttp"
            )
        
        try:
            auth = aiohttp.BasicAuth(self.config.username, self.config.password) \
                   if self.config.username else None
            
            async with aiohttp.ClientSession() as session:
                async with session.get(self.config.url, auth=auth, 
                                     timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    text = await resp.text()
            
            entries: List[ProxyEntry] = []
            for idx, line in enumerate(text.splitlines()):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                
                if self.config.tunnel_mode:
                    entry = self._parse_proxy_line(line, "socks5")
                    if entry:
                        entry.tunnel_idx = len(entries)
                else:
                    entry = self._parse_proxy_line(line, self.config.protocol)
                
                if entry:
                    entry.alive = True  # 新拉取的代理默认存活
                    entries.append(entry)
            
            # 数量限制与排序
            if self.config.fetch_count > 0 and len(entries) > self.config.fetch_count:
                if self.config.order == "random":
                    entries = random.sample(entries, self.config.fetch_count)
                else:
                    entries = entries[:self.config.fetch_count]
            elif self.config.order == "random":
                random.shuffle(entries)
            
            # 隧道模式获取端口状态 / 普通模式获取预检测信息
            if self.config.tunnel_mode:
                await self._fetch_tunnel_status(entries)
            else:
                await self._fetch_precheck_info(entries)
            
            return entries
            
        except Exception as e:
            logger.error(f"API拉取失败: {e}")
            return []
    
    def start_auto_refresh(self, callback: Callable[[List[ProxyEntry]], None]):
        """启动自动刷新定时器"""
        async def refresh_loop():
            while self._running:
                try:
                    entries = await self.fetch()
                    if entries:
                        callback(entries)
                except Exception as e:
                    logger.error(f"自动刷新失败: {e}")
                
                if self.config.refresh_min <= 0:
                    break
                await asyncio.sleep(self.config.refresh_min * 60)
        
        self._running = True
        self._task = asyncio.create_task(refresh_loop())
    
    def stop_auto_refresh(self):
        """停止自动刷新"""
        self._running = False
        if self._task:
            self._task.cancel()
    
    async def _fetch_tunnel_status(self, entries: List[ProxyEntry]):
        """获取隧道端口活跃连接数（并发查询）"""
        # 简化实现：暂时不实现隧道状态查询
        logger.debug(f"隧道模式，条目数: {len(entries)}")
        # 可以为每个条目设置默认的tunnel_active值
        for entry in entries:
            if entry.tunnel_idx >= 0:
                # 这里可以发起HTTP请求查询隧道状态，但为了简化，暂时留空
                entry.tunnel_active = 0
    
    async def _fetch_precheck_info(self, entries: List[ProxyEntry]):
        """获取预检测信息（RBL、延迟、GeoIP）"""
        # 简化实现：暂时不实现预检测信息查询
        logger.debug(f"预检测模式，条目数: {len(entries)}")
        # 可以在这里添加RBL检测、GeoIP查询等，但为了简化，暂时留空
        # 实际实现可以参考原smtpsender-v6.py中的_try_fetch_precheck方法
    
    def _parse_proxy_line(self, line: str, default_proto: str) -> Optional[ProxyEntry]:
        """解析单行代理（兼容原代码逻辑）"""
        return ProxyEntry.parse(line, default_proto)


# 简化版代理加载器（兼容旧代码）
class SimpleProxyLoader:
    """简化代理加载器，兼容smtpsender-v6.py的代理解析逻辑"""
    
    @staticmethod
    def parse_line(line: str, default_proto: str = "socks5") -> Optional[ProxyEntry]:
        """增强代理格式解析，支持更多常见格式"""
        line = line.strip()
        if not line or line.startswith("#"):
            return None
        
        # 带协议前缀的 URL 格式
        if "://" in line:
            try:
                parsed = urlparse(line)
                host = parsed.hostname or ""
                try:
                    port = parsed.port or 1080
                except ValueError:
                    port = 1080
                if not host:
                    return None
                return ProxyEntry(
                    host=host,
                    port=port,
                    username=parsed.username or "",
                    password=parsed.password or "",
                    protocol=parsed.scheme or default_proto)
            except Exception:
                return None
        
        # 支持 user:pass@host:port 格式
        if "@" in line:
            auth_part, _, addr_part = line.rpartition("@")
            parts = addr_part.split(":")
            if len(parts) >= 2:
                try:
                    host = parts[0]
                    port = int(parts[1])
                    auth_parts = auth_part.split(":", 1)
                    username = auth_parts[0] if len(auth_parts) > 0 else ""
                    password = auth_parts[1] if len(auth_parts) > 1 else ""
                    return ProxyEntry(host=host, port=port, username=username,
                                      password=password, protocol=default_proto)
                except (ValueError, IndexError):
                    pass
        
        # 纯 host:port 或 host:port:user:pass 格式
        parts = line.replace("\t", ":").replace(" ", ":").split(":")
        if len(parts) >= 2:
            try:
                host = parts[0]
                port = int(parts[1])
                username = parts[2] if len(parts) > 2 else ""
                password = parts[3] if len(parts) > 3 else ""
                return ProxyEntry(host=host, port=port, username=username,
                                  password=password, protocol=default_proto)
            except (ValueError, IndexError):
                return None
        return None