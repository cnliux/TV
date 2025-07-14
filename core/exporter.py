from pathlib import Path
from typing import List, Callable, Set
import logging
import re
from .models import Channel

class ResultExporter:
    def __init__(self, output_dir: str, enable_history: bool, template_path: str, config, matcher):
        """
        初始化结果导出器。

        :param output_dir: 输出目录路径
        :param enable_history: 是否启用历史记录功能
        :param template_path: 分类模板文件路径
        :param config: 配置对象
        :param matcher: 分类匹配器
        """
        self.output_dir = Path(output_dir)
        self.enable_history = enable_history
        self.template_path = template_path
        self.config = config
        self.matcher = matcher
        self._ensure_dirs()

    def _ensure_dirs(self):
        """确保输出目录存在"""
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export(self, channels: List[Channel], progress_cb: Callable):
        """
        主导出流程。

        :param channels: 频道列表
        :param progress_cb: 进度回调函数
        """
        try:
            # 1. 按模板严格排序（白名单优先）
            whitelist = self._load_whitelist()
            include_uncategorized = self.config.getboolean('EXPORTER', 'include_uncategorized', fallback=False)
            sorted_channels = self.matcher.sort_channels_by_template(channels, whitelist, include_uncategorized)
            
            # 2. 分类IPv4/IPv6
            ipv4_channels, ipv6_channels = self._classify_channels(sorted_channels)
            
            # 3. 导出合并文件（受prefer_ip_version控制）
            self._export_combined_files(ipv4_channels, ipv6_channels)
            
            # 4. 导出独立文件（不受prefer_ip_version影响）
            self._export_separated_files(ipv4_channels, ipv6_channels)
            
            # 5. 导出未分类频道（可选）
            if include_uncategorized:
                self._export_uncategorized_channels(channels)
            
            progress_cb(1)
        except Exception as e:
            logging.error(f"导出失败: {str(e)}")
            raise

    def _load_whitelist(self) -> Set[str]:
        """
        加载白名单。

        :return: 白名单集合
        """
        whitelist_path = Path(self.config.get('WHITELIST', 'whitelist_path', fallback='config/whitelist.txt'))
        if whitelist_path.exists():
            with open(whitelist_path, 'r', encoding='utf-8') as f:
                return {line.strip() for line in f if line.strip() and not line.startswith('#')}
        return set()

    def _classify_channels(self, channels: List[Channel]) -> (List[Channel], List[Channel]):
        """分类IPv4和IPv6频道"""
        ipv6_pattern = re.compile(r'https?://(?:\[[a-fA-F0-9:]+\]|[a-fA-F0-9:]{4,})')
        ipv4_pattern = re.compile(r'https?://(?:\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|[\w.-]+)(?::\d+)?')

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

    def _export_combined_files(self, ipv4_channels: List[Channel], ipv6_channels: List[Channel]):
        """
        导出合并文件（all.txt/all.m3u）。

        :param ipv4_channels: IPv4频道列表
        :param ipv6_channels: IPv6频道列表
        """
        ipv4_channels = [c for c in ipv4_channels if c.category != "未分类"]
        ipv6_channels = [c for c in ipv6_channels if c.category != "未分类"]

        prefer_ip_version = self.config.get('MAIN', 'prefer_ip_version', fallback='both')
        if prefer_ip_version == 'ipv6':
            all_channels = ipv6_channels + ipv4_channels
        elif prefer_ip_version == 'ipv4':
            all_channels = ipv4_channels + ipv6_channels
        else:
            all_channels = ipv4_channels + ipv6_channels

        # 写入文件
        self._write_m3u_file(self.output_dir / "all.m3u", all_channels)
        self._write_txt_file(self.output_dir / "all.txt", all_channels)

    def _export_separated_files(self, ipv4_channels: List[Channel], ipv6_channels: List[Channel]):
        """
        导出独立文件（ipv4.txt/ipv6.txt）。

        :param ipv4_channels: IPv4频道列表
        :param ipv6_channels: IPv6频道列表
        """
        ipv4_channels = [c for c in ipv4_channels if c.category != "未分类"]
        ipv6_channels = [c for c in ipv6_channels if c.category != "未分类"]

        self._write_txt_file(self.output_dir / "ipv4.txt", ipv4_channels)
        self._write_m3u_file(self.output_dir / "ipv4.m3u", ipv4_channels)
        self._write_txt_file(self.output_dir / "ipv6.txt", ipv6_channels)
        self._write_m3u_file(self.output_dir / "ipv6.m3u", ipv6_channels)

    def _write_m3u_file(self, path: Path, channels: List[Channel]):
        """
        写入M3U文件。

        :param path: 输出文件路径
        :param channels: 频道列表
        """
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write("#EXTM3U\n")
                epg_url = self.config.get('EXPORTER', 'm3u_epg_url', fallback='')
                if epg_url:
                    f.write(f"#EXT-X-EPGURL:{epg_url}\n")  # 添加 EPG 地址
                seen_urls = set()
                for chan in channels:
                    if chan.status == 'online' and chan.url not in seen_urls:
                        logo_url = self.config.get('EXPORTER', 'm3u_logo_url', fallback='').format(name=chan.name)
                        f.write(f'#EXTINF:-1 tvg-name="{chan.name}" tvg-logo="{logo_url}" group-title="{chan.category}",{chan.name}\n')  # 添加图标 URL
                        f.write(f"{chan.url}\n")
                        seen_urls.add(chan.url)
            logging.info(f"写入M3U文件: {path} (唯一频道: {len(seen_urls)})")
        except IOError as e:
            logging.error(f"写入M3U失败: {path} ({str(e)})")

    def _write_txt_file(self, path: Path, channels: List[Channel]):
        """
        写入TXT文件（严格按模板分类顺序）。

        :param path: 输出文件路径
        :param channels: 频道列表
        """
        try:
            with open(path, 'w', encoding='utf-8') as f:
                seen_urls = set()
                for category in self.matcher._category_order:
                    category_channels = [c for c in channels if c.category == category and c.url not in seen_urls]
                    if category_channels:
                        f.write(f"{category},#genre#\n")
                        for chan in category_channels:
                            f.write(f"{chan.name},{chan.url}\n")
                            seen_urls.add(chan.url)
                        f.write("\n")
                
                # 处理未分类频道
                if self.config.getboolean('EXPORTER', 'include_uncategorized', fallback=False):
                    uncategorized = [c for c in channels if c.category == "未分类" and c.url not in seen_urls]
                    if uncategorized:
                        f.write("未分类,#genre#\n")
                        for chan in uncategorized:
                            f.write(f"{chan.name},{chan.url}\n")
            
            logging.info(f"写入TXT文件: {path} (唯一频道: {len(seen_urls)})")
        except IOError as e:
            logging.error(f"写入TXT失败: {path} ({str(e)})")

    def _export_uncategorized_channels(self, channels: List[Channel]):
        """
        导出未分类频道。

        :param channels: 频道列表
        """
        uncategorized = [c for c in channels if c.category == "未分类" and c.status == 'online']
        if not uncategorized:
            return

        path = self.output_dir / "uncategorized.txt"
        with open(path, 'w', encoding='utf-8') as f:
            f.write("未分类,#genre#\n")
            for chan in uncategorized:
                f.write(f"{chan.name},{chan.url}\n")
        logging.info(f"导出未分类频道: {path} ({len(uncategorized)}个)")
