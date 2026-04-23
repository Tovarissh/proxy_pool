#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单元测试：pool.py"""

import unittest
import threading
import time
import random
from proxy_pool.models import ProxyEntry, ProxyProto, PoolConfig
from proxy_pool.pool import ProxyPool, MixedPool
from proxy_pool.connector import ProxyExhaustedError


class TestProxyPool(unittest.TestCase):
    """测试代理池基本功能"""

    def setUp(self):
        """每个测试前重置池"""
        self.pool = ProxyPool()

    def test_add_and_size(self):
        """添加代理并检查大小"""
        entry = ProxyEntry(host="127.0.0.1", port=1080)
        self.pool.add(entry)
        self.assertEqual(self.pool.size(), 1)
        self.assertEqual(self.pool.stats()["total"], 1)
        self.assertEqual(self.pool.stats()["alive"], 0)  # alive=None
        self.assertEqual(self.pool.stats()["dead"], 0)

    def test_add_alive_dead_stats(self):
        """添加存活/死亡代理，更新统计"""
        alive_entry = ProxyEntry(host="a", port=1, alive=True)
        dead_entry = ProxyEntry(host="b", port=2, alive=False)
        untested_entry = ProxyEntry(host="c", port=3, alive=None)
        self.pool.add(alive_entry)
        self.pool.add(dead_entry)
        self.pool.add(untested_entry)
        stats = self.pool.stats()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["alive"], 1)
        self.assertEqual(stats["dead"], 1)

    def test_remove(self):
        """移除代理"""
        entry1 = ProxyEntry(host="a", port=1)
        entry2 = ProxyEntry(host="b", port=2, alive=True)
        self.pool.add(entry1)
        self.pool.add(entry2)
        self.assertTrue(self.pool.remove(entry1))
        self.assertEqual(self.pool.size(), 1)
        self.assertEqual(self.pool.stats()["alive"], 1)
        # 移除不存在的代理返回 False
        self.assertFalse(self.pool.remove(ProxyEntry(host="x", port=999)))

    def test_get_round_robin(self):
        """轮转策略"""
        entries = [
            ProxyEntry(host="a", port=1, alive=True),
            ProxyEntry(host="b", port=2, alive=True),
            ProxyEntry(host="c", port=3, alive=True),
        ]
        for e in entries:
            self.pool.add(e)
        # 顺序获取
        got = []
        for _ in range(6):  # 循环两轮
            proxy = self.pool.get(strategy="round_robin")
            got.append(proxy.host)
        # 期望顺序：a, b, c, a, b, c
        self.assertEqual(got, ["a", "b", "c", "a", "b", "c"])

    def test_get_round_robin_skip_dead(self):
        """轮转时跳过死亡代理"""
        alive1 = ProxyEntry(host="a", port=1, alive=True)
        dead = ProxyEntry(host="b", port=2, alive=False)
        alive2 = ProxyEntry(host="c", port=3, alive=True)
        self.pool.add(alive1)
        self.pool.add(dead)
        self.pool.add(alive2)
        got = []
        for _ in range(4):
            proxy = self.pool.get(strategy="round_robin")
            got.append(proxy.host)
        # 期望：a, c, a, c （跳过b）
        self.assertEqual(got, ["a", "c", "a", "c"])

    def test_get_random(self):
        """随机策略"""
        entries = [ProxyEntry(host=f"h{i}", port=i, alive=True) for i in range(5)]
        for e in entries:
            self.pool.add(e)
        hosts = {e.host for e in entries}
        # 多次获取，确保随机性（至少覆盖不同主机）
        got_hosts = {self.pool.get(strategy="random").host for _ in range(20)}
        self.assertTrue(len(got_hosts) >= 2)  # 有一定的随机性

    def test_get_least_used(self):
        """最少使用策略"""
        entries = [
            ProxyEntry(host="a", port=1, alive=True, total_used=5),
            ProxyEntry(host="b", port=2, alive=True, total_used=1),
            ProxyEntry(host="c", port=3, alive=True, total_used=10),
        ]
        for e in entries:
            self.pool.add(e)
        proxy = self.pool.get(strategy="least_used")
        self.assertEqual(proxy.host, "b")

    def test_get_best_latency(self):
        """最低延迟策略"""
        entries = [
            ProxyEntry(host="a", port=1, alive=True, latency_ms=100),
            ProxyEntry(host="b", port=2, alive=True, latency_ms=20),
            ProxyEntry(host="c", port=3, alive=True, latency_ms=200),
        ]
        for e in entries:
            self.pool.add(e)
        proxy = self.pool.get(strategy="best_latency")
        self.assertEqual(proxy.host, "b")

    def test_get_country(self):
        """按国家筛选策略"""
        entries = [
            ProxyEntry(host="a", port=1, alive=True, country_code="US"),
            ProxyEntry(host="b", port=2, alive=True, country_code="CN"),
            ProxyEntry(host="c", port=3, alive=True, country_code="US"),
        ]
        for e in entries:
            self.pool.add(e)
        proxy = self.pool.get(strategy="country", country_code="US")
        self.assertIn(proxy.host, ["a", "c"])
        # 不存在的国家代码，返回随机代理
        proxy = self.pool.get(strategy="country", country_code="XX")
        self.assertIsNotNone(proxy)

    def test_get_alive_only_false(self):
        """允许返回死亡代理"""
        alive = ProxyEntry(host="a", port=1, alive=True)
        dead = ProxyEntry(host="b", port=2, alive=False)
        self.pool.add(alive)
        self.pool.add(dead)
        proxy = self.pool.get(strategy="random", alive_only=False)
        # 可能返回任意一个
        self.assertIn(proxy.host, ["a", "b"])
        # 当 alive_only=True（默认）时跳过死亡代理
        proxy = self.pool.get(strategy="random", alive_only=True)
        self.assertEqual(proxy.host, "a")

    def test_get_empty_pool(self):
        """空池时返回 None"""
        self.assertIsNone(self.pool.get())

    def test_release_success(self):
        """归还成功，更新统计"""
        entry = ProxyEntry(host="x", port=1)
        self.pool.add(entry)
        self.pool.release(entry, success=True)
        self.assertEqual(entry.total_used, 1)
        self.assertEqual(entry.success_count, 1)
        self.assertEqual(entry.fail_count, 0)
        stats = self.pool.stats()
        self.assertEqual(stats["requests"], 1)
        self.assertEqual(stats["success"], 1)
        self.assertEqual(stats["fail"], 0)

    def test_release_fail(self):
        """归还失败，更新统计"""
        entry = ProxyEntry(host="x", port=1)
        self.pool.add(entry)
        self.pool.release(entry, success=False)
        self.assertEqual(entry.total_used, 1)
        self.assertEqual(entry.success_count, 0)
        self.assertEqual(entry.fail_count, 1)
        stats = self.pool.stats()
        self.assertEqual(stats["requests"], 1)
        self.assertEqual(stats["success"], 0)
        self.assertEqual(stats["fail"], 1)

    def test_mark_dead(self):
        """标记死亡，更新状态和统计"""
        entry = ProxyEntry(host="x", port=1, alive=True)
        self.pool.add(entry)
        self.pool.mark_dead(entry)
        self.assertFalse(entry.alive)
        self.assertEqual(entry.fail_count, 1)
        stats = self.pool.stats()
        self.assertEqual(stats["alive"], 0)
        self.assertEqual(stats["dead"], 1)

    def test_mark_alive(self):
        """标记存活，更新状态和统计"""
        entry = ProxyEntry(host="x", port=1, alive=False)
        self.pool.add(entry)
        self.pool.mark_alive(entry)
        self.assertTrue(entry.alive)
        self.assertEqual(entry.fail_count, 0)
        stats = self.pool.stats()
        self.assertEqual(stats["alive"], 1)
        self.assertEqual(stats["dead"], 0)

    def test_reset_all(self):
        """重置所有死亡标记"""
        entries = [
            ProxyEntry(host="a", port=1, alive=True),
            ProxyEntry(host="b", port=2, alive=False),
            ProxyEntry(host="c", port=3, alive=False),
        ]
        for e in entries:
            self.pool.add(e)
        self.pool.reset_all()
        for e in entries:
            self.assertTrue(e.alive)
        stats = self.pool.stats()
        self.assertEqual(stats["alive"], 3)
        self.assertEqual(stats["dead"], 0)

    def test_get_alive(self):
        """获取所有存活代理"""
        alive1 = ProxyEntry(host="a", port=1, alive=True)
        dead = ProxyEntry(host="b", port=2, alive=False)
        alive2 = ProxyEntry(host="c", port=3, alive=True)
        for e in (alive1, dead, alive2):
            self.pool.add(e)
        alive_list = self.pool.get_alive()
        self.assertEqual(len(alive_list), 2)
        self.assertIn(alive1, alive_list)
        self.assertIn(alive2, alive_list)
        self.assertNotIn(dead, alive_list)
        # 当全部死亡时，返回全部代理（给第二次机会）
        self.pool.clear()
        dead1 = ProxyEntry(host="d", port=4, alive=False)
        dead2 = ProxyEntry(host="e", port=5, alive=False)
        self.pool.add(dead1)
        self.pool.add(dead2)
        alive_list = self.pool.get_alive()
        self.assertEqual(len(alive_list), 2)  # 全部死亡返回全部

    def test_get_alive_filtered(self):
        """智能过滤"""
        entries = [
            ProxyEntry(host="a", port=1, alive=True, country_code="US", rbl_count=0, latency_ms=100),
            ProxyEntry(host="b", port=2, alive=True, country_code="CN", rbl_count=1, latency_ms=200),
            ProxyEntry(host="c", port=3, alive=True, country_code="US", rbl_count=0, latency_ms=50),
        ]
        for e in entries:
            self.pool.add(e)
        # 按国家筛选
        filtered = self.pool.get_alive_filtered(country="US")
        self.assertEqual(len(filtered), 2)
        self.assertEqual({e.host for e in filtered}, {"a", "c"})
        # 按国家 + RBL
        filtered = self.pool.get_alive_filtered(country="US", require_clean=True)
        self.assertEqual(len(filtered), 2)  # a 和 c 都是干净的
        # 按国家 + RBL + 延迟
        filtered = self.pool.get_alive_filtered(country="US", require_clean=True, max_latency_ms=80)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].host, "c")

    def test_clear(self):
        """清空池"""
        for i in range(5):
            self.pool.add(ProxyEntry(host=f"h{i}", port=i))
        self.pool.clear()
        self.assertEqual(self.pool.size(), 0)
        stats = self.pool.stats()
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["alive"], 0)
        self.assertEqual(stats["dead"], 0)

    def test_entries_copy(self):
        """entries() 返回副本（列表不同，但条目引用相同）"""
        entry = ProxyEntry(host="x", port=1)
        self.pool.add(entry)
        entries = self.pool.entries()
        self.assertEqual(len(entries), 1)
        # 列表是不同的对象
        self.assertIsNot(entries, self.pool._entries)
        # 条目是同一个对象
        self.assertIs(entries[0], entry)
        # 修改条目字段会影响池内的条目（浅拷贝）
        entries[0].host = "modified"
        self.assertEqual(self.pool.entries()[0].host, "modified")

    def test_thread_safety_get_release(self):
        """多线程并发 get/release 测试"""
        # 添加一些代理
        for i in range(10):
            self.pool.add(ProxyEntry(host=f"h{i}", port=i, alive=True))
        
        results = []
        errors = []
        lock = threading.Lock()
        
        def worker(tid):
            for _ in range(20):
                try:
                    proxy = self.pool.get(strategy="random")
                    if proxy is None:
                        continue
                    # 模拟使用
                    time.sleep(0.001)
                    success = random.random() > 0.3
                    self.pool.release(proxy, success)
                    with lock:
                        results.append((tid, proxy.host, success))
                except Exception as e:
                    errors.append(e)
        
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # 检查无异常
        self.assertEqual(len(errors), 0, f"Errors: {errors}")
        # 检查统计一致性
        stats = self.pool.stats()
        self.assertEqual(stats["requests"], len(results))
        self.assertEqual(stats["success"], sum(1 for _, _, s in results if s))
        self.assertEqual(stats["fail"], sum(1 for _, _, s in results if not s))

    def test_thread_safety_add_remove(self):
        """多线程并发添加/移除代理"""
        def adder():
            for i in range(50):
                entry = ProxyEntry(host=f"add{i}", port=1000 + i)
                self.pool.add(entry)
                time.sleep(0.001)
        
        def remover():
            for i in range(50):
                entries = self.pool.entries()
                if entries:
                    entry = random.choice(entries)
                    self.pool.remove(entry)
                time.sleep(0.001)
        
        threads = []
        for _ in range(2):
            threads.append(threading.Thread(target=adder))
            threads.append(threading.Thread(target=remover))
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # 统计应一致
        stats = self.pool.stats()
        self.assertEqual(stats["total"], self.pool.size())


class TestMixedPool(unittest.TestCase):
    """测试 MixedPool（兼容性类）"""

    def setUp(self):
        self.pool = MixedPool()

    def test_add_and_entries(self):
        """添加代理"""
        entry = ProxyEntry(host="127.0.0.1", port=1080)
        self.pool.add(entry)
        self.assertEqual(len(self.pool.entries()), 1)

    def test_next_round_robin(self):
        """轮转获取"""
        entries = [
            ProxyEntry(host="a", port=1, alive=True),
            ProxyEntry(host="b", port=2, alive=True),
            ProxyEntry(host="c", port=3, alive=True),
        ]
        for e in entries:
            self.pool.add(e)
        got = []
        for _ in range(6):
            proxy = self.pool.next()
            got.append(proxy.host)
        self.assertEqual(got, ["a", "b", "c", "a", "b", "c"])

    def test_next_skip_dead(self):
        """跳过死亡代理"""
        alive1 = ProxyEntry(host="a", port=1, alive=True)
        dead = ProxyEntry(host="b", port=2, alive=False)
        alive2 = ProxyEntry(host="c", port=3, alive=True)
        self.pool.add(alive1)
        self.pool.add(dead)
        self.pool.add(alive2)
        got = [self.pool.next().host for _ in range(4)]
        self.assertEqual(got, ["a", "c", "a", "c"])

    def test_clear_and_remove(self):
        """清空和移除"""
        e1 = ProxyEntry(host="a", port=1)
        e2 = ProxyEntry(host="b", port=2)
        self.pool.add(e1)
        self.pool.add(e2)
        self.pool.clear()
        self.assertEqual(len(self.pool.entries()), 0)
        # 按索引移除
        self.pool.add(e1)
        self.pool.add(e2)
        self.pool.remove(0)
        self.assertEqual(len(self.pool.entries()), 1)
        self.assertEqual(self.pool.entries()[0].host, "b")

    def test_get_alive(self):
        """获取存活代理列表"""
        alive = ProxyEntry(host="a", port=1, alive=True)
        dead = ProxyEntry(host="b", port=2, alive=False)
        self.pool.add(alive)
        self.pool.add(dead)
        alive_list = self.pool.get_alive()
        self.assertEqual(len(alive_list), 1)
        self.assertEqual(alive_list[0].host, "a")


if __name__ == "__main__":
    unittest.main()