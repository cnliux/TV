from pathlib import Path
from typing import List, Callable, Set
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
        
        # 日志控制
        self.debug_logging = config.getboolean('DEBUG', 'enable_debug_classification', fallback=False)

    def _ensure_dirs(self):
        """确保所有输出目录存在"""
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export(self, channels: List[Channel], progress_cb: Callable):
        """主导出流程"""
        try:
            whitelist = self._load_whitelist()
            sorted_channels = self.matcher.sort_channels_by_template(channels, whitelist)
            ipv4_channels, ipv6_channels = self._classify_channels(sorted_channels)
            
            self._export_combined_files(ipv4_channels, ipv6_channels)
            self._export_separated_files(ipv4_channels, ipv6_channels)
            self._export_uncategorized_channels(channels)
            
            progress_cb(1)
        except Exception as e:
            logging.error(f"导出错误: {str(e)}")
            raise

    def _classify_channels(self, channels: List[Channel]) -> (List[Channel], List[Channel]):
        """增强版IP分类方法"""
        # 预编译正则表达式
        ipv6_pattern = re.compile(
            r'(https?|rtp)://(?:\[?([a-fA-F0-9]{1,4}:){2,7}[a-fA-F0-9]{1,4}\]?)(?::\d+)?'
        )
        ipv4_pattern = re.compile(
            r'(https?|rtp)://\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)(?:/\d{1,2})?(?::\d+)?\b'
        )

        ipv4_channels = []
        ipv6_channels = []
        domain_handling = self.config.get('MAIN', 'domain_handling', fallback='ipv4')

        for channel in channels:
            url = channel.url
            if url.startswith("rtp://"):
                # 自动将 rtp:// 协议归为 IPv4
                ipv4_channels.append(channel)
                if self.debug_logging:
                    logging.debug(f"RTP分类为IPv4: {channel.name} ({url})")
            elif self._is_valid_ipv6(url, ipv6_pattern):
                ipv6_channels.append(channel)
                if self.debug_logging:
                    logging.debug(f"IPv6分类: {channel.name} ({url})")
            elif self._is_valid_ipv4(url, ipv4_pattern):
                ipv4_channels.append(channel)
                if self.debug_logging:
                    logging.debug(f"IPv4分类: {channel.name} ({url})")
            else:
                if domain_handling == 'ipv6':
                    ipv6_channels.append(channel)
                    if self.debug_logging:
                        logging.debug(f"域名归IPv6: {channel.name} ({url})")
                else:
                    ipv4_channels.append(channel)
                    if self.debug_logging:
                        logging.debug(f"域名归IPv4: {channel.name} ({url})")

        logging.info(f"分类统计 - IPv4: {len(ipv4_channels)}个, IPv6: {len(ipv6_channels)}个")
        return ipv4_channels, ipv6_channels

    def _is_valid_ipv6(self, url: str, pattern: re.Pattern) -> bool:
        """严格验证IPv6地址"""
        if not pattern.search(url):
            return False
        
        try:
            ip_part = re.search(r'\[?([a-fA-F0-9:]+)\]?', url).group(1)
            if ':::' in ip_part or ip_part.count('::') > 1:
                return False
            return True
        except Exception:
            return False

    def _is_valid_ipv4(self, url: str, pattern: re.Pattern) -> bool:
        """验证IPv4地址"""
        return bool(pattern.search(url))

    def _load_whitelist(self) -> Set[str]:
        """加载白名单"""
        whitelist_path = Path(self.config.get('WHITELIST', 'whitelist_path', fallback='config/whitelist.txt'))
        if whitelist_path.exists():
            with open(whitelist_path, 'r', encoding='utf-8') as f:
                return {line.strip() for line in f if line.strip() and not line.startswith('#')}
        return set()

    def _export_combined_files(self, ipv4_channels: List[Channel], ipv6_channels: List[Channel]):
        """导出合并文件"""
        prefer_ip_version = self.config.get('MAIN', 'prefer_ip_version', fallback='both')
        
        if prefer_ip_version == 'ipv6':
            all_channels = ipv6_channels + ipv4_channels
        elif prefer_ip_version == 'ipv4':
            all_channels = ipv4_channels + ipv6_channels
        else:
            all_channels = sorted(ipv4_channels + ipv6_channels, key=lambda x: x.added_index)

        m3u_path = self.output_dir / self.config.get('EXPORTER', 'm3u_filename', fallback='all.m3u')
        self._write_m3u_file(m3u_path, all_channels)

        txt_path = self.output_dir / self.config.get('EXPORTER', 'txt_filename', fallback='all.txt')
        self._write_txt_file(txt_path, all_channels)

    def _export_separated_files(self, ipv4_channels: List[Channel], ipv6_channels: List[Channel]):
        """分别导出IPv4/IPv6文件"""
        ipv4_txt = self.output_dir / self.config.get('PATHS', 'ipv4_output_path', fallback='ipv4.txt')
        self._write_txt_file(ipv4_txt, ipv4_channels)
        self._write_m3u_file(ipv4_txt.with_suffix('.m3u'), ipv4_channels)

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
            logging.info(f"写入M3U: {path} (在线: {sum(1 for c in channels if c.status=='online')}/{len(channels)})")
        except IOError as e:
            logging.error(f"写入M3U失败 [{path}]: {str(e)}")
            raise

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
            logging.info(f"写入TXT: {path} (去重: {len(seen_urls)}/{len(channels)})")
        except IOError as e:
            logging.error(f"写入TXT失败 [{path}]: {str(e)}")
            raise

    def _export_uncategorized_channels(self, channels: List[Channel]):
        """导出未分类频道（根据配置决定是否执行）"""
        # 检查是否启用未分类导出
        write_uncategorized = self.config.getboolean('EXPORTER', 'write_uncategorized', fallback=True)
        if not write_uncategorized:
            logging.info("配置已禁用未分类频道导出")
            return
            
        try:
            path = Path(self.config.get('PATHS', 'uncategorized_channels_path', fallback='config/uncategorized_channels.txt'))
            path.parent.mkdir(parents=True, exist_ok=True)
            
            uncategorized = [c for c in channels if c.category == "未分类" and c.status == 'online']
            
            if uncategorized:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write("# 未匹配分类规则的频道\n\n未分类,#genre#\n")
                    for chan in sorted(uncategorized, key=lambda x: x.name):
                        f.write(f"{chan.name},{chan.url}\n")
                logging.info(f"导出未分类频道: {path} ({len(uncategorized)}个)")
            else:
                logging.debug("未发现未分类频道")
        except Exception as e:
            logging.error(f"导出未分类频道失败: {str(e)}")
            raise
