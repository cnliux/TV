#!/usr/bin/env python3
import re
from typing import Dict, List, Set, Optional
import logging
from pathlib import Path
from .models import Channel

class AutoCategoryMatcher:
    def __init__(self, template_path: str):
        """
        初始化分类匹配器
        :param template_path: 模板文件路径
        """
        self.template_path = Path(template_path)
        # 初始化核心属性
        self._regex_cache = {}  # 正则表达式缓存
        self.suffixes = ["高清", "HD", "综合"]  # 需要移除的后缀
        self.name_mapping = {}  # 频道名称标准化映射
        self.categories = {}    # 分类规则存储
        
        # 验证模板文件
        if not self.template_path.exists():
            raise FileNotFoundError(f"分类模板文件不存在: {self.template_path}")
            
        try:
            self.categories = self._parse_template()
            self.name_mapping = self._build_name_mapping()
            logging.debug(f"成功加载分类模板，共 {len(self.categories)} 个分类")
        except Exception as e:
            logging.error(f"模板初始化失败: {str(e)}")
            raise

    def _parse_template(self) -> Dict[str, List[re.Pattern]]:
        """解析模板文件并构建分类规则"""
        categories = {}
        current_category = None
        
        with open(self.template_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                
                # 跳过空行和注释
                if not line or line.startswith('#'):
                    continue
                
                # 处理分类行 (格式: "分类名称,#genre#")
                if line.endswith(',#genre#'):
                    current_category = line.split(',')[0]
                    categories[current_category] = []
                    logging.debug(f"发现分类: {current_category}")
                    continue
                
                # 处理频道规则行
                if current_category is None:
                    logging.warning(f"第 {line_num} 行: 规则 '{line}' 没有对应的分类，将被忽略")
                    continue
                
                try:
                    # 缓存正则表达式避免重复编译
                    if line not in self._regex_cache:
                        self._regex_cache[line] = re.compile(line)
                    categories[current_category].append(self._regex_cache[line])
                except re.error as e:
                    logging.error(f"第 {line_num} 行: 无效的正则表达式 '{line}' ({str(e)})")
                    continue
                    
        return categories

    def _build_name_mapping(self) -> Dict[str, str]:
        """构建频道名称标准化映射表"""
        name_map = {}
        
        with open(self.template_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or line.endswith(',#genre#'):
                    continue
                
                # 处理多名称映射 (格式: "CCTV1|CCTV-1|中央电视台1")
                parts = [p.strip() for p in line.split('|')]
                if len(parts) > 1:
                    std_name = parts[0]
                    for name in parts:
                        name_map[name] = std_name
                        logging.debug(f"名称映射: {name} → {std_name}")
        
        return name_map

    def match(self, channel_name: str) -> str:
        """
        匹配频道分类
        :param channel_name: 原始频道名称
        :return: 分类名称（未匹配时返回"未分类"）
        """
        normalized_name = self.normalize_channel_name(channel_name)
        
        for category, patterns in self.categories.items():
            for pattern in patterns:
                if pattern.search(channel_name):
                    logging.debug(f"分类匹配: '{channel_name}' → 规则 '{pattern.pattern}' → 分类 '{category}'")
                    return category
        
        logging.debug(f"未匹配分类: '{channel_name}' → 默认分类 '未分类'")
        return "未分类"

    def normalize_channel_name(self, raw_name: str) -> str:
        """
        标准化频道名称
        1. 去除后缀（如"高清"、"HD"）
        2. 应用名称映射
        """
        # 去除前后空格
        name = raw_name.strip()
        
        # 去除指定后缀
        for suffix in self.suffixes:
            name = name.replace(suffix, "")
        
        # 应用名称映射
        return self.name_mapping.get(name, name)

    def is_in_template(self, channel_name: str) -> bool:
        """检查频道是否在模板中有定义"""
        return any(
            pattern.search(channel_name)
            for patterns in self.categories.values()
            for pattern in patterns
        )

    def sort_channels_by_template(self, channels: List[Channel], whitelist: Set[str]) -> List[Channel]:
        """
        按模板顺序排序频道
        :param channels: 待排序频道列表
        :param whitelist: 白名单集合
        :return: 排序后的频道列表
        """
        # 分离白名单频道
        whitelisted = [c for c in channels if self._is_whitelisted(c, whitelist)]
        others = [c for c in channels if not self._is_whitelisted(c, whitelist)]
        
        # 按模板分类顺序排序
        sorted_channels = []
        defined_categories = list(self.categories.keys())
        
        # 先添加白名单频道
        for category in defined_categories:
            sorted_channels.extend(c for c in whitelisted if c.category == category)
        
        # 添加普通频道
        for category in defined_categories:
            sorted_channels.extend(c for c in others if c.category == category)
        
        # 最后添加未分类频道
        sorted_channels.extend(
            c for c in channels 
            if c.category not in defined_categories
        )
        
        logging.info(f"频道排序完成: 总数={len(sorted_channels)} (白名单={len(whitelisted)})")
        return sorted_channels

    def _is_whitelisted(self, channel: Channel, whitelist: Set[str]) -> bool:
        """检查频道是否在白名单中"""
        normalized_name = self.normalize_channel_name(channel.name)
        return any(
            entry in channel.url or
            entry == channel.url or
            entry == normalized_name
            for entry in whitelist
        )

    def __repr__(self):
        return f"<AutoCategoryMatcher 分类数={len(self.categories)} 规则数={len(self._regex_cache)}>"
