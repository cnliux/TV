# core/fetcher.py

import aiohttp
import asyncio
from typing import List, Callable
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

class SourceFetcher:
    """订阅源获取器（带错误重试和编码处理）"""
    
    def __init__(self, timeout: float, concurrency: int, retries: int = 3):
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.semaphore = asyncio.Semaphore(concurrency)
        self.retries = retries
        self.common_encodings = ['utf-8', 'gbk', 'latin-1']

    async def fetch_all(self, urls: List[str], progress_cb: Callable) -> List[str]:
        """批量获取订阅源（带并发控制）"""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            tasks = [self._fetch_with_retry(session, url, progress_cb) for url in urls]
            return await asyncio.gather(*tasks)

    async def _fetch_with_retry(self, session: aiohttp.ClientSession, url: str, progress_cb: Callable) -> str:
        """带重试机制的单次请求处理"""
        for attempt in range(self.retries):
            try:
                result = await self._fetch(session, url)
                if result:
                    logger.info(f"✅ 成功获取: {url}")
                else:
                    logger.warning(f"⚠️ 获取成功但内容为空: {url}")
                return result
            except Exception as e:
                logger.error(f"⚠️ 获取失败 (尝试 {attempt+1}/{self.retries}): {url} - {str(e)}")
                if attempt == self.retries - 1:
                    logger.error(f"❌❌ 最终失败: {url}")
                    return ""
                await asyncio.sleep(1)  # 指数退避
            finally:
                progress_cb()

    async def _fetch(self, session: aiohttp.ClientSession, url: str) -> str:
        """单次请求处理（带编码自动检测）"""
        async with self.semaphore:
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        raise Exception(f"HTTP状态码: {resp.status}")
                    
                    raw_content = await resp.read()
                    if not raw_content:
                        raise Exception("响应体为空")
                    
                    # 智能编码检测
                    content_type = resp.headers.get('Content-Type', '')
                    encoding = self._detect_encoding(content_type, raw_content)
                    
                    return raw_content.decode(encoding)
            except Exception as e:
                raise e

    @lru_cache(maxsize=128)
    def _detect_encoding(self, content_type: str, raw_content: bytes) -> str:
        """检测内容编码（带缓存）"""
        if 'charset=' in content_type:
            return content_type.split('charset=')[-1].strip().lower()
        
        # 尝试常见编码
        for enc in self.common_encodings:
            try:
                raw_content.decode(enc)
                return enc
            except UnicodeDecodeError:
                continue
        
        # 最终尝试utf-8并忽略错误
        return 'utf-8'
