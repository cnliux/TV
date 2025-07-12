#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime
from typing import List, Callable, Set, Dict, Optional
import csv
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
        """确保所有输出目录存在"""
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export(self, channels: List[Channel], progress_cb: Callable):
        """主导出流程"""
        try:
            # 1. 按模板排序频道
            whitelist = self._load_whitelist()
            sorted_channels = self.matcher.sort_channels_by_template(channels, whitelist)
            
            # 2. 分类IPv4/IPv6
            ipv4_channels, ipv6_channels = self._classify_channels(sorted_channels)
            
            # 3. 导出所有文件
            self._export_combined_files(ipv4_channels, ipv6_channels)
            self._export_separated_files(ipv4_channels, ipv6_channels)
            
            # 4. 导出未分类频道
            self._export_uncategorized_channels(channels)
            
            progress_cb(1)
        except Exception as e:
            logging.error(f"导出过程中发生错误: {str(e)}")
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
        ipv4_pattern = re.compile(r'https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?')
        ipv6_pattern = re.compile(r'https?://\[(?:[a-fA-F0-9:]+)\](?::\d+)?')

        ipv4_channels = []
        ipv6_channels = []

        for channel in channels:
            url = channel.url
            if ipv6_pattern.search(url):
                ipv6_channels.append(channel)
                self._log_classification(channel, "IPv6")
            elif ipv4_pattern.search(url):
                ipv4_channels.append(channel)
                self._log_classification(channel, "IPv4")
            else:
                logging.warning(f"未匹配到 IPv4 或 IPv6: {channel.name} ({channel.url})")

        logging.info(f"分类统计: IPv4={len(ipv4_channels)}, IPv6={len(ipv6_channels)}")
        return ipv4_channels, ipv6_channels

    def _log_classification(self, channel: Channel, ip_type: str):
        """记录分类调试日志"""
        if self.config.getboolean('DEBUG', f'enable_{ip_type.lower()}_classify_log', fallback=False):
            logging.debug(f"{ip_type}分类: {channel.name} ({channel.url}) → 分类: {channel.category}")

    def _export_combined_files(self, ipv4_channels: List[Channel], ipv6_channels: List[Channel]):
        """导出合并文件(all.m3u/all.txt)"""
        # 确定频道顺序
        prefer_ip_version = self.config.get('MAIN', 'prefer_ip_version', fallback='both')
        if prefer_ip_version == 'ipv6':
            all_channels = ipv6_channels + ipv4_channels
        elif prefer_ip_version == 'ipv4':
            all_channels = ipv4_channels + ipv6_channels
        else:
            all_channels = ipv4_channels + ipv6_channels

        # 导出M3U
        m3u_path = self.output_dir / self.config.get('EXPORTER', 'm3u_filename', fallback='all.m3u')
        self._write_m3u_file(m3u_path, all_channels)

        # 导出TXT
        txt_path = self.output_dir / self.config.get('EXPORTER', 'txt_filename', fallback='all.txt')
        self._write_txt_file(txt_path, all_channels)

    def _export_separated_files(self, ipv4_channels: List[Channel], ipv6_channels: List[Channel]):
        """分别导出IPv4/IPv6文件"""
        # IPv4文件
        ipv4_txt = self.output_dir / self.config.get('PATHS', 'ipv4_output_path', fallback='ipv4.txt')
        self._write_txt_file(ipv4_txt, ipv4_channels)
        self._write_m3u_file(ipv4_txt.with_suffix('.m3u'), ipv4_channels)

        # IPv6文件
        ipv6_txt = self.output_dir / self.config.get('PATHS', 'ipv6_output_path', fallback='ipv6.txt')
        self._write_txt_file(ipv6_txt, ipv6_channels)
        self._write_m3u_file(ipv6_txt.with_suffix('.m3u'), ipv6_channels)

    def _write_m3u_file(self, path: Path, channels: List[Channel]):
        """写入M3U文件"""
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(f"#EXTM3U x-tvg-url=\"{self.config.get('EXPORTER', 'm3u_epg_url', fallback='')}\"\n")
                for chan in channels:
                    if chan.status == 'online':
                        f.write(f'#EXTINF:-1 tvg-name="{chan.name}" group-title="{chan.category}",{chan.name}\n')
                        f.write(f"{chan.url}\n")
            logging.info(f"成功写入M3U文件: {path}")
        except IOError as e:
            logging.error(f"写入M3U文件失败 [{path}]: {str(e)}")

    def _write_txt_file(self, path: Path, channels: List[Channel]):
        """写入TXT文件"""
        try:
            with open(path, 'w', encoding='utf-8') as f:
                seen_urls = set()
                current_category = None
                
                for chan in channels:
                    if chan.status == 'online' and chan.url not in seen_urls:
                        if chan.category != current_category:
                            if current_category is not None:
                                f.write("\n")
                            f.write(f"{chan.category},#genre#\n")
                            current_category = chan.category
                        f.write(f"{chan.name},{chan.url}\n")
                        seen_urls.add(chan.url)
            logging.info(f"成功写入TXT文件: {path}")
        except IOError as e:
            logging.error(f"写入TXT文件失败 [{path}]: {str(e)}")

    def _export_uncategorized_channels(self, channels: List[Channel]):
        """导出未分类频道到独立文件"""
        uncategorized_path = self.output_dir / self.config.get(
            'PATHS', 
            'uncategorized_channels_path', 
            fallback='config/uncategorized_channels.txt'
        )
        
        try:
            uncategorized_path.parent.mkdir(parents=True, exist_ok=True)
            uncategorized_channels = [
                c for c in channels 
                if c.category == "未分类" 
                and c.status == 'online'
            ]
            
            if uncategorized_channels:
                with open(uncategorized_path, 'w', encoding='utf-8') as f:
                    f.write("# 未匹配分类规则的频道\n\n")
                    current_category = None
                    
                    for chan in uncategorized_channels:
                        if chan.category != current_category:
                            if current_category is not None:
                                f.write("\n")
                            f.write(f"{chan.category},#genre#\n")
                            current_category = chan.category
                        f.write(f"{chan.name},{chan.url}\n")
                
                logging.info(f"未分类频道已导出: {uncategorized_path}")
            else:
                logging.debug("未发现未分类的在线频道")
        except Exception as e:
            logging.error(f"导出未分类频道失败: {str(e)}")
