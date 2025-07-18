# core/matcher.py
import re
import time
import logging
from typing import Dict, List, Set, Tuple
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
from .models import Channel
import configparser

logger = logging.getLogger(__name__)

class AutoCategoryMatcher:
    """分类匹配器（带缓存和调试模式）"""
    
    def __init__(self, template_path: str, config=None):
        self.template_path = template_path
        self.config = config
        self.enable_debug = config.getboolean('MATCHER', 'enable_debug_classification', fallback=False) if config else False
        self.enable_space_clean = config.getboolean('MATCHER', 'enable_space_clean', fallback=True) if config else True
        
        # 初始化缓存和统计
        self.normalize_cache = {}
        self.match_cache = {}
        self.cache_stats = {'hits': 0, 'misses': 0}
        self.performance_stats = {
            'total_channels': 0,
            'match_time': 0.0,
            'normalize_time': 0.0
        }
        
        # 解析模板
        self.categories = self._parse_template()
        self.name_mapping = self._build_name_mapping()
        self.suffixes = self._extract_suffixes()
        self.template_order = self._load_template_order()
        
        if self.enable_debug:
            logger.info("✅ 分类调试模式已启用")
        if self.enable_space_clean:
            logger.info("✅ 频道名空格清理功能已启用")

    def _clean_channel_name(self, name: str) -> str:
        """清理频道名称（处理空格和特殊字符）"""
        if not self.enable_space_clean:
            return name
            
        # 1. 去除首尾空格
        cleaned = re.sub(r'^\s+|\s+$', '', name)
        # 2. 合并中间多余空格
        cleaned = re.sub(r'\s+', ' ', cleaned)
        # 3. 替换常见特殊字符
        cleaned = cleaned.replace('_', ' ').replace('-', ' ')
        return cleaned

    def is_in_template(self, channel_name: str) -> bool:
        """检查频道是否在模板中（新增方法）"""
        return self.match(channel_name) != "未分类"

    def _extract_suffixes(self) -> List[str]:
        """从模板中提取后缀配置"""
        suffix_pattern = re.compile(r'#suffixes:(.*)')
        suffixes = ["高清", "HD", "综合"]
        
        try:
            with open(self.template_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if match := suffix_pattern.search(line):
                        return [s.strip() for s in match.group(1).split(',') if s.strip()]
        except Exception as e:
            logger.error(f"后缀提取失败: {str(e)}")
            
        return suffixes

    def _parse_template(self) -> Dict[str, List[re.Pattern]]:
        """解析模板文件（带正则缓存）"""
        categories = {}
        current_category = None
        
        try:
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
                        pattern = self._compile_cached(line.split('|')[0].strip())
                        if pattern:
                            categories[current_category].append(pattern)
        except Exception as e:
            logger.error(f"模板解析失败: {str(e)}")
            raise
            
        if not categories:
            logger.warning("⚠️ 模板文件为空或格式错误")
            
        logger.info(f"加载分类: {len(categories)}个分类，共{sum(len(p) for p in categories.values())}个规则")
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
        try:
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
                            name_mapping[clean_name.lower()] = standard_name
        except Exception as e:
            logger.error(f"名称映射构建失败: {str(e)}")
            
        logger.info(f"加载名称映射: {len(name_mapping)}个条目")
        return name_mapping

    def match(self, channel_name: str) -> str:
        """匹配频道分类（带详细调试输出）"""
        start_time = time.perf_counter()
        
        # 清理频道名称
        clean_name = self._clean_channel_name(channel_name)
        
        # 缓存检查（使用原始名称）
        if channel_name in self.match_cache:
            self.cache_stats['hits'] += 1
            return self.match_cache[channel_name]
        
        self.cache_stats['misses'] += 1
        
        if self.enable_debug:
            logger.debug(f"🔍🔍 开始匹配频道: '{channel_name}' (清理后: '{clean_name}')")
        
        # 使用清理后的名称进行匹配
        for category, patterns in self.categories.items():
            for pattern in patterns:
                try:
                    if pattern.search(clean_name):  # 使用清理后的名称
                        if self.enable_debug:
                            logger.debug(f"  匹配成功: '{clean_name}' -> {category} (规则: {pattern.pattern})")
                        
                        # 更新缓存（使用原始名称）
                        self.match_cache[channel_name] = category
                        
                        end_time = time.perf_counter()
                        self.performance_stats['match_time'] += (end_time - start_time)
                        
                        return category
                except Exception as e:
                    logger.error(f"匹配过程中出错: {channel_name}, 规则: {pattern.pattern}, 错误: {str(e)}")
        
        # 更新缓存和性能统计
        self.match_cache[channel_name] = "未分类"
        end_time = time.perf_counter()
        self.performance_stats['match_time'] += (end_time - start_time)
        
        return "未分类"

    def normalize_channel_name(self, channel_name: str) -> str:
        """规范化频道名称（去除后缀）"""
        start_time = time.perf_counter()
        
        # 缓存检查
        if channel_name in self.normalize_cache:
            self.cache_stats['hits'] += 1
            return self.normalize_cache[channel_name]
        
        self.cache_stats['misses'] += 1
        
        # 清理频道名称
        clean_name = self._clean_channel_name(channel_name)
        
        # 应用名称映射（使用小写键）
        normalized_name = self.name_mapping.get(clean_name.lower(), clean_name)
        
        # 更新缓存和性能统计
        self.normalize_cache[channel_name] = normalized_name
        end_time = time.perf_counter()
        self.performance_stats['normalize_time'] += (end_time - start_time)
        
        return normalized_name

    def batch_normalize(self, channel_names: List[str]) -> Dict[str, str]:
        """批量规范化频道名称（带缓存优化）"""
        result = {}
        for name in channel_names:
            result[name] = self.normalize_channel_name(name)
        return result

    def batch_match(self, channel_names: List[str]) -> Dict[str, str]:
        """批量匹配分类（带并行处理）"""
        total = len(channel_names)
        self.performance_stats['total_channels'] += total
        
        # 小批量直接处理
        if total < 1000:
            return {name: self.match(name) for name in channel_names}
        
        # 配置并行参数
        threads = self.config.getint('PERFORMANCE', 'classification_threads', fallback=4) if self.config else 4
        batch_size = self.config.getint('PERFORMANCE', 'classification_batch_size', fallback=2000) if self.config else 2000
        
        logger.info(f"🔁🔁 启动并行分类处理: 总数={total}, 线程数={threads}, 批次大小={batch_size}")
        
        results = {}
        batches = [channel_names[i:i+batch_size] for i in range(0, total, batch_size)]
        
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = [executor.submit(self._process_batch, batch) for batch in batches]
            
            for i, future in enumerate(as_completed(futures)):
                batch_results = future.result()
                results.update(batch_results)
                logger.debug(f"  完成批次 {i+1}/{len(futures)} (处理 {len(batch_results)} 个频道)")
        
        logger.info(f"✅ 批量分类完成: 总数={len(results)}")
        return results
    
    def _process_batch(self, batch: List[str]) -> Dict[str, str]:
        """处理单个批次"""
        return {name: self.match(name) for name in batch}

    def sort_channels_by_template(self, channels: List[Channel], whitelist: Set[str]) -> List[Channel]:
        """排序频道（白名单优先）"""
        # 白名单频道优先
        whitelist_channels = [c for c in channels if any(w in c.name or w in c.url for w in whitelist)]
        non_whitelist_channels = [c for c in channels if c not in whitelist_channels]
        
        # 按模板顺序排序
        sorted_channels = []
        
        for category in self.template_order.keys():
            # 获取当前分类下的频道
            category_channels = [c for c in non_whitelist_channels if c.category == category]
            
            # 按模板顺序排序
            if category in self.template_order:
                category_channels.sort(key=lambda c: self._get_channel_order(c, self.template_order[category]))
            
            sorted_channels.extend(category_channels)
            
        # 添加未在模板中的频道
        remaining = [c for c in non_whitelist_channels if c.category not in self.template_order]
        logger.info(f"未分类频道数量: {len(remaining)}")
        sorted_channels.extend(remaining)
        
        # 最后添加白名单频道
        return whitelist_channels + sorted_channels

    def _load_template_order(self) -> Dict[str, List[str]]:
        """加载模板中的频道顺序"""
        template_order = {}
        current_category = None
        
        try:
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
        except Exception as e:
            logger.error(f"模板顺序加载失败: {str(e)}")
            
        logger.info(f"加载模板顺序: {len(template_order)}个分类")
        return template_order

    def _get_channel_order(self, channel: Channel, channel_names: List[str]) -> int:
        """获取频道在模板中的顺序"""
        try:
            clean_name = self.normalize_channel_name(channel.name)
            for i, name in enumerate(channel_names):
                if re.search(f'^{name}$', clean_name):
                    return i
            return len(channel_names)  # 未定义的频道放最后
        except Exception as e:
            logger.error(f"频道排序错误: {channel.name}, 错误: {e}")
            return len(channel_names)
    
    def print_cache_stats(self):
        """打印缓存统计"""
        hits = self.cache_stats['hits']
        misses = self.cache_stats['misses']
        total = hits + misses
        hit_rate = (hits / total * 100) if total > 0 else 0
        
        logger.info("📊📊 缓存统计:")
        logger.info(f"  总请求: {total}")
        logger.info(f"  命中: {hits} ({hit_rate:.1f}%)")
        logger.info(f"  未命中: {misses}")
        logger.info(f"  名称缓存大小: {len(self.normalize_cache)}")
        logger.info(f"  匹配缓存大小: {len(self.match_cache)}")
    
    def print_performance_report(self):
        """打印性能报告"""
        total_time = self.performance_stats['match_time'] + self.performance_stats['normalize_time']
        total_channels = self.performance_stats['total_channels']
        channels_per_sec = total_channels / total_time if total_time > 0 else 0
        
        logger.info("🚀🚀 性能报告:")
        logger.info(f"  处理频道总数: {total_channels}")
        logger.info(f"  总处理时间: {total_time:.4f}秒")
        logger.info(f"  平均速度: {channels_per_sec:.0f} 频道/秒")
        logger.info(f"  名称规范化时间: {self.performance_stats['normalize_time']:.4f}秒")
        logger.info(f"  分类匹配时间: {self.performance_stats['match_time']:.4f}秒")
        
        if total_time > 0:
            logger.info(f"  时间占比: 匹配 {self.performance_stats['match_time']/total_time*100:.1f}%, 规范化 {self.performance_stats['normalize_time']/total_time*100:.1f}%")
