#!/usr/bin/env python3
import re
from typing import Generator
from .models import Channel
import logging
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

class PlaylistParser:
    """M3U解析器，使用生成器逐条处理数据"""
    
    CHANNEL_REGEX = re.compile(r'^(.*?),(http.*)$', re.MULTILINE)
    EXTINF_REGEX = re.compile(r'#EXTINF:-?[\d.]*,?(.*?)\n(.*)')

    def __init__(self, config=None):
        self.config = config
        self.params_to_remove = set()
        if config and config.has_section('URL_FILTER'):
            params = config.get('URL_FILTER', 'remove_params', fallback='')
            self.params_to_remove = {p.strip() for p in params.split(',') if p.strip()}

    def parse(self, content: str) -> Generator[Channel, None, None]:
        """解析内容生成频道列表（生成器）"""
        channel_matches = self.CHANNEL_REGEX.findall(content)
        if channel_matches:
            for name, url in channel_matches:
                # 清理 URL，去除 $ 及其后面的参数
                clean_url = self._clean_url(url)
                yield Channel(name=self._clean_name(name), url=clean_url)
        else:
            for name, url in self.EXTINF_REGEX.findall(content):
                # 清理 URL，去除 $ 及其后面的参数
                clean_url = self._clean_url(url)
                yield Channel(name=self._clean_name(name), url=clean_url)

    def _clean_name(self, raw_name: str) -> str:
        """清理频道名称"""
        return raw_name.split(',')[-1].strip()

    def _clean_url(self, raw_url: str) -> str:
        """清理 URL，去除 $ 及其后面的参数和指定查询参数"""
        # 先去除 $ 及其后面的参数
        url = raw_url.split('$')[0].strip()
        
        # 如果有需要移除的参数，处理查询参数
        if self.params_to_remove:
            try:
                parsed = urlparse(url)
                if parsed.query:
                    query_params = parse_qs(parsed.query, keep_blank_values=True)
                    # 移除指定的参数
                    filtered_params = {
                        k: v for k, v in query_params.items() 
                        if k not in self.params_to_remove
                    }
                    # 重新构建URL
                    new_query = urlencode(filtered_params, doseq=True)
                    url = urlunparse(parsed._replace(query=new_query))
            except Exception as e:
                logging.warning(f"URL参数处理失败: {url}, 错误: {str(e)}")
        
        return url
