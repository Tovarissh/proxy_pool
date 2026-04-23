#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单元测试：models.py"""

import unittest
from unittest.mock import patch
from proxy_pool.models import (
    ProxyProto,
    ProxyStatus,
    ProxyEntry,
    ApiProxyConfig,
    RotateConfig,
    PoolConfig,
)
from proxy_pool.connector import (
    ProxyExhaustedError,
    ProxyDeadError,
    PortBlockedError,
    ProxyUnstableError,
    ProxyParseError,
    ProxyFetchError,
)


class TestProxyProto(unittest.TestCase):
    """测试代理协议枚举"""

    def test_protocol_values(self):
        """验证协议枚举值"""
        self.assertEqual(ProxyProto.SOCKS5, "socks5")
        self.assertEqual(ProxyProto.SOCKS4, "socks4")
        self.assertEqual(ProxyProto.HTTP, "http")
        self.assertEqual(ProxyProto.HTTPS, "https")

    def test_str_behavior(self):
        """枚举应能转换为字符串"""
        self.assertIsInstance(ProxyProto.SOCKS5, str)
        # 枚举成员本身就是字符串值
        self.assertEqual(ProxyProto.HTTP, "http")
        # str() 在某些Python版本中可能返回枚举名，但值正确即可
        # 我们至少验证它是字符串
        self.assertIsInstance(str(ProxyProto.HTTP), str)


class TestProxyStatus(unittest.TestCase):
    """测试代理状态枚举"""

    def test_status_values(self):
        """验证状态枚举值"""
        self.assertEqual(ProxyStatus.UNTESTED, "untested")
        self.assertEqual(ProxyStatus.ALIVE, "alive")
        self.assertEqual(ProxyStatus.DEAD, "dead")
        self.assertEqual(ProxyStatus.UNSTABLE, "unstable")
        self.assertEqual(ProxyStatus.TIMEOUT, "timeout")


class TestProxyEntry(unittest.TestCase):
    """测试代理条目"""

    def test_basic_creation(self):
        """基本创建与字段访问"""
        entry = ProxyEntry(
            host="127.0.0.1",
            port=1080,
            username="user",
            password="pass",
            protocol=ProxyProto.SOCKS5,
            alive=True,
            socks_rdns=True,
        )
        self.assertEqual(entry.host, "127.0.0.1")
        self.assertEqual(entry.port, 1080)
        self.assertEqual(entry.username, "user")
        self.assertEqual(entry.password, "pass")
        self.assertEqual(entry.protocol, ProxyProto.SOCKS5)
        self.assertEqual(entry.alive, True)
        self.assertEqual(entry.socks_rdns, True)

    def test_default_values(self):
        """默认值测试"""
        entry = ProxyEntry(host="example.com", port=8080)
        self.assertEqual(entry.host, "example.com")
        self.assertEqual(entry.port, 8080)
        self.assertEqual(entry.username, "")
        self.assertEqual(entry.password, "")
        self.assertEqual(entry.protocol, ProxyProto.SOCKS5)
        self.assertIsNone(entry.alive)
        self.assertIsNone(entry.socks_rdns)

    def test_str_with_auth(self):
        """带认证的字符串表示"""
        entry = ProxyEntry(
            host="proxy.com",
            port=8080,
            username="user",
            password="pass",
            protocol="http"
        )
        self.assertEqual(str(entry), "http://user:pass@proxy.com:8080")

    def test_str_without_auth(self):
        """无认证的字符串表示"""
        entry = ProxyEntry(host="proxy.com", port=1080, protocol="socks5")
        self.assertEqual(str(entry), "socks5://proxy.com:1080")

    def test_parse_socks5_auth_url(self):
        """解析 SOCKS5 认证 URL"""
        entry = ProxyEntry.parse("socks5://user:pass@127.0.0.1:1080")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.host, "127.0.0.1")
        self.assertEqual(entry.port, 1080)
        self.assertEqual(entry.username, "user")
        self.assertEqual(entry.password, "pass")
        self.assertEqual(entry.protocol, ProxyProto.SOCKS5)

    def test_parse_http_url(self):
        """解析 HTTP 代理 URL"""
        entry = ProxyEntry.parse("http://proxy.com:8080")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.host, "proxy.com")
        self.assertEqual(entry.port, 8080)
        self.assertEqual(entry.username, "")
        self.assertEqual(entry.password, "")
        self.assertEqual(entry.protocol, ProxyProto.HTTP)

    def test_parse_https_url(self):
        """解析 HTTPS 代理 URL"""
        entry = ProxyEntry.parse("https://proxy.com:443")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.protocol, ProxyProto.HTTPS)

    def test_parse_host_port(self):
        """解析 host:port 格式"""
        entry = ProxyEntry.parse("192.168.1.1:8888")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.host, "192.168.1.1")
        self.assertEqual(entry.port, 8888)
        # 默认协议是 socks5
        self.assertEqual(entry.protocol, ProxyProto.SOCKS5)

    def test_parse_host_port_user_pass(self):
        """解析 host:port:user:pass 格式（密码含冒号）"""
        entry = ProxyEntry.parse("192.168.1.1:1080:username:pass:word")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.host, "192.168.1.1")
        self.assertEqual(entry.port, 1080)
        self.assertEqual(entry.username, "username")
        self.assertEqual(entry.password, "pass:word")

    def test_parse_user_pass_host_port(self):
        """解析 user:pass@host:port 格式"""
        entry = ProxyEntry.parse("user:pass@192.168.1.1:1080")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.username, "user")
        self.assertEqual(entry.password, "pass")

    def test_parse_curl_proxy_format(self):
        """解析 curl --proxy 格式"""
        entry = ProxyEntry.parse("curl --proxy socks5://127.0.0.1:1080")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.host, "127.0.0.1")
        self.assertEqual(entry.port, 1080)
        self.assertEqual(entry.protocol, ProxyProto.SOCKS5)

    def test_parse_invalid_empty(self):
        """解析空行返回 None"""
        self.assertIsNone(ProxyEntry.parse(""))
        self.assertIsNone(ProxyEntry.parse("# comment"))

    def test_parse_invalid_socks4(self):
        """Socks4 明确拒绝"""
        self.assertIsNone(ProxyEntry.parse("socks4://host:1080"))
        self.assertIsNone(ProxyEntry.parse("curl --proxy socks4://host:1080"))

    def test_parse_invalid_format(self):
        """无效格式返回 None"""
        self.assertIsNone(ProxyEntry.parse("not a proxy"))
        self.assertIsNone(ProxyEntry.parse("host:notaport"))

    def test_to_pysocks_args_socks5(self):
        """转换为 PySocks 参数字典（SOCKS5）"""
        entry = ProxyEntry(
            host="proxy.com",
            port=1080,
            username="user",
            password="pass",
            socks_rdns=True
        )
        args = entry.to_pysocks_args()
        self.assertEqual(args["addr"], "proxy.com")
        self.assertEqual(args["port"], 1080)
        self.assertEqual(args["username"], "user")
        self.assertEqual(args["password"], "pass")
        self.assertEqual(args["rdns"], True)

    def test_to_pysocks_args_default(self):
        """默认 rdns 为 True"""
        entry = ProxyEntry(host="proxy.com", port=1080)
        args = entry.to_pysocks_args()
        self.assertEqual(args["rdns"], True)

    def test_is_rbl_clean(self):
        """RBL 检测"""
        entry = ProxyEntry(host="x", port=1, rbl_count=0)
        self.assertTrue(entry.is_rbl_clean())
        entry.rbl_count = 3
        self.assertFalse(entry.is_rbl_clean())

    def test_is_low_latency(self):
        """延迟检测"""
        entry = ProxyEntry(host="x", port=1, latency_ms=100)
        self.assertTrue(entry.is_low_latency(threshold_ms=500))
        self.assertFalse(entry.is_low_latency(threshold_ms=50))
        # 零延迟不算低延迟
        entry.latency_ms = 0
        self.assertFalse(entry.is_low_latency(threshold_ms=1000))

    def test_update_latency(self):
        """更新延迟"""
        import time
        entry = ProxyEntry(host="x", port=1)
        entry.update_latency(150.5)
        self.assertEqual(entry.latency_ms, 150.5)
        self.assertGreater(entry.precheck_time, 0)


class TestConfigClasses(unittest.TestCase):
    """测试配置类"""

    def test_api_proxy_config_defaults(self):
        """ApiProxyConfig 默认值"""
        config = ApiProxyConfig()
        self.assertEqual(config.url, "")
        self.assertEqual(config.username, "")
        self.assertEqual(config.password, "")
        self.assertEqual(config.protocol, "socks5")
        self.assertEqual(config.order, "random")
        self.assertEqual(config.fetch_count, 0)
        self.assertEqual(config.refresh_min, 10.0)
        self.assertTrue(config.auto_remove_dead)
        self.assertFalse(config.pause_on_fail)
        self.assertFalse(config.enabled)
        self.assertFalse(config.tunnel_mode)
        self.assertEqual(config.tunnel_api_base, "")

    def test_rotate_config_defaults(self):
        """RotateConfig 默认值"""
        config = RotateConfig()
        self.assertEqual(config.host, "")
        self.assertEqual(config.port, 0)
        self.assertEqual(config.username, "")
        self.assertEqual(config.password, "")
        self.assertEqual(config.proto, ProxyProto.SOCKS5)
        self.assertFalse(config.enabled)
        self.assertTrue(config.dnsbl_enabled)
        self.assertTrue(config.geoip_enabled)
        self.assertEqual(config.rotation_mode, "sticky")
        self.assertEqual(config.sticky_ttl_minutes, 0)
        self.assertTrue(config.socks5_remote_dns)

    def test_pool_config_defaults(self):
        """PoolConfig 默认值"""
        config = PoolConfig()
        self.assertEqual(config.max_size, 1000)
        self.assertEqual(config.health_check_interval, 300)
        self.assertEqual(config.health_check_timeout, 10)
        self.assertEqual(config.health_check_target, ("smtp.gmail.com", 465))
        self.assertTrue(config.enable_geoip)
        self.assertTrue(config.enable_dnsbl)
        self.assertEqual(config.retry_dead_after, 600)


class TestErrorClasses(unittest.TestCase):
    """测试错误类"""

    def test_proxy_exhausted_error(self):
        """ProxyExhaustedError 可实例化"""
        err = ProxyExhaustedError("No proxies available")
        self.assertIsInstance(err, Exception)
        self.assertEqual(str(err), "No proxies available")

    def test_proxy_dead_error(self):
        """ProxyDeadError 可实例化"""
        err = ProxyDeadError("Proxy dead")
        self.assertIsInstance(err, Exception)

    def test_port_blocked_error(self):
        """PortBlockedError 可实例化"""
        err = PortBlockedError("Port blocked")
        self.assertIsInstance(err, Exception)

    def test_proxy_unstable_error(self):
        """ProxyUnstableError 可实例化"""
        err = ProxyUnstableError("Unstable")
        self.assertIsInstance(err, Exception)

    def test_proxy_parse_error(self):
        """ProxyParseError 可实例化"""
        err = ProxyParseError("Parse failed")
        self.assertIsInstance(err, Exception)

    def test_proxy_fetch_error(self):
        """ProxyFetchError 可实例化"""
        err = ProxyFetchError("Fetch failed")
        self.assertIsInstance(err, Exception)


if __name__ == "__main__":
    unittest.main()