# -*- coding: utf-8 -*-
"""
代理池配置模块
提供配置加载、保存、验证等功能
"""
import json
from typing import Any, Dict, Optional, List
from pathlib import Path
import logging

from .models import PoolConfig, ApiProxyConfig, RotateConfig

logger = logging.getLogger(__name__)


class ProxyPoolConfig:
    """代理池完整配置"""
    
    def __init__(self, config_dict: Optional[Dict[str, Any]] = None):
        self.pool = PoolConfig()
        self.api = ApiProxyConfig()
        self.rotate = RotateConfig()
        self.file_sources: List[str] = []
        self.enable_health_check: bool = True
        self.log_level: str = "INFO"
        
        if config_dict:
            self._load_dict(config_dict)
    
    def _load_dict(self, config_dict: Dict[str, Any]):
        """从字典加载配置"""
        if "pool" in config_dict:
            for key, value in config_dict["pool"].items():
                if hasattr(self.pool, key):
                    setattr(self.pool, key, value)
        
        if "api" in config_dict:
            for key, value in config_dict["api"].items():
                if hasattr(self.api, key):
                    setattr(self.api, key, value)
        
        if "rotate" in config_dict:
            for key, value in config_dict["rotate"].items():
                if hasattr(self.rotate, key):
                    setattr(self.rotate, key, value)
        
        self.file_sources = config_dict.get("file_sources", [])
        self.enable_health_check = config_dict.get("enable_health_check", True)
        self.log_level = config_dict.get("log_level", "INFO")
    
    @classmethod
    def from_json(cls, filepath: str) -> "ProxyPoolConfig":
        """从JSON文件加载配置"""
        with open(filepath, "r", encoding="utf-8") as f:
            config_dict = json.load(f)
        return cls(config_dict)
    
    @classmethod
    def from_yaml(cls, filepath: str) -> "ProxyPoolConfig":
        """从YAML文件加载配置（需要PyYAML包）"""
        try:
            import yaml
            with open(filepath, "r", encoding="utf-8") as f:
                config_dict = yaml.safe_load(f)
            return cls(config_dict)
        except ImportError:
            logger.error("PyYAML未安装，无法加载YAML配置。请安装: pip install PyYAML")
            raise
        except Exception as e:
            logger.error(f"加载YAML配置失败: {e}")
            raise
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "pool": {field: getattr(self.pool, field) 
                    for field in self.pool.__dataclass_fields__},
            "api": {field: getattr(self.api, field) 
                   for field in self.api.__dataclass_fields__},
            "rotate": {field: getattr(self.rotate, field) 
                      for field in self.rotate.__dataclass_fields__},
            "file_sources": self.file_sources,
            "enable_health_check": self.enable_health_check,
            "log_level": self.log_level,
        }
    
    def to_json(self, filepath: str) -> None:
        """保存为JSON文件"""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
    
    def validate(self) -> bool:
        """验证配置有效性"""
        # 基础验证
        if self.pool.max_size <= 0:
            logger.warning("pool.max_size 必须大于0")
            return False
        
        if self.pool.health_check_interval <= 0:
            logger.warning("pool.health_check_interval 必须大于0")
            return False
        
        if self.pool.health_check_timeout <= 0:
            logger.warning("pool.health_check_timeout 必须大于0")
            return False
        
        # API配置验证
        if self.api.enabled:
            if not self.api.url:
                logger.warning("API配置启用但未设置URL")
                return False
        
        # 文件源验证
        for filepath in self.file_sources:
            if not Path(filepath).exists():
                logger.warning(f"文件源不存在: {filepath}")
                # 不返回False，因为文件可能稍后创建
        
        return True


# 默认配置实例
def default_config() -> ProxyPoolConfig:
    """返回默认配置"""
    return ProxyPoolConfig()