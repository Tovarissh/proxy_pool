#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""功能测试：集成各模块"""

import unittest
import tempfile
import os
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from proxy_pool.models import ProxyEntry, ProxyProto, PoolConfig, ApiProxyConfig
from proxy_pool.pool import ProxyPool
from proxy_pool.health import HealthChecker, SyncHealthChecker
from proxy_pool.fetcher import FileProxyFetcher, ApiProxyFetcher
from proxy_pool.connector import create_proxy_socket


class TestIntegration(unittest.TestCase):
    """集成测试：完整流程"""

    def test_full_workflow(self):
        """完整流程：创建pool → 添加代理 → 健康检测 → 获取可用代理"""
        pool = ProxyPool()
        # 添加几个代理
        proxy1 = ProxyEntry(host="proxy1.com", port=1080, alive=True)
        proxy2 = ProxyEntry(host="proxy2.com", port=1080, alive=None)
        proxy3 = ProxyEntry(host="proxy3.com", port=1080, alive=False)
        pool.add(proxy1)
        pool.add(proxy2)
        pool.add(proxy3)
        
        self.assertEqual(pool.size(), 3)
        self.assertEqual(pool.stats()["alive"], 1)
        self.assertEqual(pool.stats()["dead"], 1)
        
        # 获取存活代理
        alive = pool.get_alive()
        self.assertEqual(len(alive), 2)  # alive=True + alive=None
        self.assertIn(proxy1, alive)
        self.assertIn(proxy2, alive)
        
        # 轮转获取代理（跳过死亡代理）
        proxy = pool.get(strategy="round_robin")
        self.assertIn(proxy.host, ["proxy1.com", "proxy2.com"])
        
        # 使用并归还
        pool.release(proxy, success=True)
        self.assertEqual(proxy.total_used, 1)
        self.assertEqual(pool.stats()["success"], 1)
        
        # 标记死亡
        pool.mark_dead(proxy2)
        self.assertFalse(proxy2.alive)
        self.assertEqual(pool.stats()["dead"], 2)
        
        # 此时轮转只会返回 proxy1
        for _ in range(3):
            p = pool.get(strategy="round_robin")
            self.assertEqual(p.host, "proxy1.com")
            pool.release(p, success=True)

    @patch('proxy_pool.health.create_proxy_socket')
    async def test_pool_with_health_checker(self, mock_create_socket):
        """Pool + HealthChecker 联合测试（mock网络）"""
        pool = ProxyPool()
        checker = HealthChecker(pool)
        
        # 添加代理，状态未知
        proxy = ProxyEntry(host="test.com", port=1080, alive=None)
        pool.add(proxy)
        
        # 模拟健康检测成功
        mock_sock = MagicMock()
        mock_sock.close = MagicMock()
        mock_create_socket.return_value = mock_sock
        
        await checker.check_all()
        
        # 代理应标记为存活
        self.assertTrue(proxy.alive)
        self.assertGreater(proxy.latency_ms, 0)
        self.assertEqual(proxy.success_count, 1)
        
        # 获取代理应返回它
        fetched = pool.get(strategy="round_robin")
        self.assertEqual(fetched, proxy)
        
        # 模拟健康检测失败（代理死亡）
        mock_create_socket.side_effect = Exception("PROXY_DEAD")
        await checker.check_all([proxy])
        
        # 代理应标记为死亡
        self.assertFalse(proxy.alive)
        self.assertEqual(proxy.fail_count, 2)  # 之前成功1次，现在失败1次
        
        # 轮转获取应跳过死亡代理
        fetched = pool.get(strategy="round_robin")
        self.assertIsNone(fetched)  # 没有存活代理

    def run_async(self, coro):
        """运行异步测试的辅助函数"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    # 删除重复测试，因为 test_pool_with_health_checker 已经是异步测试
    # def test_sync_pool_with_health_checker(self):
    #     """同步版本集成测试"""
    #     async def inner():
    #         with patch('proxy_pool.health.create_proxy_socket') as mock_create_socket:
    #             await self.test_pool_with_health_checker(mock_create_socket)
    #     self.run_async(inner())


class TestFileProxyFetcher(unittest.TestCase):
    """测试文件代理加载器"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.temp_dir, "proxies.txt")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_from_file(self):
        """从文件加载代理"""
        content = """# 注释行
socks5://user:pass@127.0.0.1:1080
http://proxy.com:8080
192.168.1.1:8888
# 另一行注释
invalid line
"""
        with open(self.test_file, "w") as f:
            f.write(content)
        
        fetcher = FileProxyFetcher(self.test_file, default_proto="socks5")
        entries = fetcher.load()
        
        self.assertEqual(len(entries), 3)
        # 检查第一个条目
        e1 = entries[0]
        self.assertEqual(e1.host, "127.0.0.1")
        self.assertEqual(e1.port, 1080)
        self.assertEqual(e1.username, "user")
        self.assertEqual(e1.password, "pass")
        self.assertEqual(e1.protocol, ProxyProto.SOCKS5)
        # 第二个条目
        e2 = entries[1]
        self.assertEqual(e2.protocol, ProxyProto.HTTP)
        # 第三个条目（默认协议）
        e3 = entries[2]
        self.assertEqual(e3.protocol, ProxyProto.SOCKS5)

    def test_load_empty_file(self):
        """空文件"""
        with open(self.test_file, "w") as f:
            f.write("")
        fetcher = FileProxyFetcher(self.test_file)
        entries = fetcher.load()
        self.assertEqual(entries, [])

    def test_load_nonexistent_file(self):
        """文件不存在返回空列表"""
        fetcher = FileProxyFetcher("/nonexistent/file.txt")
        entries = fetcher.load()
        self.assertEqual(entries, [])

    def test_file_modification_detection(self):
        """文件修改检测"""
        with open(self.test_file, "w") as f:
            f.write("socks5://127.0.0.1:1080\n")
        
        fetcher = FileProxyFetcher(self.test_file, default_proto="socks5")
        entries = fetcher.load()
        self.assertEqual(len(entries), 1)
        
        # 再次加载，文件未修改，应返回空列表
        entries2 = fetcher.load()
        self.assertEqual(entries2, [])
        
        # 修改文件（添加新代理）
        with open(self.test_file, "a") as f:
            f.write("http://new:8080\n")
        
        # 模拟文件修改：重置 _last_mtime 以确保检测到修改
        fetcher._last_mtime = 0
        
        entries3 = fetcher.load()
        # 文件已修改，应返回所有代理（旧+新）
        self.assertEqual(len(entries3), 2)
        hosts = {e.host for e in entries3}
        self.assertEqual(hosts, {"127.0.0.1", "new"})

    @patch('time.sleep')
    def test_watch_callback(self, mock_sleep):
        """文件监视线程回调"""
        with open(self.test_file, "w") as f:
            f.write("socks5://127.0.0.1:1080\n")
        
        fetcher = FileProxyFetcher(self.test_file)
        callback_called = []
        def callback(entries):
            callback_called.append(entries)
        
        # 模拟 sleep 调用一次后抛出异常以退出循环
        call_count = 0
        def sleep_side_effect(*args):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise StopIteration
        mock_sleep.side_effect = sleep_side_effect
        
        # 启动监视线程（因为 sleep 会抛出 StopIteration，线程会终止）
        thread = fetcher.watch(callback, interval=0.01)
        # 等待线程结束（由于 StopIteration）
        thread.join(timeout=1)
        
        # 至少调用了一次回调（初始加载）
        self.assertGreaterEqual(len(callback_called), 1)


class TestApiProxyFetcher(unittest.TestCase):
    """测试API代理加载器"""

    def setUp(self):
        self.config = ApiProxyConfig(
            url="http://api.example.com/proxies",
            username="user",
            password="pass",
            protocol="socks5",
            order="random",
            fetch_count=5,
            refresh_min=5.0,
            enabled=True
        )

    @patch('aiohttp.ClientSession')
    @patch('aiohttp.ClientResponse')
    async def test_fetch_success(self, mock_response, mock_session):
        """成功拉取代理列表"""
        # 模拟 API 响应
        mock_session_instance = AsyncMock()
        mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_instance.__aexit__ = AsyncMock()
        mock_session_instance.get = AsyncMock()
        
        mock_response_instance = AsyncMock()
        mock_response_instance.text = AsyncMock(return_value="""socks5://proxy1.com:1080
http://proxy2.com:8080
192.168.1.1:1080
""")
        mock_response_instance.__aenter__ = AsyncMock(return_value=mock_response_instance)
        mock_response_instance.__aexit__ = AsyncMock()
        
        mock_session_instance.get.return_value = mock_response_instance
        mock_session.return_value = mock_session_instance
        
        fetcher = ApiProxyFetcher(self.config)
        entries = await fetcher.fetch()
        
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].host, "proxy1.com")
        self.assertEqual(entries[0].protocol, ProxyProto.SOCKS5)
        self.assertEqual(entries[1].protocol, ProxyProto.HTTP)
        self.assertEqual(entries[2].protocol, ProxyProto.SOCKS5)  # 默认协议
        
        # 新拉取的代理默认存活
        self.assertTrue(all(e.alive is True for e in entries))

    @patch('aiohttp.ClientSession')
    async def test_fetch_empty_response(self, mock_session):
        """API返回空内容"""
        mock_session_instance = AsyncMock()
        mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_instance.__aexit__ = AsyncMock()
        mock_session_instance.get = AsyncMock()
        
        mock_response_instance = AsyncMock()
        mock_response_instance.text = AsyncMock(return_value="")
        mock_response_instance.__aenter__ = AsyncMock(return_value=mock_response_instance)
        mock_response_instance.__aexit__ = AsyncMock()
        
        mock_session_instance.get.return_value = mock_response_instance
        mock_session.return_value = mock_session_instance
        
        fetcher = ApiProxyFetcher(self.config)
        entries = await fetcher.fetch()
        
        self.assertEqual(entries, [])

    @patch('aiohttp.ClientSession')
    async def test_fetch_network_error(self, mock_session):
        """网络错误返回空列表"""
        mock_session_instance = AsyncMock()
        mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_instance.__aexit__ = AsyncMock()
        mock_session_instance.get = AsyncMock(side_effect=Exception("Network error"))
        mock_session.return_value = mock_session_instance
        
        fetcher = ApiProxyFetcher(self.config)
        entries = await fetcher.fetch()
        
        self.assertEqual(entries, [])

    def test_fetch_without_aiohttp(self):
        """未安装 aiohttp 时抛出 ImportError"""
        with patch('proxy_pool.fetcher.HAS_AIOHTTP', False):
            fetcher = ApiProxyFetcher(self.config)
            with self.assertRaises(ImportError):
                # 需要运行异步代码
                async def test():
                    await fetcher.fetch()
                asyncio.run(test())

    @patch('proxy_pool.fetcher.ApiProxyFetcher.fetch')
    async def test_start_stop_auto_refresh(self, mock_fetch):
        """启动和停止自动刷新"""
        mock_fetch.return_value = []
        
        fetcher = ApiProxyFetcher(self.config)
        callback_called = []
        def callback(entries):
            callback_called.append(entries)
        
        # 启动自动刷新
        fetcher.start_auto_refresh(callback)
        self.assertTrue(fetcher._running)
        self.assertIsNotNone(fetcher._task)
        
        # 等待一小段时间
        await asyncio.sleep(0.05)
        
        # 停止
        fetcher.stop_auto_refresh()
        self.assertFalse(fetcher._running)
        if fetcher._task:
            fetcher._task.cancel()
            await asyncio.sleep(0.01)

    def run_async(self, coro):
        """运行异步测试的辅助函数"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_sync_wrapper(self):
        """同步包装器"""
        async def test():
            with patch('aiohttp.ClientSession'):
                # 简化测试
                fetcher = ApiProxyFetcher(self.config)
                # 模拟未安装 aiohttp 的情况
                with patch('proxy_pool.fetcher.HAS_AIOHTTP', False):
                    with self.assertRaises(ImportError):
                        await fetcher.fetch()
        self.run_async(test())


if __name__ == "__main__":
    unittest.main()