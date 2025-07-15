#!/usr/bin/env python3
import aiohttp
import asyncio
from typing import List, Callable
import logging

class SourceFetcher:
    """异步订阅源获取器"""
    
    def __init__(self, timeout: float, concurrency: int, retries: int = 3):
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.semaphore = asyncio.Semaphore(concurrency)
        self.retries = retries
        self.logger = logging.getLogger(__name__)

    async def fetch_all(self, urls: List[str], progress_cb: Callable) -> List[str]:
        """批量获取订阅源"""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            tasks = [self._fetch_with_retry(session, url, progress_cb) for url in urls]
            return await asyncio.gather(*tasks)

    async def _fetch_with_retry(self, session: aiohttp.ClientSession, url: str, progress_cb: Callable) -> str:
        """带重试的获取逻辑"""
        for attempt in range(self.retries):
            try:
                async with self.semaphore:
                    async with session.get(url, headers={'User-Agent': 'Mozilla/5.0'}) as resp:
                        if resp.status != 200:
                            raise ValueError(f"HTTP {resp.status}")
                        content = await resp.text(encoding='utf-8', errors='replace')
                        self.logger.debug(f"成功获取: {url}")
                        progress_cb()  # 成功时也调用进度回调
                        return content
            except Exception as e:
                if attempt == self.retries - 1:
                    self.logger.warning(f"获取失败: {url} ({str(e)})")
                    progress_cb()  # 失败时也调用进度回调
                    return ""
                await asyncio.sleep(1)
            finally:
                progress_cb()  # 确保无论如何都会调用进度回调
