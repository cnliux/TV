#!/usr/bin/env python3
import aiohttp
import asyncio
from typing import List, Callable, Optional
import logging
from dataclasses import dataclass

@dataclass
class FetchResult:
    content: str = ""
    url: str = ""
    success: bool = False

class SourceFetcher:
    """异步订阅源获取器（优化版）"""
    
    def __init__(
        self,
        timeout: float = 15,
        concurrency: int = 10,
        retries: int = 2,
        whitelist: List[str] = None
    ):
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.semaphore = asyncio.Semaphore(concurrency)
        self.retries = retries
        self.whitelist = whitelist or [".m3u", ".txt"]
        self.logger = logging.getLogger(__name__)
        self._session = None

    async def fetch_all(self, urls: List[str], progress_cb: Callable) -> List[str]:
        """批量获取订阅源"""
        if not self._session:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        
        results = []
        tasks = []
        
        # 预过滤URL
        filtered_urls = [u for u in urls if any(ext in u for ext in self.whitelist)]
        
        for url in filtered_urls:
            task = asyncio.create_task(
                self._fetch_with_retry(url, progress_cb))
            tasks.append(task)
        
        # 分批处理避免内存问题
        for i in range(0, len(tasks), 100):
            batch = tasks[i:i+100]
            results.extend(await asyncio.gather(*batch))
            progress_cb(len(batch))  # 批量更新进度
        
        # 按原始URL顺序返回结果
        url_to_content = {r.url: r.content for r in results if r.success}
        return [url_to_content.get(url, "") for url in urls]

    async def _fetch_with_retry(self, url: str, progress_cb: Callable) -> FetchResult:
        """带重试的获取逻辑"""
        result = FetchResult(url=url)
        
        for attempt in range(self.retries):
            try:
                async with self.semaphore:
                    async with self._session.get(
                        url,
                        headers={'User-Agent': 'Mozilla/5.0'},
                        ssl=False  # 忽略SSL验证
                    ) as resp:
                        if resp.status != 200:
                            raise ValueError(f"HTTP {resp.status}")
                        
                        result.content = await resp.text(
                            encoding='utf-8',
                            errors='replace'
                        )
                        result.success = True
                        return result
                        
            except Exception as e:
                if attempt == self.retries - 1:
                    self.logger.debug(f"获取失败: {url} ({str(e)})")
                await asyncio.sleep(1)
        
        return result

    async def close(self):
        """关闭会话"""
        if self._session:
            await self._session.close()
            self._session = None
