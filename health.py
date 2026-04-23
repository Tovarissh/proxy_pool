# -*- coding: utf-8 -*-
"""
代理健康检测器
定时检测代理的连通性、延迟、RBL状态等，维护代理状态机。
"""
import asyncio
import time
import logging
import threading
from typing import List, Callable, Optional, Dict, Any

from .models import ProxyEntry, PoolConfig
from .pool import ProxyPool
from .connector import create_proxy_socket

logger = logging.getLogger(__name__)


class HealthChecker:
    """代理健康检测器
    
    定时检测代理的连通性、延迟、RBL状态等，维护代理状态机。
    """
    
    def __init__(self, pool: ProxyPool, config: Optional[PoolConfig] = None):
        self.pool = pool
        self.config = config or PoolConfig()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._callbacks: List[Callable[[ProxyEntry, str, dict], None]] = []
        
    def add_callback(self, callback: Callable[[ProxyEntry, str, dict], None]):
        """添加状态变更回调
        
        回调函数签名：callback(entry, prev_status, test_result)
        """
        self._callbacks.append(callback)
    
    async def test_proxy(self, entry: ProxyEntry) -> dict:
        """测试单个代理
        
        Returns:
            测试结果字典：
            {
                "success": bool,
                "latency_ms": float,
                "error": str,
                "rbl_hits": int,      # 可选的RBL检测结果
                "country_code": str,  # 可选的GeoIP结果
            }
        """
        target_host, target_port = self.config.health_check_target
        timeout = self.config.health_check_timeout
        
        start_time = time.time()
        try:
            sock = await asyncio.wait_for(
                asyncio.to_thread(create_proxy_socket, entry, target_host, target_port, timeout),
                timeout + 2
            )
            sock.close()
            latency_ms = (time.time() - start_time) * 1000
            
            return {
                "success": True,
                "latency_ms": latency_ms,
                "error": "",
            }
        except Exception as e:
            return {
                "success": False,
                "latency_ms": 0,
                "error": str(e),
            }
    
    async def check_all(self, entries: Optional[List[ProxyEntry]] = None) -> None:
        """批量检测代理"""
        if entries is None:
            entries = self.pool.get_alive()
        
        # 限制并发数，避免资源耗尽
        semaphore = asyncio.Semaphore(10)
        
        async def check_one(entry: ProxyEntry):
            async with semaphore:
                result = await self.test_proxy(entry)
                await self._process_result(entry, result)
        
        tasks = [check_one(entry) for entry in entries]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _process_result(self, entry: ProxyEntry, result: dict):
        """处理检测结果，更新状态机"""
        prev_alive = entry.alive
        
        if result["success"]:
            entry.alive = True
            entry.latency_ms = result.get("latency_ms", entry.latency_ms)
            entry.success_count += 1
            entry.fail_count = 0
        else:
            entry.fail_count += 1
            entry.success_count = 0
            
            # 根据错误类型判断是否标记死亡
            error = result["error"]
            if "PROXY_DEAD" in error or "auth failed" in error.lower():
                entry.alive = False
            elif "PORT_TIMEOUT" in error:
                # 端口超时可能是ISP封锁，不标记死亡
                pass
            else:
                # 其他错误暂不改变状态
                pass
        
        # 通知状态变更
        if entry.alive != prev_alive:
            for callback in self._callbacks:
                try:
                    callback(entry, prev_alive, result)
                except Exception:
                    pass
    
    def start_auto_check(self, interval: Optional[int] = None):
        """启动定时健康检测"""
        async def check_loop():
            while self._running:
                await self.check_all()
                await asyncio.sleep(interval or self.config.health_check_interval)
        
        self._running = True
        self._task = asyncio.create_task(check_loop())
    
    def stop_auto_check(self):
        """停止定时健康检测"""
        self._running = False
        if self._task:
            self._task.cancel()


# 同步版本的健康检查器（兼容旧代码）
class SyncHealthChecker:
    """同步健康检查器（使用线程池）"""
    
    def __init__(self, pool: ProxyPool, config: Optional[PoolConfig] = None):
        self.pool = pool
        self.config = config or PoolConfig()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callbacks: List[Callable[[ProxyEntry, bool, dict], None]] = []
    
    def add_callback(self, callback: Callable[[ProxyEntry, bool, dict], None]):
        """添加状态变更回调"""
        self._callbacks.append(callback)
    
    def test_proxy_sync(self, entry: ProxyEntry) -> dict:
        """同步测试单个代理"""
        target_host, target_port = self.config.health_check_target
        timeout = self.config.health_check_timeout
        
        start_time = time.time()
        try:
            sock = create_proxy_socket(entry, target_host, target_port, timeout)
            sock.close()
            latency_ms = (time.time() - start_time) * 1000
            return {
                "success": True,
                "latency_ms": latency_ms,
                "error": "",
            }
        except Exception as e:
            return {
                "success": False,
                "latency_ms": 0,
                "error": str(e),
            }
    
    def start_auto_check_sync(self, interval: Optional[int] = None):
        """启动定时健康检测（同步版本）"""
        import threading
        
        def check_loop():
            import time
            while self._running:
                entries = self.pool.get_alive()
                # 简单实现：逐个测试
                for entry in entries:
                    result = self.test_proxy_sync(entry)
                    self._process_result_sync(entry, result)
                time.sleep(interval or self.config.health_check_interval)
        
        self._running = True
        self._thread = threading.Thread(target=check_loop, daemon=True)
        self._thread.start()
    
    def stop_auto_check_sync(self):
        """停止定时健康检测"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
    
    def _process_result_sync(self, entry: ProxyEntry, result: dict):
        """处理检测结果（同步版本）"""
        prev_alive = entry.alive
        
        if result["success"]:
            entry.alive = True
            entry.latency_ms = result.get("latency_ms", entry.latency_ms)
            entry.success_count += 1
            entry.fail_count = 0
            self.pool.mark_alive(entry)
        else:
            entry.fail_count += 1
            entry.success_count = 0
            
            error = result["error"]
            if "PROXY_DEAD" in error or "auth failed" in error.lower():
                entry.alive = False
                self.pool.mark_dead(entry)
            elif "PORT_TIMEOUT" in error:
                # 端口超时可能是ISP封锁，不标记死亡
                pass
            # 其他错误暂不改变状态
        
        # 通知状态变更
        if entry.alive != prev_alive:
            for callback in self._callbacks:
                try:
                    callback(entry, prev_alive, result)
                except Exception:
                    pass