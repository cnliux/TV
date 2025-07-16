# core/matcher.py

import re
from typing import Dict, List, Set
import logging
from functools import lru_cache
from .models import Channel

logger = logging.getLogger(__name__)

class AutoCategoryMatcher:
    """分类匹配器（带缓存和调试模式）"""
    
    def __init__(self, template_path: str, config=None):
        self.template_path = template_path
        self.config = config
        self.categories = self._parse_template()
        self.name_mapping = self._build_name_mapping()
        self.enable_debug = config.getboolean('MATCHER', 'enable_debug_classification', fallback=False) if config else False
        
        # 后缀列表（从模板中读取）
        self.suffixes = self._extract_suffixes()
        
    def _extract_suffixes(self) -> List[str]:
        """从模板中提取后缀配置"""
        suffix_pattern = re.compile(r'#suffixes:(.*)')
        suffixes = ["高清", "HD", "综合"]
        
        try:
            with open(self.template_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if match := suffix_pattern.search(line):
                        return [s.strip() for s in match.group(1).split(',') if s.strip()]
        except Exception:
            pass
            
        return suffixes

    def _parse_template(self) -> Dict[str, List[re.Pattern]]:
        """解析模板文件（带正则缓存）"""
        categories = {}
        current_category = None
        
        with open(self.template_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                    
                if line.endswith(',#genre#'):
                    current_category = line.split(',')[0]
                    categories[current_category] = []
                    continue
                    
                if current_category:
                    pattern = self._compile_cached(line)
                    if pattern:
                        categories[current_category].append(pattern)
                        
        return categories

    @lru_cache(maxsize=1024)
    def _compile_cached(self, pattern_str: str) -> re.Pattern:
        """带缓存的正则编译"""
        try:
            return re.compile(pattern_str)
        except re.error as e:
            logger.error(f"正则表达式编译失败: {pattern_str} ({str(e)})")
            return None

    def _build_name_mapping(self) -> Dict[str, str]:
        """构建名称映射（预处理为小写）"""
        name_mapping = {}
        with open(self.template_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or line.endswith(',#genre#'):
                    continue
                    
                parts = line.split('|')
                if len(parts) > 1:
                    standard_name = parts[0].strip()
                    for name in parts:
                        clean_name = name.strip()
                        name_mapping[clean_name] = standard_name
                        
        return name_mapping

    def match(self, channel_name: str) -> str:
        """匹配频道分类（带调试模式）"""
        if self.enable_debug:
            logger.debug(f"匹配频道: {channel_name}")
            
        for category, patterns in self.categories.items():
            for pattern in patterns:
                if pattern.search(channel_name):
                    if self.enable_debug:
                        logger.debug(f"匹配成功: {channel_name} -> {category} (规则: {pattern.pattern})")
                    return category
                    
        return "其他"

    def is_in_template(self, channel_name: str) -> bool:
        """检查频道是否在模板中"""
        for patterns in self.categories.values():
            for pattern in patterns:
                if pattern.search(channel_name):
                    return True
        return False

    def normalize_channel_name(self, channel_name: str) -> str:
        """规范化频道名称（去除后缀）"""
        name = channel_name.strip()
        
        # 去除后缀
        for suffix in self.suffixes:
            if name.endswith(suffix):
                name = name[:-len(suffix)]
                
        # 应用名称映射
        return self.name_mapping.get(name, name)

    def sort_channels_by_template(self, channels: List[Channel], whitelist: Set[str]) -> List[Channel]:
        """排序频道（白名单优先）"""
        template_order = self._load_template_order()
        
        sorted_channels = []
        for category, channel_names in template_order.items():
            # 获取当前分类下的频道
            category_channels = [c for c in channels if c.category == category]
            
            # 按模板顺序排序
            category_channels.sort(key=lambda c: self._get_channel_order(c, channel_names))
            
            sorted_channels.extend(category_channels)
            
        # 添加未分类频道
        remaining = [c for c in channels if c.category not in template_order]
        logger.info(f"未分类频道数量: {len(remaining)}")
        sorted_channels.extend(remaining)
        
        return sorted_channels

    def _load_template_order(self) -> Dict[str, List[str]]:
        """加载模板中的频道顺序"""
        template_order = {}
        current_category = None
        
        with open(self.template_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                    
                if line.endswith(',#genre#'):
                    current_category = line.split(',')[0]
                    template_order[current_category] = []
                    continue
                    
                if current_category:
                    parts = line.split('|')
                    if parts:
                        standard_name = parts[0].strip()
                        template_order[current_category].append(standard_name)
                        
        return template_order

    def _get_channel_order(self, channel: Channel, channel_names: List[str]) -> int:
        """获取频道在模板中的顺序"""
        try:
            clean_name = self.normalize_channel_name(channel.name)
            for i, name in enumerate(channel_names):
                if re.match(f'^{name}$', clean_name):
                    return i
            return len(channel_names)  # 未定义的频道放最后
        except Exception as e:
            logger.error(f"频道排序错误: {channel.name}, 错误: {e}")
            return len(channel_names)
