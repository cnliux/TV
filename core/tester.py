import asyncio
import aiohttp
from typing import List, Callable, Set
from .models import Channel
import logging

class SpeedTester:
    """测速模块"""

    def __init__(self, timeout: float, concurrency: int, max_attempts: int, min_download_speed: float, enable_logging: bool = True):
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(concurrency)
        self.max_attempts = max_attempts
        self.min_download_speed = min_download_speed
        self.enable_logging = enable_logging
        self.logger = logging.getLogger(__name__)

    async def test_channels(self, channels: List[Channel], progress_cb: Callable, failed_urls: Set[str]):
        async with aiohttp.ClientSession() as session:
            tasks = [self._test(session, c, progress_cb, failed_urls) for c in channels]
            await asyncio.gather(*tasks)

    async def _test(self, session: aiohttp.ClientSession, channel: Channel, progress_cb: Callable, failed_urls: Set[str]):
        async with self.semaphore:
            for attempt in range(self.max_attempts):
                try:
                    headers = {'User-Agent': 'Mozilla/5.0'}
                    start = asyncio.get_event_loop().time()

                    async with session.get(channel.url, headers=headers, timeout=self.timeout) as resp:
                        if resp.status != 200:
                            if self.enable_logging:
                                self.logger.warning(f"⚠️ 测速失败 (尝试 {attempt + 1}/{self.max_attempts}): {channel.name} ({channel.url}), 状态码: {resp.status}")
                            if attempt == self.max_attempts - 1:
                                channel.status = 'offline'
                                failed_urls.add(channel.url)
                            continue

                        content_length = int(resp.headers.get('Content-Length', 0))
                        if content_length <= 0:
                            if self.enable_logging:
                                self.logger.warning(f"⚠️ 测速失败 (尝试 {attempt + 1}/{self.max_attempts}): {channel.name} ({channel.url}), 响应体为空")
                            if attempt == self.max_attempts - 1:
                                channel.status = 'offline'
                                failed_urls.add(channel.url)
                            continue

                        download_time = asyncio.get_event_loop().time() - start
                        download_speed = (content_length / 1024) / download_time
                        channel.response_time = download_time
                        channel.download_speed = download_speed

                        if self.enable_logging:
                            if download_speed < self.min_download_speed:  
                                self.logger.warning(f"⚠️ 测速失败 (尝试 {attempt + 1}/{self.max_attempts}): {channel.name} ({channel.url}), 下载速度: {download_speed:.2f} KB/s (低于 {self.min_download_speed:.2f} KB/s)")
                            else:
                                self.logger.info(f"✅ 测速成功: {channel.name} ({channel.url}), 下载速度: {download_speed:.2f} KB/s")

                        if download_speed < self.min_download_speed:
                            channel.status = 'offline'
                            failed_urls.add(channel.url)
                        else:
                            channel.status = 'online'

                        break

                except asyncio.TimeoutError:
                    if self.enable_logging:
                        self.logger.error(f"❌ 测速超时 (尝试 {attempt + 1}/{self.max_attempts}): {channel.name} ({channel.url})")
                    if attempt == self.max_attempts - 1:
                        channel.status = 'offline'
                        failed_urls.add(channel.url)
                except Exception as e:
                    if self.enable_logging:
                        self.logger.error(f"❌ 测速异常 (尝试 {attempt + 1}/{self.max_attempts}): {channel.name} ({channel.url}), 错误: {str(e)}")
                    if attempt == self.max_attempts - 1:
                        channel.status = 'offline'
                        failed_urls.add(channel.url)

                await asyncio.sleep(1)

            progress_cb()
