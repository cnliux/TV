#!/usr/bin/env python3
import re
from typing import Generator, Dict, Optional
import logging
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from .models import Channel

class PlaylistParser:
    """M3U解析器（完整版）"""
    
    # 支持的标准EXTINF格式
    EXTINF_REGEX = re.compile(
        r'^#EXTINF:-?\d+\s*(?:tvg-id="([^"]*)")?\s*(?:tvg-name="([^"]*)")?\s*'
        r'(?:tvg-logo="([^"]*)")?\s*(?:group-title="([^"]*)")?\s*,\s*(.*?)\s*$',
        re.IGNORECASE
    )
    
    # 支持的简单格式 (name,url)
    SIMPLE_REGEX = re.compile(
        r'^(?!http)(?:group-title="([^"]*)",?\s*)?([^,#]+?)\s*,\s*(http[^\s#]+)',
        re.IGNORECASE
    )
    
    # URL行检测（增强版）
    URL_LINE_REGEX = re.compile(
        r'^(?P<url>http[^\s#]+)(?:\$.*)?$',  # 新增对$后缀的处理
        re.IGNORECASE
    )
    
    # 非法字符过滤
    INVALID_CHARS = re.compile(r'[^\w\u4e00-\u9fff\-_ ]')

    def __init__(self, config=None):
        self.config = config
        self.params_to_remove = self._init_remove_params()
        self.logger = logging.getLogger(__name__)
        self._last_extinf = None  # 新增初始化

    def _init_remove_params(self) -> set:
        """初始化需要移除的URL参数"""
        params = {'key', 'playlive', 'authid'}
        if self.config and self.config.has_section('URL_FILTER'):
            extra = self.config.get('URL_FILTER', 'remove_params', fallback='')
            params.update(p.strip() for p in extra.split(',') if p.strip())
        return params

    def parse(self, content: str) -> Generator[Channel, None, None]:
        """主解析方法"""
        lines = content.splitlines()
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            try:
                # 1. 尝试匹配EXTINF格式
                if extinf := self._parse_extinf(line):
                    self._last_extinf = extinf  # 使用 self._last_extinf 替代临时变量
                    continue
                
                # 2. 尝试匹配简单格式 (name,url)
                if (simple := self._parse_simple(line)) and simple['url']:
                    yield self._create_channel(**simple)
                    self._last_extinf = None
                    continue
                
                # 3. 尝试匹配纯URL行（结合前一个EXTINF）
                if (url := self._parse_url(line)) and self._last_extinf:
                    yield self._create_channel(**self._last_extinf, url=url)
                    self._last_extinf = None
                    continue
                
                # 4. 处理多URL情况（取第一个有效URL）
                if '#' in line and (first_url := self._get_first_url(line)):
                    if self._last_extinf:
                        yield self._create_channel(**self._last_extinf, url=first_url)
                    else:
                        yield self._create_channel(
                            name=self._extract_name_from_url(first_url),
                            url=first_url
                        )
                    self._last_extinf = None

            except Exception as e:
                self.logger.warning(f"解析行失败: {line[:50]}... ({str(e)})")
                continue

    def _parse_extinf(self, line: str) -> Optional[Dict]:
        """解析EXTINF行"""
        if not line.startswith('#EXTINF'):
            return None
        
        if match := self.EXTINF_REGEX.match(line):
            return {
                'tvg_id': match.group(1),
                'tvg_name': match.group(2),
                'tvg_logo': match.group(3),
                'group': match.group(4),
                'name': match.group(5)
            }
        return None

    def _parse_simple(self, line: str) -> Optional[Dict]:
        """解析简单格式行"""
        if match := self.SIMPLE_REGEX.match(line):
            return {
                'group': match.group(1),
                'name': match.group(2),
                'url': match.group(3)
            }
        return None

    def _parse_url(self, line: str) -> Optional[str]:
        """解析纯URL行（增强版）"""
        if match := self.URL_LINE_REGEX.match(line):
            return self._clean_url(match.group('url'))  # 使用命名分组
        return None

    def _get_first_url(self, line: str) -> Optional[str]:
        """从多URL行中提取第一个有效URL"""
        for part in line.split('#'):
            if url := self._parse_url(part):
                return url
        return None

    def _create_channel(self, name: str, url: str, **kwargs) -> Channel:
        """创建标准化频道对象"""
        # 名称清理
        clean_name = self.INVALID_CHARS.sub('', name.strip())
        if not clean_name:
            clean_name = self._extract_name_from_url(url) or f"未命名_{hash(url)}"
        
        # URL清理
        clean_url = self._clean_url(url)
        if not clean_url:
            raise ValueError("无效的URL")
        
        return Channel(
            name=clean_name,
            url=clean_url,
            category="未分类",  # 初始设为未分类，后续由matcher处理
            original_category=kwargs.get('group', ''),  # 保存原始分类
            tvg_id=kwargs.get('tvg_id'),
            tvg_name=kwargs.get('tvg_name'),
            tvg_logo=kwargs.get('tvg_logo'),
            group_title=kwargs.get('group')
        )

    def _clean_url(self, raw_url: str) -> str:
        """深度清理URL（增强版）"""
        if not raw_url:
            return ""
        
        # 1. 去除 $ 符号及其后的所有内容
        clean_url = re.sub(r'\$.*$', '', raw_url).strip()
        
        # 2. 移除参数和锚点
        clean_url = clean_url.split('?')[0].split('#')[0]
        
        # 3. 验证协议
        if not clean_url.startswith(('http://', 'https://', 'rtp://', 'udp://')):
            return ""
        
        # 4. 处理 IPv6 地址（特殊格式保留）
        if '://[' in clean_url:
            return clean_url
        
        # 5. 移除指定查询参数
        try:
            parsed = urlparse(clean_url)
            if parsed.query and self.params_to_remove:
                params = parse_qs(parsed.query, keep_blank_values=True)
                filtered = {
                    k: v for k, v in params.items() 
                    if k.lower() not in self.params_to_remove
                }
                new_query = urlencode(filtered, doseq=True)
                clean_url = urlunparse(parsed._replace(query=new_query))
        except Exception as e:
            self.logger.debug(f"URL参数处理失败: {clean_url[:50]}... ({str(e)})")
        
        # 6. 去除类似 $IPV4•线路145 的后缀
        clean_url = re.sub(r'\$IPV4•线路\d+', '', clean_url).strip()
        
        return clean_url

    def _extract_name_from_url(self, url: str) -> str:
        """从URL中提取频道名称"""
        try:
            # 从PLTV格式提取
            if 'PLTV' in url and (match := re.search(r'PLTV/[^/]+/\d+/(\d+)/', url)):
                return f"CH_{match.group(1)}"
            
            # 从域名提取
            if (netloc := urlparse(url).netloc) and '.' in netloc:
                return netloc.split('.')[-2]
            
            # 从路径提取
            if (path := urlparse(url).path.split('/')[-1]) and '.' in path:
                return path.split('.')[0]
                
        except Exception as e:
            self.logger.debug(f"URL名称提取失败: {url[:50]}... ({str(e)})")
        
        return ""
