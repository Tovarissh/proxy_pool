#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
代理池 Web UI 管理界面
Flask + 纯HTML/JS，深色主题
"""
import json
import time
import logging
import sys
import os
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum

# 确保 proxy_pool 包在 Python 路径中
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from flask import Flask, render_template, request, jsonify, Response
from werkzeug.exceptions import BadRequest, NotFound

from proxy_pool.models import ProxyEntry, ProxyProto, ProxyStatus, PoolConfig
from proxy_pool.pool import ProxyPool
from proxy_pool.health import HealthChecker

logger = logging.getLogger(__name__)

# ============================================================================
# Web UI 配置
# ============================================================================
@dataclass
class WebUIConfig:
    """Web UI 特有配置（内存存储）"""
    # 调度模式: round_robin, random
    scheduling_mode: str = "round_robin"
    # 健康检测间隔（秒）
    health_check_interval: int = 300
    # 是否启用实时刷新
    auto_refresh: bool = True
    # 自动刷新间隔（秒）
    refresh_interval: int = 30

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)

# ============================================================================
# Flask 应用工厂
# ============================================================================
def create_app(pool: ProxyPool, health_checker: Optional[HealthChecker] = None, 
               pool_config: Optional[PoolConfig] = None) -> Flask:
    """
    创建 Flask 应用
    
    Args:
        pool: ProxyPool 实例
        health_checker: HealthChecker 实例（可选）
        pool_config: PoolConfig 实例（可选，用于读取健康检测间隔等）
    """
    app = Flask(__name__, template_folder="templates")
    
    # 初始化配置
    ui_config = WebUIConfig()
    if pool_config:
        ui_config.health_check_interval = pool_config.health_check_interval
    
    # 代理条目 ID 映射（用于 API 操作）
    # 生成唯一 ID：使用条目在列表中的索引（不稳定，但简单）
    # 我们会在每次请求时重新计算映射
    
    def get_entry_by_id(entry_id: str) -> Optional[ProxyEntry]:
        """根据 ID 查找代理条目"""
        try:
            idx = int(entry_id)
            entries = pool.entries()
            if 0 <= idx < len(entries):
                return entries[idx]
        except (ValueError, IndexError):
            pass
        return None
    
    def entry_to_dict(entry: ProxyEntry, idx: int) -> Dict[str, Any]:
        """转换 ProxyEntry 为 API 响应字典"""
        status = "unknown"
        if entry.alive is True:
            status = "alive"
        elif entry.alive is False:
            status = "dead"
        elif entry.alive is None:
            status = "untested"
        
        # 简化协议字符串
        protocol = str(entry.protocol)
        
        return {
            "id": idx,
            "host": entry.host,
            "port": entry.port,
            "username": entry.username,
            "password": entry.password,
            "protocol": protocol,
            "status": status,
            "latency_ms": round(entry.latency_ms, 2) if entry.latency_ms else 0,
            "last_check": entry.precheck_time,
            "last_check_str": time.strftime("%Y-%m-%d %H:%M:%S", 
                                           time.localtime(entry.precheck_time)) if entry.precheck_time else "Never",
            "country_code": entry.country_code,
            "rbl_count": entry.rbl_count,
            "total_used": entry.total_used,
            "fail_count": entry.fail_count,
            "success_count": entry.success_count,
            "str": str(entry)
        }
    
    # ========== 页面路由 ==========
    @app.route("/")
    def index():
        """主页面（单页应用）"""
        return render_template("index.html")
    
    # ========== API 路由 ==========
    
    @app.route("/api/stats", methods=["GET"])
    def api_stats():
        """获取代理池统计信息"""
        stats = pool.stats()
        total = stats.get("total", 0)
        alive = stats.get("alive", 0)
        dead = stats.get("dead", 0)
        alive_rate = (alive / total * 100) if total > 0 else 0
        
        return jsonify({
            "total": total,
            "alive": alive,
            "dead": dead,
            "alive_rate": round(alive_rate, 2),
            "requests": stats.get("requests", 0),
            "success": stats.get("success", 0),
            "fail": stats.get("fail", 0)
        })
    
    @app.route("/api/proxies", methods=["GET"])
    def api_proxies():
        """获取所有代理列表"""
        entries = pool.entries()
        proxies = [entry_to_dict(entry, idx) for idx, entry in enumerate(entries)]
        
        # 支持按状态过滤
        status_filter = request.args.get("status")
        if status_filter:
            if status_filter == "alive":
                proxies = [p for p in proxies if p["status"] == "alive"]
            elif status_filter == "dead":
                proxies = [p for p in proxies if p["status"] == "dead"]
            elif status_filter == "untested":
                proxies = [p for p in proxies if p["status"] == "untested"]
        
        return jsonify(proxies)
    
    @app.route("/api/proxies", methods=["POST"])
    def api_add_proxies():
        """批量添加代理"""
        data = request.get_json()
        if not data or "proxies" not in data:
            raise BadRequest("Missing 'proxies' field")
        
        proxies_raw = data["proxies"]
        if not isinstance(proxies_raw, list):
            raise BadRequest("'proxies' must be a list")
        
        added = []
        errors = []
        
        for raw in proxies_raw:
            if not isinstance(raw, str):
                errors.append(f"Invalid proxy format: {raw}")
                continue
            
            entry = ProxyEntry.parse(raw)
            if entry is None:
                errors.append(f"Failed to parse: {raw}")
                continue
            
            # 检查是否已存在（基于字符串表示）
            existing_strs = [str(e) for e in pool.entries()]
            if str(entry) in existing_strs:
                errors.append(f"Proxy already exists: {raw}")
                continue
            
            pool.add(entry)
            added.append(str(entry))
        
        # 触发健康检测（如果健康检测器可用）
        if health_checker and added:
            try:
                # 异步触发检测
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(health_checker.check_all([entry for entry in pool.entries() 
                                                                  if str(entry) in added]))
            except Exception as e:
                logger.error(f"Failed to trigger health check: {e}")
        
        return jsonify({
            "added": added,
            "errors": errors,
            "success": len(errors) == 0
        }), 201 if added else 400
    
    @app.route("/api/proxies/<entry_id>", methods=["DELETE"])
    def api_delete_proxy(entry_id):
        """删除单个代理"""
        entry = get_entry_by_id(entry_id)
        if entry is None:
            raise NotFound(f"Proxy with ID {entry_id} not found")
        
        success = pool.remove(entry)
        return jsonify({"success": success})
    
    @app.route("/api/proxies/<entry_id>/check", methods=["POST"])
    def api_check_proxy(entry_id):
        """立即检测单个代理"""
        entry = get_entry_by_id(entry_id)
        if entry is None:
            raise NotFound(f"Proxy with ID {entry_id} not found")
        
        if not health_checker:
            return jsonify({"error": "Health checker not available"}), 500
        
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(health_checker.test_proxy(entry))
            
            # 更新代理状态
            prev_alive = entry.alive
            if result["success"]:
                entry.alive = True
                entry.latency_ms = result.get("latency_ms", entry.latency_ms)
                entry.success_count += 1
                entry.fail_count = 0
                pool.mark_alive(entry)
            else:
                entry.fail_count += 1
                entry.success_count = 0
                error = result["error"]
                if "PROXY_DEAD" in error or "auth failed" in error.lower():
                    entry.alive = False
                    pool.mark_dead(entry)
            
            entry.precheck_time = time.time()
            
            return jsonify({
                "success": True,
                "result": result,
                "new_status": "alive" if entry.alive else "dead"
            })
        except Exception as e:
            logger.error(f"Failed to check proxy: {e}")
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/proxies/<entry_id>/mark_dead", methods=["POST"])
    def api_mark_dead(entry_id):
        """手动标记死亡"""
        entry = get_entry_by_id(entry_id)
        if entry is None:
            raise NotFound(f"Proxy with ID {entry_id} not found")
        
        pool.mark_dead(entry)
        return jsonify({"success": True})
    
    @app.route("/api/proxies/<entry_id>/mark_alive", methods=["POST"])
    def api_mark_alive(entry_id):
        """手动标记存活（恢复）"""
        entry = get_entry_by_id(entry_id)
        if entry is None:
            raise NotFound(f"Proxy with ID {entry_id} not found")
        
        pool.mark_alive(entry)
        return jsonify({"success": True})
    
    @app.route("/api/config", methods=["GET"])
    def api_get_config():
        """获取当前配置"""
        # 合并 PoolConfig 和 UI 配置
        config_dict = ui_config.to_dict()
        
        # 从 pool.config 获取健康检测间隔
        if pool_config:
            config_dict["pool_health_check_interval"] = pool_config.health_check_interval
            config_dict["pool_health_check_timeout"] = pool_config.health_check_timeout
            config_dict["pool_max_size"] = pool_config.max_size
        else:
            config_dict["pool_health_check_interval"] = 300
            config_dict["pool_health_check_timeout"] = 10
            config_dict["pool_max_size"] = 1000
        
        return jsonify(config_dict)
    
    @app.route("/api/config", methods=["POST"])
    def api_update_config():
        """更新配置"""
        data = request.get_json()
        if not data:
            raise BadRequest("No data provided")
        
        # 更新 UI 配置
        ui_config.from_dict(data)
        
        # 更新 PoolConfig 的健康检测间隔（如果有）
        if pool_config and "health_check_interval" in data:
            pool_config.health_check_interval = data["health_check_interval"]
        
        # 更新调度模式（UI 配置已经更新）
        # 注意：实际调度模式需要在获取代理时传递给 pool.get()
        
        return jsonify({"success": True, "config": ui_config.to_dict()})
    
    @app.route("/api/check_all", methods=["POST"])
    def api_check_all():
        """触发全量健康检测"""
        if not health_checker:
            return jsonify({"error": "Health checker not available"}), 500
        
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(health_checker.check_all())
            return jsonify({"success": True})
        except Exception as e:
            logger.error(f"Failed to check all proxies: {e}")
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/export", methods=["GET"])
    def api_export():
        """导出所有代理为文本列表"""
        entries = pool.entries()
        proxies = [str(entry) for entry in entries]
        return Response("\n".join(proxies), mimetype="text/plain")
    
    return app

# ============================================================================
# 独立运行测试
# ============================================================================
if __name__ == "__main__":
    import argparse
    from proxy_pool.config import default_config
    
    parser = argparse.ArgumentParser(description="Proxy Pool Web UI")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    args = parser.parse_args()
    
    # 创建默认池和健康检测器
    config = default_config()
    pool = ProxyPool(config.pool)
    health_checker = HealthChecker(pool, config.pool)
    
    app = create_app(pool, health_checker, config.pool)
    
    print(f"Starting Proxy Pool Web UI at http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop")
    
    app.run(host=args.host, port=args.port, debug=args.debug)