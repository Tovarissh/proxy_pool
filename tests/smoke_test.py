#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冒烟测试：无需mock，测试真实可运行性
运行：python3 smoke_test.py
"""

import sys
import os
import tempfile

# 添加父目录到路径，确保可以导入 proxy_pool
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def smoke_test():
    """执行冒烟测试"""
    print("=== 开始代理池冒烟测试 ===\n")
    
    passed = []
    failed = []
    
    # 1. 所有模块可正常import
    print("1. 导入模块...")
    try:
        from proxy_pool.models import ProxyEntry, ProxyProto, ProxyStatus
        from proxy_pool.pool import ProxyPool, MixedPool
        from proxy_pool.health import HealthChecker, SyncHealthChecker
        from proxy_pool.connector import create_proxy_socket, ProxyExhaustedError
        from proxy_pool.fetcher import FileProxyFetcher, ApiProxyFetcher
        print("   ✓ 所有模块导入成功")
        passed.append("导入模块")
    except ImportError as e:
        print(f"   ✗ 导入失败: {e}")
        failed.append("导入模块")
        return passed, failed
    
    # 2. ProxyEntry可创建
    print("2. 创建 ProxyEntry...")
    try:
        entry = ProxyEntry(host="127.0.0.1", port=1080, protocol="socks5")
        assert entry.host == "127.0.0.1"
        assert entry.port == 1080
        assert entry.protocol == "socks5"
        assert entry.username == ""
        print(f"   ✓ ProxyEntry 创建成功: {entry}")
        passed.append("创建 ProxyEntry")
    except Exception as e:
        print(f"   ✗ 创建 ProxyEntry 失败: {e}")
        failed.append("创建 ProxyEntry")
    
    # 3. ProxyPool可创建并add/get/release
    print("3. 测试 ProxyPool 基本操作...")
    try:
        pool = ProxyPool()
        # 添加代理
        proxy1 = ProxyEntry(host="127.0.0.1", port=1080, alive=True)
        proxy2 = ProxyEntry(host="127.0.0.2", port=1080, alive=True)
        pool.add(proxy1)
        pool.add(proxy2)
        assert pool.size() == 2
        # 获取代理
        p = pool.get(strategy="round_robin")
        assert p is not None
        # 释放代理
        pool.release(p, success=True)
        assert p.total_used == 1
        # 统计
        stats = pool.stats()
        assert stats["total"] == 2
        assert stats["requests"] == 1
        assert stats["success"] == 1
        print(f"   ✓ ProxyPool 基本操作成功，统计: {stats}")
        passed.append("ProxyPool 基本操作")
    except Exception as e:
        print(f"   ✗ ProxyPool 操作失败: {e}")
        failed.append("ProxyPool 基本操作")
    
    # 4. 添加一个本地127.0.0.1:1080代理并mark_dead
    print("4. 测试标记代理死亡...")
    try:
        pool = ProxyPool()
        dead_proxy = ProxyEntry(host="127.0.0.1", port=1080, alive=True)
        pool.add(dead_proxy)
        pool.mark_dead(dead_proxy)
        assert dead_proxy.alive == False
        stats = pool.stats()
        assert stats["dead"] == 1
        print(f"   ✓ 标记代理死亡成功，死亡计数: {stats['dead']}")
        passed.append("标记代理死亡")
    except Exception as e:
        print(f"   ✗ 标记代理死亡失败: {e}")
        failed.append("标记代理死亡")
    
    # 5. HealthChecker可实例化并启动/停止
    print("5. 测试 HealthChecker...")
    try:
        pool = ProxyPool()
        checker = HealthChecker(pool)
        # 异步启动停止需要事件循环，这里只测试实例化
        assert checker.pool == pool
        # 同步版本
        sync_checker = SyncHealthChecker(pool)
        assert sync_checker.pool == pool
        print("   ✓ HealthChecker 实例化成功")
        passed.append("HealthChecker 实例化")
    except Exception as e:
        print(f"   ✗ HealthChecker 实例化失败: {e}")
        failed.append("HealthChecker 实例化")
    
    # 6. FileProxyFetcher加载临时文件
    print("6. 测试 FileProxyFetcher...")
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("socks5://127.0.0.1:1080\n")
            f.write("http://proxy.com:8080\n")
            f.write("# 注释行\n")
            f.write("192.168.1.1:8888\n")
            temp_path = f.name
        
        fetcher = FileProxyFetcher(temp_path, default_proto="socks5")
        entries = fetcher.load()
        assert len(entries) == 3  # 忽略注释行
        for e in entries:
            assert e.host
            assert e.port > 0
        print(f"   ✓ FileProxyFetcher 加载成功，得到 {len(entries)} 个代理")
        passed.append("FileProxyFetcher 加载文件")
        
        os.unlink(temp_path)
    except Exception as e:
        print(f"   ✗ FileProxyFetcher 失败: {e}")
        failed.append("FileProxyFetcher 加载文件")
    
    # 7. 错误类可实例化
    print("7. 测试错误类...")
    try:
        from proxy_pool.connector import (
            ProxyError, ProxyExhaustedError, ProxyDeadError,
            PortBlockedError, ProxyUnstableError, ProxyParseError, ProxyFetchError
        )
        # 实例化每个错误类
        errors = [
            ProxyError("test"),
            ProxyExhaustedError("exhausted"),
            ProxyDeadError("dead"),
            PortBlockedError("blocked"),
            ProxyUnstableError("unstable"),
            ProxyParseError("parse"),
            ProxyFetchError("fetch"),
        ]
        for err in errors:
            assert isinstance(err, Exception)
        print(f"   ✓ 所有 {len(errors)} 个错误类可实例化")
        passed.append("错误类实例化")
    except Exception as e:
        print(f"   ✗ 错误类测试失败: {e}")
        failed.append("错误类实例化")
    
    print("\n=== 冒烟测试完成 ===")
    return passed, failed


if __name__ == "__main__":
    passed, failed = smoke_test()
    print(f"\n通过: {len(passed)} 项")
    for p in passed:
        print(f"  ✓ {p}")
    print(f"失败: {len(failed)} 项")
    for f in failed:
        print(f"  ✗ {f}")
    
    if failed:
        print("\n✗ SMOKE TEST FAILED")
        sys.exit(1)
    else:
        print("\n✓ SMOKE TEST PASSED")
        sys.exit(0)