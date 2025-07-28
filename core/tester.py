# core/tester.py（修复版）
import asyncio
import aiohttp
from typing import List, Callable, Set
from .models import Channel
import logging
import time

logger = logging.getLogger(__name__)

class SpeedTester:
    """修复后的测速模块（添加失败URL收集）"""
    
    def __init__(self, timeout: float, concurrency: int, max_attempts: int,
                 min_download_speed: float, enable_logging: bool = True):
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(concurrency)
        self.max_attempts = max_attempts
        self.min_download_speed = min_download_speed
        self.enable_logging = enable_logging
        self.success_count = 0
        self.total_count = 0

    async def test_channels(self, channels: List[Channel], progress_cb: Callable,
                          failed_urls: Set[str], white_list: set):
        """批量测速（修复统计逻辑）"""
        self.total_count = len(channels)
        self.success_count = 0
        
        async with aiohttp.ClientSession() as session:
            tasks = [self._test_channel(session, c, progress_cb, failed_urls, white_list)
                    for c in channels]
            await asyncio.gather(*tasks)

    async def _test_channel(self, session: aiohttp.ClientSession, channel: Channel,
                          progress_cb: Callable, failed_urls: Set[str], white_list: set):
        """测试单个频道（添加失败URL收集）"""
        if self._is_in_white_list(channel, white_list):
            channel.status = 'online'
            progress_cb()  # 正确调用进度回调
            return

        async with self.semaphore:
            try:
                success = await self._perform_test(session, channel)
                if success:
                    self.success_count += 1
                else:
                    # 添加失败URL到集合
                    failed_urls.add(channel.url)
                    logger.debug(f"测速失败: {channel.url}")
            except Exception as e:
                # 添加异常URL到集合
                failed_urls.add(channel.url)
                if self.enable_logging:
                    logger.warning(f"⚠️ 测速异常: {channel.url} - {str(e)}")
            finally:
                progress_cb()  # 正确调用进度回调

    async def _perform_test(self, session: aiohttp.ClientSession, channel: Channel) -> bool:
        """执行测速核心逻辑"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            start_time = time.time()
            async with session.get(channel.url, headers=headers, timeout=self.timeout) as resp:
                if resp.status != 200:
                    channel.status = 'offline'
                    return False
                
                # 简化的测速逻辑
                content = await resp.read()
                download_speed = len(content) / (time.time() - start_time) / 1024  # KB/s
                
                if download_speed >= self.min_download_speed:
                    channel.status = 'online'
                    channel.download_speed = download_speed
                    if self.enable_logging:
                        logger.info(f"✅ 测速成功: {channel.url} - 速度: {download_speed:.2f} KB/s")
                    return True
                else:
                    channel.status = 'offline'
                    if self.enable_logging:
                        logger.warning(f"⚠️ 速度过低: {channel.url} - {download_speed:.2f} KB/s < {self.min_download_speed} KB/s")
                    return False
                
        except Exception as e:
            channel.status = 'offline'
            return False

    def _is_in_white_list(self, channel: Channel, white_list: set) -> bool:
        """检查白名单"""
        return any(w in channel.url or w == channel.name for w in white_list)
