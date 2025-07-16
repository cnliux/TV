#!/usr/bin/env python3
import logging
from pathlib import Path
from typing import List, Dict, Set, Callable, Tuple, Optional
import re
import configparser
from datetime import datetime
from .models import Channel
from .matcher import AutoCategoryMatcher

logger = logging.getLogger(__name__)

class ResultExporter:
    """增强版结果导出器，支持多种输出格式和严格分类管理"""
    
    def __init__(self, output_dir: str, enable_history: bool, template_path: str,
                 config: configparser.ConfigParser, matcher: AutoCategoryMatcher):
        """
        初始化导出器
        
        Args:
            output_dir: 输出目录路径
            enable_history: 是否启用历史记录
            template_path: 分类模板路径
            config: 配置对象
            matcher: 分类匹配器实例
        """
        self.output_dir = Path(output_dir)
        self.enable_history = enable_history
        self.config = config
        self.matcher = matcher
        
        # 初始化路径配置
        self.uncategorized_path = Path(config.get(
            'EXPORTER', 'uncategorized_channels_path',
            fallback='config/uncategorized_channels.txt'))
        self.failed_urls_path = Path(config.get(
            'TESTER', 'failed_urls_path',
            fallback='config/failed_urls.txt'))
        
        # EPG和台标配置
        self.epg_url = config.get('EXPORTER', 'm3u_epg_url', fallback='')
        self.logo_template = config.get(
            'EXPORTER', 'm3u_logo_url',
            fallback='https://epg.v1.mk/logo/{name}.png')
        
        # 创建必要目录
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """确保所有输出目录存在"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.uncategorized_path.parent.mkdir(parents=True, exist_ok=True)
        self.failed_urls_path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, channels: List[Channel], progress_cb: Callable, include_uncat: bool = False) -> Dict:
        """
        主导出流程
        
        Args:
            channels: 频道列表
            progress_cb: 进度回调函数
            include_uncat: 是否包含未分类频道
            
        Returns:
            包含导出统计信息的字典
        """
        try:
            # 加载白名单
            whitelist = self._load_whitelist()
            
            # 分离在线频道
            valid_channels = [c for c in channels if c.status == 'online']
            
            # 严格分离已分类和未分类频道
            categorized, uncategorized = self._separate_channels(valid_channels)
            
            # 按模板排序已分类频道
            sorted_channels = self.matcher.sort_channels_by_template(
                categorized, whitelist, include_uncategorized=include_uncat)
            
            # 按IP版本分类
            ipv4, ipv6 = self._classify_channels(sorted_channels)
            
            # 导出主文件
            stats = {
                'all': self._write_txt(self.output_dir / "all.txt", sorted_channels),
                'ipv4': self._write_txt(self.output_dir / "ipv4.txt", ipv4),
                'ipv6': self._write_txt(self.output_dir / "ipv6.txt", ipv6),
                'm3u': {
                    'all': self._write_m3u(self.output_dir / "all.m3u", sorted_channels),
                    'ipv4': self._write_m3u(self.output_dir / "ipv4.m3u", ipv4),
                    'ipv6': self._write_m3u(self.output_dir / "ipv6.m3u", ipv6)
                }
            }
            
            # 导出未分类频道
            uncat_count = self._export_uncategorized(uncategorized)
            
            # 更新进度
            progress_cb()
            
            return {
                "total_channels": len(valid_channels),
                "categorized": len(categorized),
                "uncategorized": uncat_count,
                "file_stats": stats
            }
            
        except Exception as e:
            logger.error(f"导出过程中发生错误: {str(e)}", exc_info=True)
            raise

    def _separate_channels(self, channels: List[Channel]) -> Tuple[List[Channel], List[Channel]]:
        """
        严格分离已分类和未分类频道
        
        Args:
            channels: 待分类的频道列表
            
        Returns:
            (已分类频道列表, 未分类频道列表)
        """
        categorized = []
        uncategorized = []
        
        for chan in channels:
            if chan.category == "未分类":
                uncategorized.append(chan)
            else:
                categorized.append(chan)
                
        return categorized, uncategorized

    def _write_txt(self, path: Path, channels: List[Channel]) -> int:
        """
        导出TXT格式的频道列表
        
        Args:
            path: 输出文件路径
            channels: 频道列表
            
        Returns:
            成功导出的频道数量
        """
        try:
            seen_urls = set()
            current_category = None
            count = 0
            
            with open(path, 'w', encoding='utf-8') as f:
                # 写入文件头
                f.write("# 电视频道列表\n")
                f.write(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# 总计频道: {len(channels)} 个\n\n")
                
                # 按分类写入频道
                for chan in channels:
                    if chan.category == "未分类" or chan.url in seen_urls:
                        continue
                        
                    # 分类标题
                    if chan.category != current_category:
                        if current_category is not None:
                            f.write("\n")
                        current_category = chan.category
                        f.write(f"{current_category},#genre#\n")
                    
                    # 频道条目
                    f.write(f"{chan.name},{chan.url}\n")
                    seen_urls.add(chan.url)
                    count += 1
                
                # 写入文件尾
                f.write(f"\n# 实际导出: {count} 个有效频道\n")
            
            logger.info(f"成功导出 TXT 文件: {path} (频道数: {count})")
            return count
            
        except Exception as e:
            logger.error(f"导出 TXT 文件失败: {path} - {str(e)}")
            return 0

    def _write_m3u(self, path: Path, channels: List[Channel]) -> int:
        """
        导出M3U格式的播放列表（修复：按模板顺序排列节目）
        
        Args:
            path: 输出文件路径
            channels: 频道列表
            
        Returns:
            成功导出的频道数量
        """
        try:
            # 按分类分组频道
            category_map = {}
            for chan in channels:
                if chan.category == "未分类":
                    continue
                    
                if chan.category not in category_map:
                    category_map[chan.category] = []
                category_map[chan.category].append(chan)
            
            # 按模板顺序获取分类
            ordered_categories = self._get_ordered_categories()
            
            seen_urls = set()
            count = 0
            
            with open(path, 'w', encoding='utf-8') as f:
                # M3U文件头
                f.write("#EXTM3U\n")
                if self.epg_url:
                    f.write(f"#EXT-X-EPGURL:{self.epg_url}\n")
                f.write(f"#EXT-X-PLAYLIST-TYPE:VOD\n")
                f.write(f"#EXT-X-VERSION:3\n\n")
                
                # 按模板顺序写入分类
                for category in ordered_categories:
                    if category not in category_map:
                        continue
                        
                    # 分类分组标记
                    f.write(f"#EXTGRP:{category}\n")
                    
                    # 写入该分类下的频道
                    for chan in category_map[category]:
                        if chan.url in seen_urls:
                            continue
                            
                        # 频道信息
                        logo = self.logo_template.format(name=chan.name)
                        f.write(
                            f'#EXTINF:-1 tvg-id="{chan.tvg_id}" '
                            f'tvg-name="{chan.tvg_name}" '
                            f'tvg-logo="{logo}" '
                            f'group-title="{category}",{chan.name}\n'
                        )
                        f.write(f"{chan.url}\n")
                        
                        seen_urls.add(chan.url)
                        count += 1
                    
                    # 分类间空行
                    f.write("\n")
                
                # 文件尾
                f.write(f"\n# 总计: {count} 个频道\n")
            
            logger.info(f"成功导出 M3U 文件: {path} (频道数: {count})")
            return count
            
        except Exception as e:
            logger.error(f"导出 M3U 文件失败: {path} - {str(e)}")
            return 0

    def _get_ordered_categories(self) -> List[str]:
        """获取按模板顺序排列的分类列表"""
        # 获取模板中的所有分类顺序
        template_categories = self.matcher.categories.keys()
        
        # 获取模板中定义的分类顺序
        if hasattr(self.matcher, '_category_order'):
            return self.matcher._category_order
        
        # 如果没有明确的顺序，则按字母顺序排序
        return sorted(template_categories)

    def _export_uncategorized(self, channels: List[Channel]) -> int:
        """
        导出未分类频道到专用文件
        
        Args:
            channels: 未分类频道列表
            
        Returns:
            成功导出的频道数量
        """
        if not channels:
            return 0
            
        try:
            # 按原始分类分组
            category_map = {}
            for chan in channels:
                category = chan.source_category if chan.source_category else "未分组"
                if category not in category_map:
                    category_map[category] = []
                category_map[category].append(chan)
            
            # 写入文件
            count = 0
            seen_urls = set()
            
            with open(self.uncategorized_path, 'w', encoding='utf-8') as f:
                # 文件头
                f.write("# 未分类频道列表\n")
                f.write(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# 总计未分类频道: {len(channels)} 个\n\n")
                
                # 按分类名称排序输出
                for category in sorted(category_map.keys()):
                    f.write(f"\n{category},#genre#\n")
                    
                    # 按频道名称排序
                    for chan in sorted(category_map[category], key=lambda x: x.name):
                        if chan.url not in seen_urls:
                            f.write(f"{chan.name},{chan.url}\n")
                            seen_urls.add(chan.url)
                            count += 1
                
                # 文件尾
                f.write(f"\n# 实际导出: {count} 个唯一频道\n")
            
            logger.info(f"已导出 {count} 个未分类频道 -> {self.uncategorized_path}")
            return count
            
        except Exception as e:
            logger.error(f"导出未分类频道失败: {str(e)}", exc_info=True)
            return 0

    def _load_whitelist(self) -> Set[str]:
        """加载白名单"""
        path = Path(self.config.get('WHITELIST', 'whitelist_path',
                                  fallback='config/whitelist.txt'))
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return {line.strip() for line in f if line.strip() and not line.startswith('#')}
        return set()

    def _classify_channels(self, channels: List[Channel]) -> Tuple[List[Channel], List[Channel]]:
        """
        按IP版本分类频道
        
        Args:
            channels: 待分类频道列表
            
        Returns:
            (IPv4频道列表, IPv6频道列表)
        """
        ipv6_pat = re.compile(r'https?://(?:\[[a-fA-F0-9:]+\]|[\w:]+:[a-fA-F0-9:]+)')
        ipv4_pat = re.compile(r'https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?')
        
        ipv4, ipv6 = [], []
        for chan in channels:
            if ipv6_pat.search(chan.url):
                ipv6.append(chan)
            elif ipv4_pat.search(chan.url):
                ipv4.append(chan)
            elif self.config.get('MAIN', 'prefer_ip_version', fallback='ipv4') == 'ipv6':
                ipv6.append(chan)
            else:
                ipv4.append(chan)
        
        return ipv4, ipv6
