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
    source_category: str = ""  # 永久保存最原始的分类
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
        # 永久保存最原始的分类（第一次设置后不再修改）
        if not self.source_category and self.original_category:
            self.source_category = self.original_category
        
        # 设置默认值
        self.tvg_name = self.tvg_name or self.name
        self.tvg_id = self.tvg_id or self.name
        self.group_title = self.group_title or self.category
        self.original_category = self.original_category or self.category
