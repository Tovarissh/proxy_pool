# -*- coding: utf-8 -*-
"""
代理池管理器
负责代理的存储、调度、状态维护与统计。不负责代理的获取与健康检测。
"""
from typing import List, Optional, Dict, Any, Callable
from collections import deque
import threading
import random
import time
import logging

from .models import ProxyEntry, PoolConfig

logger = logging.getLogger(__name__)


class ProxyPool:
    """代理池管理器
    
    负责代理的存储、调度、状态维护与统计。不负责代理的获取与健康检测。
    """
    
    def __init__(self, config: Optional[PoolConfig] = None):
        self.config = config or PoolConfig()
        self._entries: List[ProxyEntry] = []
        self._lock = threading.RLock()
        self._queue = deque()  # 用于轮转调度
        self._stats: Dict[str, Any] = {
            "total": 0,
            "alive": 0,
            "dead": 0,
            "requests": 0,
            "success": 0,
            "fail": 0,
        }
    
    def add(self, entry: ProxyEntry) -> None:
        """添加代理到池中"""
        with self._lock:
            self._entries.append(entry)
            self._queue.append(entry)
            self._stats["total"] += 1
            if entry.alive is True:
                self._stats["alive"] += 1
            elif entry.alive is False:
                self._stats["dead"] += 1
    
    def remove(self, entry: ProxyEntry) -> bool:
        """从池中移除代理"""
        with self._lock:
            try:
                self._entries.remove(entry)
                try:
                    self._queue.remove(entry)
                except ValueError:
                    pass
                if entry.alive is True:
                    self._stats["alive"] -= 1
                elif entry.alive is False:
                    self._stats["dead"] -= 1
                self._stats["total"] -= 1
                return True
            except ValueError:
                return False
    
    def get(self, strategy: str = "round_robin", **kwargs) -> Optional[ProxyEntry]:
        """根据策略获取一个代理
        
        Args:
            strategy: 调度策略
                - "round_robin": 轮转（跳过死亡代理）
                - "random": 随机选择
                - "least_used": 最少使用
                - "best_latency": 最低延迟
                - "country": 按国家筛选（需传入 country_code）
            **kwargs: 策略参数
                - alive_only: bool = True 是否仅返回存活的代理
                - country_code: str 国家代码（country策略）
                
        Returns:
            ProxyEntry 或 None（池为空）
        """
        with self._lock:
            if not self._entries:
                return None
            
            candidates = self._entries
            
            # 先按存活状态过滤
            alive_only = kwargs.get("alive_only", True)
            if alive_only:
                candidates = [p for p in candidates if p.alive is not False]
                if not candidates:  # 全部死亡时放宽条件
                    candidates = self._entries
            
            # 策略筛选
            if strategy == "round_robin":
                if not self._queue:
                    self._queue.extend(candidates)
                for _ in range(len(self._queue)):
                    entry = self._queue[0]
                    self._queue.rotate(-1)
                    if entry.alive is not False:
                        return entry
                return None if not candidates else random.choice(candidates)
                
            elif strategy == "random":
                return random.choice(candidates)
                
            elif strategy == "least_used":
                candidates.sort(key=lambda p: p.total_used)
                return candidates[0] if candidates else None
                
            elif strategy == "best_latency":
                alive_low = [p for p in candidates if p.latency_ms > 0]
                if alive_low:
                    alive_low.sort(key=lambda p: p.latency_ms)
                    return alive_low[0]
                return random.choice(candidates) if candidates else None
                
            elif strategy == "country":
                country = kwargs.get("country_code", "").upper()
                if country:
                    by_country = [p for p in candidates 
                                 if p.country_code and p.country_code.upper() == country]
                    if by_country:
                        return random.choice(by_country)
                return random.choice(candidates) if candidates else None
                
            else:
                raise ValueError(f"未知策略: {strategy}")
    
    def release(self, entry: ProxyEntry, success: bool) -> None:
        """归还代理并更新统计
        
        Args:
            entry: 归还的代理
            success: 使用是否成功
        """
        with self._lock:
            entry.total_used += 1
            entry.last_used = time.time()
            self._stats["requests"] += 1
            
            if success:
                entry.success_count += 1
                entry.fail_count = 0
                self._stats["success"] += 1
            else:
                entry.fail_count += 1
                entry.success_count = 0
                self._stats["fail"] += 1
    
    def mark_dead(self, entry: ProxyEntry) -> None:
        """标记代理死亡"""
        with self._lock:
            if entry.alive is not False:
                entry.alive = False
                entry.fail_count += 1
                self._stats["alive"] = max(0, self._stats["alive"] - 1)
                self._stats["dead"] += 1
    
    def mark_alive(self, entry: ProxyEntry) -> None:
        """标记代理存活"""
        with self._lock:
            if entry.alive is not True:
                entry.alive = True
                entry.fail_count = 0
                self._stats["dead"] = max(0, self._stats["dead"] - 1)
                self._stats["alive"] += 1
    
    def reset_all(self) -> None:
        """重置所有代理的死亡标记（给第二次机会）"""
        with self._lock:
            for entry in self._entries:
                if entry.alive is False:
                    entry.alive = True
            self._stats["alive"] = self._stats["total"]
            self._stats["dead"] = 0
    
    def get_alive(self) -> List[ProxyEntry]:
        """获取所有存活的代理"""
        with self._lock:
            alive = [p for p in self._entries if p.alive is not False]
            if alive:
                return alive
            # 全部死亡时返回全部（给予第二次机会）
            return list(self._entries)
    
    def get_alive_filtered(self, country: str = "", 
                           require_clean: bool = False,
                           max_latency_ms: float = 0) -> List[ProxyEntry]:
        """智能过滤（与 smtpsender-v6.py 兼容）
        
        按国家、RBL、延迟逐步放宽条件。
        """
        alive = self.get_alive()
        if not alive:
            return alive
        
        # 三层过滤策略（同原逻辑）
        # 1. 全部条件
        filtered = alive
        if country:
            cc = country.upper()
            by_country = [p for p in filtered if p.country_code.upper() == cc]
            if by_country:
                filtered = by_country
        if require_clean:
            clean = [p for p in filtered if p.is_rbl_clean()]
            if clean:
                filtered = clean
        if max_latency_ms > 0:
            low_lat = [p for p in filtered if p.is_low_latency(max_latency_ms)]
            if low_lat:
                filtered = low_lat
        
        if filtered:
            return filtered
        
        # 2. 放宽延迟限制
        filtered = alive
        if country:
            cc = country.upper()
            by_country = [p for p in filtered if p.country_code.upper() == cc]
            if by_country:
                filtered = by_country
        if require_clean:
            clean = [p for p in filtered if p.is_rbl_clean()]
            if clean:
                filtered = clean
        if filtered:
            return filtered
        
        # 3. 放宽 RBL 限制
        filtered = alive
        if country:
            cc = country.upper()
            by_country = [p for p in filtered if p.country_code.upper() == cc]
            if by_country:
                filtered = by_country
        if filtered:
            return filtered
        
        # 全部放宽
        return alive
    
    def stats(self) -> Dict[str, Any]:
        """返回池统计信息"""
        with self._lock:
            return self._stats.copy()
    
    def clear(self) -> None:
        """清空池"""
        with self._lock:
            self._entries.clear()
            self._queue.clear()
            self._stats = {"total": 0, "alive": 0, "dead": 0, 
                          "requests": 0, "success": 0, "fail": 0}
    
    def size(self) -> int:
        """返回池中代理总数"""
        with self._lock:
            return len(self._entries)
    
    def entries(self) -> List[ProxyEntry]:
        """返回所有代理条目（副本）"""
        with self._lock:
            return list(self._entries)


# 兼容性类：MixedPool（保持与proxysmtp-gui.py相同的接口）
class MixedPool:
    """混合模式：维护代理列表，顺序/随机分发（兼容proxysmtp-gui.py）"""
    def __init__(self):
        self._entries: List[ProxyEntry] = []
        self._dq: deque = deque()
        self._lock = threading.Lock()
    
    def add(self, entry: ProxyEntry):
        with self._lock:
            self._entries.append(entry)
            self._dq.append(entry)
    
    def remove(self, idx: int):
        with self._lock:
            if 0 <= idx < len(self._entries):
                e = self._entries.pop(idx)
                try:
                    self._dq.remove(e)
                except ValueError:
                    pass
    
    def clear(self):
        with self._lock:
            self._entries.clear()
            self._dq.clear()
    
    def set_entries_ordered(self, entries: List[ProxyEntry]) -> None:
        """按给定顺序重建列表与轮转队列（用于表格排序后写回）。"""
        with self._lock:
            self._entries = list(entries)
            self._dq = deque(entries)
    
    def remove_entries(self, to_remove: List[ProxyEntry]) -> None:
        """批量移除代理条目"""
        with self._lock:
            for entry in to_remove:
                try:
                    self._entries.remove(entry)
                except ValueError:
                    pass
                try:
                    self._dq.remove(entry)
                except ValueError:
                    pass
    
    def get_alive(self) -> List[ProxyEntry]:
        with self._lock:
            return [p for p in self._entries if p.alive is not False]
    
    def next(self) -> Optional[ProxyEntry]:
        """轮转获取下一个代理（跳过死亡代理）"""
        with self._lock:
            if not self._dq:
                if not self._entries:
                    return None
                self._dq.extend(self._entries)
            
            for _ in range(len(self._dq)):
                entry = self._dq[0]
                self._dq.rotate(-1)
                if entry.alive is not False:
                    return entry
            
            return None if not self._entries else random.choice(self._entries)
    
    def entries(self) -> List[ProxyEntry]:
        with self._lock:
            return list(self._entries)