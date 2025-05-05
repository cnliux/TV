#!/usr/bin/env python3
from typing import List, Callable, Set, Dict
from pathlib import Path
from datetime import datetime
import csv
from urllib.parse import quote
import re
import logging
from .models import Channel

class ResultExporter:
    def __init__(self, output_dir: str, enable_history: bool, template_path: str, config, matcher):
        self.output_dir = Path(output_dir)
        self.enable_history = enable_history
        self.template_path = template_path
        self.config = config
        self.matcher = matcher
        self._ensure_dirs()
        self.ipv4_pattern = re.compile(r'http://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')
        self.ipv6_pattern = re.compile(r'http://\[[a-fA-F0-9:]+]')
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def _ensure_dirs(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export(self, channels: List[Channel], progress_cb: Callable):
        """主导出方法"""
        try:
            whitelist = self._load_whitelist()
            sorted_channels = self.matcher.sort_channels_by_template(channels, whitelist)
            
            # 从配置读取参数
            m3u_filename = self.config.get('EXPORTER', 'm3u_filename')
            epg_url = self.config.get('EXPORTER', 'm3u_epg_url')
            logo_url_template = self.config.get('EXPORTER', 'm3u_logo_url')
            
            # 导出文件
            self._export_m3u(sorted_channels, m3u_filename, epg_url, logo_url_template)
            progress_cb(1)
            
            txt_filename = self.config.get('EXPORTER', 'txt_filename')
            self._export_txt(sorted_channels, txt_filename)
            progress_cb(1)
            
            if self.enable_history:
                csv_format = self.config.get('EXPORTER', 'csv_filename_format')
                self._export_csv(sorted_channels, csv_format)
                progress_cb(1)

            # 单独导出IPv4/IPv6文件（不重复追加到all文件）
            self._export_ip_files(sorted_channels)
            
        except Exception as e:
            self.logger.error(f"导出失败: {str(e)}", exc_info=True)

    def _load_whitelist(self) -> Set[str]:
        """加载白名单"""
        whitelist_path = Path(self.config.get('WHITELIST', 'whitelist_path', fallback='config/whitelist.txt'))
        if not whitelist_path.exists():
            return set()
        with open(whitelist_path, 'r', encoding='utf-8') as f:
            return {line.strip() for line in f if line.strip() and not line.startswith('#')}

    def _sort_by_ip_version(self, channels: List[Channel]) -> List[Channel]:
        """根据IP版本偏好排序频道"""
        ipv4 = [c for c in channels if self.ipv4_pattern.search(c.url)]
        ipv6 = [c for c in channels if self.ipv6_pattern.search(c.url)]
        others = [c for c in channels if not (self.ipv4_pattern.search(c.url) or self.ipv6_pattern.search(c.url))]
        
        prefer = self.config.get('MAIN', 'prefer_ip_version', fallback='both')
        if prefer == 'ipv6':
            return ipv6 + ipv4 + others
        elif prefer == 'ipv4':
            return ipv4 + ipv6 + others
        return channels

    def _export_m3u(self, channels: List[Channel], filename: str, epg_url: str, logo_url_template: str):
        """导出M3U文件"""
        sorted_channels = self._sort_by_ip_version(channels)
        with open(self.output_dir / filename, 'w', encoding='utf-8') as f:
            f.write(f'#EXTM3U x-tvg-url="{epg_url}"\n')
            
            seen_urls = set()
            for channel in sorted_channels:
                if channel.status != 'online' or channel.url in seen_urls:
                    continue
                
                logo = self._generate_logo_url(logo_url_template, channel.name)
                f.write(f'#EXTINF:-1 tvg-name="{channel.name}"{logo} group-title="{channel.category}",{channel.name}\n')
                f.write(f"{channel.url}\n")
                seen_urls.add(channel.url)
        self.logger.info(f"M3U文件已生成: {filename}")

    def _export_txt(self, channels: List[Channel], filename: str):
        """导出TXT文件（修复重复分类行问题）"""
        sorted_channels = self._sort_by_ip_version(channels)
        with open(self.output_dir / filename, 'w', encoding='utf-8') as f:
            seen_urls = set()
            current_category = None
            
            for channel in sorted_channels:
                if channel.status != 'online' or channel.url in seen_urls:
                    continue
                
                # 关键修复：仅在分类变化时写入分类行
                if channel.category != current_category:
                    if current_category is not None:
                        f.write("\n")  # 分类间空行分隔
                    f.write(f"{channel.category},#genre#\n")
                    current_category = channel.category
                
                f.write(f"{channel.name},{channel.url}\n")
                seen_urls.add(channel.url)
        self.logger.info(f"TXT文件已生成: {filename}")

    def _export_csv(self, channels: List[Channel], filename_format: str):
        """导出CSV历史记录"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = filename_format.format(timestamp=timestamp)
        with open(self.output_dir / filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['频道名称', '分类', '状态', '响应时间', '下载速度', 'URL'])
            
            seen_urls = set()
            for channel in channels:
                if channel.url not in seen_urls:
                    writer.writerow([
                        channel.name,
                        channel.category,
                        channel.status,
                        f"{channel.response_time:.2f}s" if channel.response_time else 'N/A',
                        f"{channel.download_speed:.2f} KB/s" if channel.download_speed else 'N/A',
                        channel.url
                    ])
                    seen_urls.add(channel.url)
        self.logger.info(f"CSV历史记录已生成: {filename}")

    def _export_ip_files(self, channels: List[Channel]):
        """单独导出IPv4/IPv6文件"""
        ipv4_path = Path(self.config.get('PATHS', 'ipv4_output_path'))
        ipv6_path = Path(self.config.get('PATHS', 'ipv6_output_path'))
        
        with open(self.output_dir / ipv4_path, 'w', encoding='utf-8') as f4, \
             open(self.output_dir / ipv6_path, 'w', encoding='utf-8') as f6:
            
            current_cat4, current_cat6 = None, None
            seen4, seen6 = set(), set()
            
            for channel in channels:
                if channel.status != 'online':
                    continue
                
                if self.ipv4_pattern.search(channel.url) and channel.url not in seen4:
                    if channel.category != current_cat4:
                        if current_cat4 is not None:
                            f4.write("\n")
                        f4.write(f"{channel.category},#genre#\n")
                        current_cat4 = channel.category
                    f4.write(f"{channel.name},{channel.url}\n")
                    seen4.add(channel.url)
                
                elif self.ipv6_pattern.search(channel.url) and channel.url not in seen6:
                    if channel.category != current_cat6:
                        if current_cat6 is not None:
                            f6.write("\n")
                        f6.write(f"{channel.category},#genre#\n")
                        current_cat6 = channel.category
                    f6.write(f"{channel.name},{channel.url}\n")
                    seen6.add(channel.url)
        
        self.logger.info(f"IPv4文件已生成: {ipv4_path}")
        self.logger.info(f"IPv6文件已生成: {ipv6_path}")

    def _generate_logo_url(self, template: str, name: str) -> str:
        """生成台标URL"""
        if not template or '{name}' not in template:
            return ''
        return f' tvg-logo="{template.replace("{name}", quote(name))}"'
