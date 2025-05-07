from typing import List, Callable
from pathlib import Path
from datetime import datetime
import csv
from urllib.parse import quote
from .models import Channel

class ResultExporter:
    def __init__(self, output_dir: str, enable_history: bool, template_path: str, config, matcher):
        self.output_dir = Path(output_dir)
        self.enable_history = enable_history
        self.template_path = template_path
        self.config = config
        self.matcher = matcher  # matcher 参数传递到这里
        self._ensure_dirs()

    def _ensure_dirs(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export(self, channels: List[Channel], progress_cb: Callable):
        whitelist_path = Path(self.config.get('WHITELIST', 'whitelist_path', fallback='config/whitelist.txt'))
        whitelist = set()
        if whitelist_path.exists():
            with open(whitelist_path, 'r', encoding='utf-8') as f:
                whitelist = {line.strip() for line in f if line.strip() and not line.startswith('#')}

        sorted_channels = self.matcher.sort_channels_by_template(channels, whitelist)
        sorted_channels = sorted(sorted_channels, key=lambda x: x.category)

        m3u_filename = self.config.get('EXPORTER', 'm3u_filename')
        epg_url = self.config.get('EXPORTER', 'm3u_epg_url')
        logo_url_template = self.config.get('EXPORTER', 'm3u_logo_url')

        self._export_m3u(sorted_channels, m3u_filename, epg_url, logo_url_template)
        progress_cb(1)

        txt_filename = self.config.get('EXPORTER', 'txt_filename')
        self._export_txt(sorted_channels, txt_filename)
        progress_cb(1)

        if self.enable_history:
            csv_format = self.config.get('EXPORTER', 'csv_filename_format')
            self._export_csv(sorted_channels, csv_format)
            progress_cb(1)

    def _export_m3u(self, channels: List[Channel], filename: str, epg_url: str, logo_url_template: str):
        with open(self.output_dir / filename, 'w', encoding='utf-8') as f:
            header = f'#EXTM3U x-tvg-url="{epg_url}" catchup="append" catchup-source="?playseek=${{(b)yyyyMMddHHmmss}}-${{(e)yyyyMMddHHmmss}}"'
            f.write(header + "\n")
            
            seen_urls = set()
            current_category = None
            
            for channel in channels:
                if channel.status != 'online' or channel.url in seen_urls:
                    continue
                
                if channel.category != current_category:
                    f.write(f"{channel.category},#genre#\n")
                    current_category = channel.category
                
                logo_part = ''
                if logo_url_template and '{name}' in logo_url_template:
                    logo_url = logo_url_template.replace('{name}', quote(channel.name))
                    logo_part = f' tvg-logo="{logo_url}"'
                
                f.write(
                    f'#EXTINF:-1 tvg-name="{channel.name}"{logo_part} '
                    f'group-title="{channel.category}", {channel.name}\n'
                )
                f.write(f"{channel.url}\n")
                seen_urls.add(channel.url)

    def _export_txt(self, channels: List[Channel], filename: str):
        with open(self.output_dir / filename, 'w', encoding='utf-8') as f:
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

    def _export_csv(self, channels: List[Channel], filename_format: str):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = filename_format.format(timestamp=timestamp)
        
        with open(self.output_dir / filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['频道名称', '分类', '状态', '响应时间', 'URL'])
            
            seen_urls = set()
            for channel in channels:
                if channel.url not in seen_urls:
                    writer.writerow([
                        channel.name,
                        channel.category,
                        channel.status,
                        f"{channel.response_time:.2f}s" if channel.response_time else 'N/A',
                        channel.url
                    ])
                    seen_urls.add(channel.url)
