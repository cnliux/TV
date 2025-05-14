#!/usr/bin/env python3
from typing import List, Callable
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

    def _ensure_dirs(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_whitelist(self):
        """获取白名单"""
        whitelist_path = Path(self.config.get('WHITELIST', 'whitelist_path', fallback='config/whitelist.txt'))
        if whitelist_path.exists():
            with open(whitelist_path, 'r', encoding='utf-8') as f:
                whitelist = set(line.strip() for line in f if line.strip() and not line.startswith('#'))
        else:
            whitelist = set()
        return whitelist

    def export(self, channels: List[Channel], progress_cb: Callable):
        # 读取白名单
        whitelist = self.get_whitelist()

        # 按模板排序并优先白名单频道
        sorted_channels = self.matcher.sort_channels_by_template(channels, whitelist)

        # 分类并导出 IPv4 和 IPv6 频道
        ipv4_channels, ipv6_channels = self._classify_channels(sorted_channels)

        # 根据 prefer_ip_version 配置决定 all 文件中的频道顺序
        prefer_ip_version = self.config.get('MAIN', 'prefer_ip_version', fallback='ipv6')
        if prefer_ip_version == 'ipv6':
            all_channels = ipv6_channels + ipv4_channels
        elif prefer_ip_version == 'ipv4':
            all_channels = ipv4_channels + ipv6_channels
        else:
            all_channels = sorted_channels

        # 导出 all 频道到 all.m3u 和 all.txt 文件
        self._export_all(all_channels)

        # 导出 IPv4 和 IPv6 频道到各自的文件
        self._export_channels(ipv4_channels, "ipv4")
        self._export_channels(ipv6_channels, "ipv6")

        # 导出 CSV 文件（如果启用历史记录）
        if self.enable_history:
            self._export_csv(all_channels)

        # 添加未分类频道到未分类文件
        self._export_uncategorized_channels(channels)

        # 更新进度
        progress_cb(1)

    def _classify_channels(self, channels: List[Channel]) -> (List[Channel], List[Channel]):
        """分类 IPv4 和 IPv6 频道"""
        ipv4_pattern = re.compile(r'http://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')
        ipv6_pattern = re.compile(r'http://\[[a-fA-F0-9:]+]')

        ipv4_channels = []
        ipv6_channels = []

        for channel in channels:
            if ipv4_pattern.search(channel.url):
                ipv4_channels.append(channel)
            elif ipv6_pattern.search(channel.url):
                ipv6_channels.append(channel)

        return ipv4_channels, ipv6_channels

    def _export_all(self, channels: List[Channel]):
        """导出所有频道到 all.m3u 和 all.txt 文件"""
        # 获取配置
        m3u_filename = self.config.get('EXPORTER', 'm3u_filename', fallback='all.m3u')
        txt_filename = self.config.get('EXPORTER', 'txt_filename', fallback='all.txt')

        # 导出 M3U 文件
        with open(self.output_dir / m3u_filename, 'w', encoding='utf-8') as f:
            f.write(self._get_m3u_header())
            for channel in channels:
                if channel.status != 'online':  # 过滤不合格的频道
                    continue
                f.write(f'#EXTINF:-1 tvg-name="{channel.name}" group-title="{channel.category}", {channel.name}\n')
                f.write(f"{channel.url}\n")

        # 导出 TXT 文件
        with open(self.output_dir / txt_filename, 'w', encoding='utf-8') as f:
            seen_urls = set()
            current_category = None
            for channel in channels:
                if channel.status != 'online' or channel.url in seen_urls:  # 过滤不合格的频道和重复的 URL
                    continue
                if channel.category != current_category:
                    if current_category is not None:
                        f.write("\n")
                    f.write(f"{channel.category},#genre#\n")
                    current_category = channel.category
                f.write(f"{channel.name},{channel.url}\n")
                seen_urls.add(channel.url)

        logging.info(f"📄 生成的 M3U 文件: {(self.output_dir / m3u_filename).resolve()}")
        logging.info(f"📄 生成的 TXT 文件: {(self.output_dir / txt_filename).resolve()}")

    def _export_channels(self, channels: List[Channel], type_name: str):
        """导出频道到指定类型的文件"""
        # 获取配置
        output_txt = Path(self.config.get('PATHS', f'{type_name}_output_path', fallback=f'{type_name}.txt'))
        output_m3u = output_txt.with_suffix('.m3u')

        # 导出 TXT 文件
        with open(self.output_dir / output_txt, 'w', encoding='utf-8') as f_txt:
            seen_urls = set()
            current_category = None
            for channel in channels:
                if channel.status != 'online' or channel.url in seen_urls:  # 过滤不合格的频道和重复的 URL
                    continue
                if channel.category != current_category:
                    if current_category is not None:
                        f_txt.write("\n")
                    f_txt.write(f"{channel.category},#genre#\n")
                    current_category = channel.category
                f_txt.write(f"{channel.name},{channel.url}\n")
                seen_urls.add(channel.url)

        # 导出 M3U 文件
        with open(self.output_dir / output_m3u, 'w', encoding='utf-8') as f_m3u:
            f_m3u.write(self._get_m3u_header())
            for channel in channels:
                if channel.status != 'online':  # 过滤不合格的频道
                    continue
                f_m3u.write(f'#EXTINF:-1 tvg-name="{channel.name}" group-title="{channel.category}", {channel.name}\n')
                f_m3u.write(f"{channel.url}\n")

        logging.info(f"📄 生成的 {type_name} 地址文件: {(self.output_dir / output_txt).resolve()}")
        logging.info(f"📄 生成的 {type_name} M3U 文件: {(self.output_dir / output_m3u).resolve()}")

    def _get_m3u_header(self) -> str:
        """生成 M3U 文件头部"""
        epg_url = self.config.get('EXPORTER', 'm3u_epg_url', fallback='http://epg.51zmt.top:8000/cc.xml.gz')
        return f'#EXTM3U x-tvg-url="{epg_url}" catchup="append" catchup-source="?playseek=${{(b)yyyyMMddHHmmss}}-${{(e)yyyyMMddHHmmss}}"'

    def _export_csv(self, channels: List[Channel]):
        """导出历史记录到 CSV 文件"""
        csv_format = self.config.get('EXPORTER', 'csv_filename_format', fallback='history_{timestamp}.csv')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = csv_format.format(timestamp=timestamp)

        with open(self.output_dir / filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['频道名称', '分类', '状态', '响应时间', 'URL'])
            
            for channel in channels:
                writer.writerow([
                    channel.name,
                    channel.category,
                    channel.status,
                    f"{channel.response_time:.2f}s" if channel.response_time else 'N/A',
                    channel.url
                ])

        logging.info(f"📄 生成的 CSV 文件: {(self.output_dir / filename).resolve()}")

    def _export_uncategorized_channels(self, channels: List[Channel]):
        """导出未分类频道到未分类文件"""
        # 获取配置
        uncategorized_path = self.config.get('PATHS', 'uncategorized_channels_path', fallback='config/uncategorized_channels.txt')

        # 筛选未分类且在线的频道
        uncategorized_channels = [c for c in channels if c.category == "未分类" and c.status == 'online']

        if uncategorized_channels:
            # 导出未分类频道到文件
            with open(self.output_dir / uncategorized_path, 'w', encoding='utf-8') as f:
                f.write("未分类频道:\n")
                current_category = None
                for channel in uncategorized_channels:
                    if channel.category != current_category:
                        if current_category is not None:
                            f.write("\n")
                        f.write(f"{channel.category},#genre#\n")
                        current_category = channel.category
                    f.write(f"{channel.name},{channel.url}\n")

            logging.info(f"📄 生成的未分类频道文件: {(self.output_dir / uncategorized_path).resolve()}")
