#!/usr/bin/env python3
from pathlib import Path
from typing import List, Callable, Set, Dict
import logging
from datetime import datetime
from .models import Channel
from .matcher import AutoCategoryMatcher
import re
import os

class ResultExporter:
    def __init__(self, output_dir: str, enable_history: bool, template_path: str, config, matcher):
        """
        初始化导出器
        :param output_dir: 输出目录
        :param enable_history: 是否启用历史记录
        :param template_path: 模板文件路径
        :param config: 配置对象
        :param matcher: 分类匹配器
        """
        self.output_dir = Path(output_dir)
        self.enable_history = enable_history
        self.template_path = template_path
        self.config = config
        self.matcher = matcher
        self.logger = logging.getLogger(__name__)
        
        # 从配置获取路径
        self.uncategorized_path = Path(config.get(
            'PATHS', 
            'uncategorized_channels_path',
            fallback='config/uncategorized_channels.txt'
        ))
        
        self._ensure_dirs()

    def _ensure_dirs(self):
        """确保所有输出目录存在"""
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.uncategorized_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.logger.error(f"创建目录失败: {str(e)}")
            raise

    def export(self, channels: List[Channel], progress_cb: Callable):
        """主导出流程"""
        try:
            # 加载白名单
            whitelist = self._load_whitelist()
            
            # 是否包含未分类频道
            include_uncategorized = self.config.getboolean('EXPORTER', 'include_uncategorized', fallback=True)
            
            # 按模板排序
            sorted_channels = self.matcher.sort_channels_by_template(
                channels, whitelist, include_uncategorized
            )
            
            # 分类IPv4/IPv6
            ipv4_channels, ipv6_channels = self._classify_channels(sorted_channels)
            
            # 导出合并文件
            self._export_combined_files(ipv4_channels, ipv6_channels)
            
            # 导出独立文件
            self._export_separated_files(ipv4_channels, ipv6_channels)
            
            # 导出未分类频道
            if include_uncategorized:
                self._export_uncategorized_channels(channels)
            
            progress_cb(1)
            
        except Exception as e:
            self.logger.error(f"导出过程中发生错误: {str(e)}", exc_info=True)
            raise

    def _load_whitelist(self) -> Set[str]:
        """加载白名单"""
        whitelist_path = Path(self.config.get('WHITELIST', 'whitelist_path', fallback='config/whitelist.txt'))
        if whitelist_path.exists():
            with open(whitelist_path, 'r', encoding='utf-8') as f:
                return {line.strip() for line in f if line.strip() and not line.startswith('#')}
        return set()

    def _classify_channels(self, channels: List[Channel]) -> (List[Channel], List[Channel]):
        """分类IPv4和IPv6频道"""
        ipv6_pattern = re.compile(r'https?://(?:\[[a-fA-F0-9:]+\]|[a-fA-F0-9:]{4,})')
        ipv4_pattern = re.compile(r'https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?')

        ipv4_channels = []
        ipv6_channels = []
        domain_handling = self.config.get('MAIN', 'domain_handling', fallback='ipv4')

        for channel in channels:
            url = channel.url
            if ipv6_pattern.search(url):
                ipv6_channels.append(channel)
            elif ipv4_pattern.search(url):
                ipv4_channels.append(channel)
            else:
                if domain_handling == 'ipv6':
                    ipv6_channels.append(channel)
                else:
                    ipv4_channels.append(channel)

        self.logger.info(f"IP分类统计: IPv4={len(ipv4_channels)}, IPv6={len(ipv6_channels)}")
        return ipv4_channels, ipv6_channels

    def _export_combined_files(self, ipv4_channels: List[Channel], ipv6_channels: List[Channel]):
        """导出合并文件"""
        prefer_ip_version = self.config.get('MAIN', 'prefer_ip_version', fallback='both')
        
        # 过滤掉未分类和离线频道
        ipv4_channels = [c for c in ipv4_channels if c.category != "未分类" and c.status == 'online']
        ipv6_channels = [c for c in ipv6_channels if c.category != "未分类" and c.status == 'online']
        
        if prefer_ip_version == 'ipv6':
            all_channels = ipv6_channels + ipv4_channels
        elif prefer_ip_version == 'ipv4':
            all_channels = ipv4_channels + ipv6_channels
        else:
            all_channels = ipv4_channels + ipv6_channels

        self._write_m3u_file(self.output_dir / "all.m3u", all_channels)
        self._write_txt_file(self.output_dir / "all.txt", all_channels)

    def _export_separated_files(self, ipv4_channels: List[Channel], ipv6_channels: List[Channel]):
        """导出独立文件"""
        # 过滤掉未分类和离线频道
        ipv4_channels = [c for c in ipv4_channels if c.category != "未分类" and c.status == 'online']
        ipv6_channels = [c for c in ipv6_channels if c.category != "未分类" and c.status == 'online']
        
        self._write_m3u_file(self.output_dir / "ipv4.m3u", ipv4_channels)
        self._write_txt_file(self.output_dir / "ipv4.txt", ipv4_channels)
        self._write_m3u_file(self.output_dir / "ipv6.m3u", ipv6_channels)
        self._write_txt_file(self.output_dir / "ipv6.txt", ipv6_channels)

    def _write_m3u_file(self, path: Path, channels: List[Channel]):
        """写入M3U文件"""
        try:
            seen_urls = set()
            with open(path, 'w', encoding='utf-8') as f:
                f.write("#EXTM3U\n")
                epg_url = self.config.get('EXPORTER', 'm3u_epg_url', fallback='')
                if epg_url:
                    f.write(f"#EXT-X-EPGURL:{epg_url}\n")
                
                for chan in channels:
                    if chan.url not in seen_urls:
                        logo_url = self.config.get('EXPORTER', 'm3u_logo_url', fallback='').format(name=chan.name)
                        f.write(f'#EXTINF:-1 tvg-id="{chan.tvg_id}" tvg-name="{chan.tvg_name}" '
                               f'tvg-logo="{logo_url}" group-title="{chan.group_title}",{chan.name}\n')
                        f.write(f"{chan.url}\n")
                        seen_urls.add(chan.url)
            
            self.logger.info(f"成功写入M3U文件: {path} (频道数: {len(seen_urls)})")
        except Exception as e:
            self.logger.error(f"写入M3U文件失败: {path} ({str(e)})")
            raise

    def _write_txt_file(self, path: Path, channels: List[Channel]):
        """写入TXT文件（严格按分类结构）"""
        try:
            seen_urls = set()
            with open(path, 'w', encoding='utf-8') as f:
                # 1. 写入模板分类
                for category in self.matcher._category_order:
                    cat_channels = [
                        c for c in channels 
                        if c.category == category 
                        and c.url not in seen_urls
                    ]
                    
                    if cat_channels:
                        f.write(f"{category},#genre#\n")
                        for chan in cat_channels:
                            f.write(f"{chan.name},{chan.url}\n")
                            seen_urls.add(chan.url)
                        f.write("\n")
                
                # 2. 写入其他有效分类（来自original_category）
                other_categories = {
                    c.original_category for c in channels 
                    if c.original_category 
                    and c.original_category != "未分类"
                    and c.original_category not in self.matcher._category_order
                }
                
                for cat in sorted(other_categories):
                    cat_channels = [
                        c for c in channels 
                        if c.original_category == cat 
                        and c.url not in seen_urls
                    ]
                    
                    if cat_channels:
                        f.write(f"{cat},#genre#\n")
                        for chan in cat_channels:
                            f.write(f"{chan.name},{chan.url}\n")
                            seen_urls.add(chan.url)
                        f.write("\n")
                
                # 3. 写入真正的未分类（没有有效original_category的）
                true_uncategorized = [
                    c for c in channels 
                    if c.category == "未分类" 
                    and (not c.original_category or c.original_category == "未分类")
                    and c.url not in seen_urls
                ]
                
                if true_uncategorized:
                    f.write("未分类,#genre#\n")
                    for chan in true_uncategorized:
                        f.write(f"{chan.name},{chan.url}\n")
            
            self.logger.info(f"成功写入TXT文件: {path} (频道数: {len(seen_urls)})")
        except Exception as e:
            self.logger.error(f"写入TXT文件失败: {path} ({str(e)})")
            raise

    def _export_uncategorized_channels(self, channels: List[Channel]):
        """
        导出纯净的未分类频道
        仅包含：
        - category为"未分类"
        - original_category为空或"未分类"
        - 在线状态
        """
        uncategorized = [
            c for c in channels 
            if c.category == "未分类" 
            and (not c.original_category or c.original_category == "未分类")
            and c.status == 'online'
        ]
        
        if not uncategorized:
            self.logger.info("未发现符合条件的未分类频道，跳过导出")
            return

        try:
            with open(self.uncategorized_path, 'w', encoding='utf-8') as f:
                f.write("未分类,#genre#\n")
                for chan in uncategorized:
                    f.write(f"{chan.name},{chan.url}\n")
            
            self.logger.info(
                f"成功导出纯净未分类频道\n"
                f"文件路径: {self.uncategorized_path}\n"
                f"频道数量: {len(uncategorized)}"
            )
        except Exception as e:
            self.logger.error(
                f"导出未分类频道失败\n"
                f"目标路径: {self.uncategorized_path}\n"
                f"错误详情: {str(e)}",
                exc_info=True
            )
            raise
