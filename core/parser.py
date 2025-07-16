# core/parser.py

import re
from typing import Generator, List
import logging
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from .models import Channel
from functools import lru_cache

logger = logging.getLogger(__name__)

class PlaylistParser:
    """M3U解析器（流式处理+分批处理优化）"""
    
    CHANNEL_REGEX = re.compile(r'^(.*?),(http.*)$', re.MULTILINE)
    EXTINF_REGEX = re.compile(r'#EXTINF:-?[\d.]*,?(.*?)\n(.*)')
    
    def __init__(self, config=None):
        self.config = config
        self.params_to_remove = set()
        if config and config.has_section('URL_FILTER'):
            params = config.get('URL_FILTER', 'remove_params', fallback='')
            self.params_to_remove = {p.strip() for p in params.split(',') if p.strip()}

    def parse(self, content: str) -> Generator[Channel, None, None]:
        """解析内容生成频道列表（分批处理优化）"""
        # 分批处理大内容
        lines = content.splitlines()
        batch_size = min(1000, len(lines) // 10 or 100)
        
        for i in range(0, len(lines), batch_size):
            batch = lines[i:i+batch_size]
            for channel in self._parse_batch(batch):
                yield channel

    def _parse_batch(self, batch: List[str]) -> Generator[Channel, None, None]:
        """解析内容批次"""
        channel_matches = []
        
        # 合并行处理
        current_extinf = None
        for line in batch:
            line = line.strip()
            if not line:
                continue
                
            if line.startswith('#EXTINF'):
                current_extinf = line
            elif current_extinf and line.startswith('http'):
                channel_matches.append((current_extinf, line))
                current_extinf = None
            else:
                # 处理标准格式
                if match := self.CHANNEL_REGEX.match(line):
                    channel_matches.append(match.groups())
                elif match := self.EXTINF_REGEX.match(line):
                    channel_matches.append(match.groups())

        # 生成频道对象
        for name, url in channel_matches:
            clean_url = self._clean_url(url)
            yield Channel(name=self._clean_name(name), url=clean_url)

    def _clean_name(self, raw_name: str) -> str:
        """清理频道名称"""
        return raw_name.split(',')[-1].strip()

    def _clean_url(self, raw_url: str) -> str:
        """清理URL（带参数过滤）"""
        # 先去除$及其后面参数
        url = raw_url.split('$')[0].strip()
        
        # 过滤查询参数
        if self.params_to_remove:
            try:
                parsed = urlparse(url)
                if parsed.query:
                    query_params = parse_qs(parsed.query, keep_blank_values=True)
                    filtered_params = {k: v for k, v in query_params.items() if k not in self.params_to_remove}
                    new_query = urlencode(filtered_params, doseq=True)
                    url = urlunparse(parsed._replace(query=new_query))
            except Exception as e:
                logger.warning(f"URL参数处理失败: {url}, 错误: {str(e)}")
        
        return url
