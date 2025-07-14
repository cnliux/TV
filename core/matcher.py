import re
from typing import Dict, List, Set, Optional
import logging
from pathlib import Path
from .models import Channel

class AutoCategoryMatcher:
    def __init__(self, template_path: str):
        """
        初始化分类匹配器。

        :param template_path: 分类模板文件路径
        """
        self.template_path = Path(template_path)
        self._regex_cache = {}
        self.suffixes = ["高清", "HD", "综合"]  # 去除后缀的列表
        self.name_mapping = {}  # 名称映射表
        self.categories = {}  # 分类规则
        self._category_order = []  # 分类的原始顺序
        self._channel_order = {}   # 每个分类下的频道原始顺序
        
        if not self.template_path.exists():
            raise FileNotFoundError(f"分类模板文件不存在: {self.template_path}")
        self._parse_template()

    def _parse_template(self):
        """
        解析模板文件，记录分类和频道的原始顺序。
        """
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

    def match(self, raw_name: str) -> str:
        """
        根据频道名称匹配分类。

        :param raw_name: 原始频道名称
        :return: 匹配到的分类名称，如果未匹配到则返回 "未分类"
        """
        name = self.normalize_channel_name(raw_name)
        for category, patterns in self.categories.items():
            for pattern in patterns:
                if pattern.search(name):
                    return category
        return "未分类"

    def normalize_channel_name(self, raw_name: str) -> str:
        """
        标准化频道名称，去除后缀等。

        :param raw_name: 原始频道名称
        :return: 标准化后的频道名称
        """
        name = raw_name.strip()
        for suffix in self.suffixes:
            name = name.replace(suffix, "")
        return self.name_mapping.get(name, name)

    def sort_channels_by_template(self, channels: List[Channel], whitelist: Set[str], include_uncategorized: bool) -> List[Channel]:
        """
        严格按模板顺序排序，白名单频道优先。

        :param channels: 频道列表
        :param whitelist: 白名单集合
        :param include_uncategorized: 是否包含未分类频道
        :return: 排序后的频道列表
        """
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
        """
        检查频道是否在白名单中。

        :param channel: 频道对象
        :param whitelist: 白名单集合
        :return: 是否在白名单中
        """
        normalized_name = self.normalize_channel_name(channel.name)
        return any(
            entry in channel.url or
            entry == channel.url or
            entry == normalized_name
            for entry in whitelist
        )
