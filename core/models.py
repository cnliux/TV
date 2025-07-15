#!/usr/bin/env python3
from dataclasses import dataclass
from typing import Optional
import re

@dataclass
class Channel:
    """频道数据模型（完整版）"""
    name: str
    url: str
    category: str = "未分类"
    original_category: str = ""
    status: str = "pending"
    response_time: float = 0.0
    download_speed: float = 0.0
    tvg_id: Optional[str] = None
    tvg_name: Optional[str] = None
    tvg_logo: Optional[str] = None
    group_title: Optional[str] = None
    added_index: int = 0

    def __post_init__(self):
        """初始化后处理"""
        # 清理URL（实例级别二次清理）
        self.url = self._clean_url(self.url)
        
        # 设置默认值
        self.tvg_name = self.tvg_name or self.name
        self.tvg_id = self.tvg_id or self.name
        self.group_title = self.group_title or self.category
        self.original_category = self.original_category or self.category

    def _clean_url(self, url: str) -> str:
        """实例级别的URL清理"""
        if not url:
            return url
            
        # 1. 去除$符号及其后的所有内容
        clean_url = re.sub(r'\$.*$', '', url)
        
        # 2. 移除参数和锚点
        clean_url = clean_url.split('?')[0].split('#')[0]
        
        return clean_url.strip()
