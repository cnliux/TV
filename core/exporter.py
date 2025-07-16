# core/exporter.py

import logging
from pathlib import Path
from datetime import datetime
from typing import List, Callable, Set
from .models import Channel
import csv
from urllib.parse import quote

logger = logging.getLogger(__name__)

class ResultExporter:
    """结果导出器（支持多协议分类）"""
    
    def __init__(self, output_dir: str, enable_history: bool, template_path: str, config, matcher):
        self.output_dir = Path(output_dir)
        self.enable_history = enable_history
        self.template_path = template_path
        self.config = config
        self.matcher = matcher
        self._ensure_dirs()

    def _ensure_dirs(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_whitelist(self) -> Set[str]:
        """获取白名单（预处理为小写）"""
        whitelist_path = Path(self.config.get('WHITELIST', 'whitelist_path', fallback='config/whitelist.txt'))
        if whitelist_path.exists():
            with open(whitelist_path, 'r', encoding='utf-8') as f:
                return {line.strip().lower() for line in f if line.strip() and not line.startswith('#')}
        return set()

    def export(self, channels: List[Channel], progress_cb: Callable):
        """导出所有结果"""
        whitelist = self.get_whitelist()
        sorted_channels = self.matcher.sort_channels_by_template(channels, whitelist)
        
        # 多协议分类
        ipv4_channels, ipv6_channels, rtp_channels = self._classify_channels(sorted_channels)
        
        # 根据偏好决定顺序
        prefer_ip_version = self.config.get('MAIN', 'prefer_ip_version', fallback='ipv6')
        if prefer_ip_version == 'ipv6':
            all_channels = ipv6_channels + ipv4_channels + rtp_channels
        elif prefer_ip_version == 'ipv4':
            all_channels = ipv4_channels + ipv6_channels + rtp_channels
        else:  # both
            all_channels = sorted_channels
        
        # 导出主文件
        self._export_all(all_channels)
        
        # 导出协议特定文件
        self._export_channels(ipv4_channels, "ipv4")
        self._export_channels(ipv6_channels, "ipv6")
        self._export_channels(rtp_channels, "rtp")
        
        # 导出未分类频道
        self._export_uncategorized_channels(channels)
        
        progress_cb(1)

    def _classify_channels(self, channels: List[Channel]) -> tuple:
        """分类频道为IPv4、IPv6和RTP"""
        ipv4_channels = []
        ipv6_channels = []
        rtp_channels = []
        
        for channel in channels:
            ip_type = Channel.classify_ip_type(channel.url)
            if ip_type == "ipv4":
                ipv4_channels.append(channel)
            elif ip_type == "ipv6":
                ipv6_channels.append(channel)
            elif ip_type == "rtp":
                rtp_channels.append(channel)
        
        logger.info(f"频道分类: IPv4({len(ipv4_channels)}) | IPv6({len(ipv6_channels)}) | RTP({len(rtp_channels)})")
        return ipv4_channels, ipv6_channels, rtp_channels

    def _export_all(self, channels: List[Channel]):
        """导出主文件"""
        m3u_filename = self.config.get('EXPORTER', 'm3u_filename', fallback='all.m3u')
        txt_filename = self.config.get('EXPORTER', 'txt_filename', fallback='all.txt')
        
        self._export_m3u(channels, self.output_dir / m3u_filename)
        self._export_txt(channels, self.output_dir / txt_filename)

    def _export_m3u(self, channels: List[Channel], file_path: Path):
        """导出M3U文件"""
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(self._get_m3u_header())
            for channel in channels:
                if channel.status != 'online':
                    continue
                logo_url = self.config.get('EXPORTER', 'm3u_logo_url', fallback='').format(name=quote(channel.name))
                f.write(f'#EXTINF:-1 tvg-name="{channel.name}" group-title="{channel.category}" tvg-logo="{logo_url}", {channel.name}\n')
                f.write(f"{channel.url}\n")
        logger.info(f"📄📄 生成的 M3U 文件: {file_path.resolve()}")

    def _export_txt(self, channels: List[Channel], file_path: Path):
        """导出TXT文件"""
        with open(file_path, 'w', encoding='utf-8') as f:
            seen_urls = set()
            current_category = None
            for channel in channels:
                if channel.status != 'online' or channel.url in seen_urls:
                    continue
                if channel.category != current_category:
                    if current_category is not None:
                        f.write("\n")
                    f.write(f"{channel.category},#genre#\n")
                    current_category = channel.category
                f.write(f"{channel.name},{channel.url}\n")
                seen_urls.add(channel.url)
        logger.info(f"📄📄 生成的 TXT 文件: {file_path.resolve()}")

    def _export_channels(self, channels: List[Channel], type_name: str):
        """导出指定类型的文件"""
        output_txt = Path(self.config.get('PATHS', f'{type_name}_output_path', fallback=f'{type_name}.txt'))
        output_m3u = output_txt.with_suffix('.m3u')

        # 导出TXT文件
        with open(self.output_dir / output_txt, 'w', encoding='utf-8') as f_txt:
            seen_urls = set()
            current_category = None
            for channel in channels:
                if channel.status != 'online' or channel.url in seen_urls:
                    continue
                if channel.category != current_category:
                    if current_category is not None:
                        f_txt.write("\n")
                    f_txt.write(f"{channel.category},#genre#\n")
                    current_category = channel.category
                f_txt.write(f"{channel.name},{channel.url}\n")
                seen_urls.add(channel.url)

        # 导出M3U文件
        with open(self.output_dir / output_m3u, 'w', encoding='utf-8') as f_m3u:
            f_m3u.write(self._get_m3u_header())
            for channel in channels:
                if channel.status != 'online':
                    continue
                logo_url = self.config.get('EXPORTER', 'm3u_logo_url', fallback='').format(name=quote(channel.name))
                f_m3u.write(f'#EXTINF:-1 tvg-name="{channel.name}" group-title="{channel.category}" tvg-logo="{logo_url}", {channel.name}\n')
                f_m3u.write(f"{channel.url}\n")

        logger.info(f"📄📄 生成的 {type_name} 地址文件: {(self.output_dir / output_txt).resolve()}")
        logger.info(f"📄📄 生成的 {type_name} M3U 文件: {(self.output_dir / output_m3u).resolve()}")

    def _get_m3u_header(self) -> str:
        """生成M3U文件头部"""
        epg_url = self.config.get('EXPORTER', 'm3u_epg_url', fallback='http://epg.51zmt.top:8000/cc.xml.gz')
        return f'#EXTM3U x-tvg-url="{epg_url}" catchup="append" catchup-source="?playseek=${{(b)yyyyMMddHHmmss}}-${{(e)yyyyMMddHHmmss}}"\n'

    def _export_uncategorized_channels(self, channels: List[Channel]):
        """导出未分类频道到未分类文件"""
        uncategorized_path = Path(self.config.get('PATHS', 'uncategorized_channels_path', fallback='config/uncategorized_channels.txt'))
        
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
                    
            logger.info(f"📄📄 生成的未分类频道文件: {(self.output_dir / uncategorized_path).resolve()}")
