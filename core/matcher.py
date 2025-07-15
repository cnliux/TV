#!/usr/bin/env python3
import re
from typing import Dict, List, Set, Optional
import logging
from pathlib import Path
from .models import Channel

class AutoCategoryMatcher:
    def __init__(self, template_path: str):
        """
        初始化分类匹配器（完整版）
        :param template_path: 分类模板文件路径
        """
        self.template_path = Path(template_path)
        self._regex_cache = {}
        self.categories = {}
        self._category_order = []
        self._channel_order = {}
        
        if not self.template_path.exists():
            raise FileNotFoundError(f"分类模板文件不存在: {self.template_path}")
        self._parse_template()

    def _parse_template(self):
        """解析模板文件"""
        current_category = None
        with open(self.template_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                if line.endswith(',#genre#'):
                    current_category = line.split(',')[0]
                    self.categories[current_category] = []
                    self._category_order.append(current_category)
                    self._channel_order[current_category] = []
                elif current_category:
                    if line not in self._regex_cache:
                        self._regex_cache[line] = re.compile(line)
                    self.categories[current_category].append(self._regex_cache[line])
                    self._channel_order[current_category].append(line)

    def match(self, channel: Channel) -> str:
        """
        分类匹配（完整实现）
        优先级：
        1. 模板匹配
        2. 原始分类
        3. 默认未分类
        """
        # 1. 模板匹配
        normalized_name = self.normalize_channel_name(channel.name)
        for category, patterns in self.categories.items():
            for pattern in patterns:
                if pattern.search(normalized_name):
                    return category
        
        # 2. 使用原始分类（如果有效）
        if (channel.original_category and 
            channel.original_category != "未分类" and
            channel.original_category in self.categories):
            return channel.original_category
        
        # 3. 默认未分类
        return "未分类"

    def normalize_channel_name(self, raw_name: str) -> str:
        """标准化频道名称"""
        name = raw_name.strip()
        suffixes = ["高清", "HD", "标清", "FHD"]
        for suffix in suffixes:
            name = name.replace(suffix, "")
        return name

    def sort_channels_by_template(self, channels: List[Channel], whitelist: Set[str], include_uncategorized: bool) -> List[Channel]:
        """按模板排序频道（完整实现）"""
        whitelisted = [c for c in channels if self._is_whitelisted(c, whitelist)]
        others = [c for c in channels if not self._is_whitelisted(c, whitelist)]
        
        sorted_channels = []
        
        # 按模板分类顺序处理
        for category in self._category_order:
            # 处理白名单频道
            for pattern in self._channel_order[category]:
                for chan in whitelisted:
                    if chan.category == category and self._regex_cache[pattern].search(chan.name):
                        sorted_channels.append(chan)
            
            # 处理非白名单频道
            for pattern in self._channel_order[category]:
                for chan in others:
                    if chan.category == category and self._regex_cache[pattern].search(chan.name):
                        sorted_channels.append(chan)
        
        # 处理未分类频道
        if include_uncategorized:
            sorted_channels.extend(c for c in channels if c.category == "未分类")
        
        return sorted_channels

    def _is_whitelisted(self, channel: Channel, whitelist: Set[str]) -> bool:
        """检查是否在白名单中"""
        if not whitelist:
            return False
            
        normalized_name = self.normalize_channel_name(channel.name).lower()
        normalized_url = channel.url.lower()
        
        for entry in whitelist:
            norm_entry = entry.lower().strip()
            if (norm_entry in normalized_url or 
                norm_entry == normalized_url or 
                norm_entry == normalized_name):
                return True
        return False
