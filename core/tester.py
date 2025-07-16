#!/usr/bin/env python3
# 添加 shebang（可选，非必须）
import asyncio
import aiohttp
from typing import List, Callable, Set
from .models import Channel
import logging

logger = logging.getLogger(__name__)

import asyncio
import aiohttp
from typing import List, Callable, Set
from .models import Channel
import logging
import time

logger = logging.getLogger(__name__)

class SpeedTester:  # 确保类名完全匹配
    def __init__(self, timeout: float, concurrency: int, max_attempts: int,
                 min_download_speed: float, enable_logging: bool = True):
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(concurrency)
        self.max_attempts = max_attempts
        self.min_download_speed = min_download_speed
        self.enable_logging = enable_logging

    async def test_channels(self, channels: List[Channel], progress_cb: Callable,
                          failed_urls: Set[str], white_list: set):
        """批量测速方法"""
        async with aiohttp.ClientSession() as session:
            tasks = [self._test_channel(session, c, progress_cb, failed_urls, white_list) 
                    for c in channels]
            await asyncio.gather(*tasks)

    async def test_channels(self, channels: List[Channel], progress_cb: Callable, 
                           failed_urls: Set[str], white_list: set):
        """批量测速（带动态并发调整）"""
        self.total_count = len(channels)
        async with aiohttp.ClientSession() as session:
            tasks = [self._test_channel(session, c, progress_cb, failed_urls, white_list) for c in channels]
            await asyncio.gather(*tasks)

    async def _test_channel(self, session: aiohttp.ClientSession, channel: Channel, 
                           progress_cb: Callable, failed_urls: Set[str], white_list: set):
        """测试单个频道（带自适应重试）"""
        if self._is_in_white_list(channel, white_list):
            channel.status = 'online'
            progress_cb()
            return

        async with self.semaphore:
            delay = 1  # 初始延迟
            for attempt in range(self.max_attempts):
                try:
                    start_time = time.time()
                    success = await self._perform_test(session, channel)
                    test_duration = time.time() - start_time
                    
                    if success:
                        self.success_count += 1
                        break
                    else:
                        # 根据测试时长调整延迟
                        delay = max(1, min(10, test_duration * 2))
                except Exception as e:
                    logger.debug(f"测速异常: {channel.url} - {str(e)}")
                finally:
                    # 动态调整并发
                    if attempt < self.max_attempts - 1:
                        await asyncio.sleep(delay)
            
            # 更新进度
            progress_cb()
            
            # 每100个频道调整一次并发
            if self.total_count > 0 and (self.success_count + len(failed_urls)) % 100 == 0:
                await self._adjust_concurrency()

    async def _perform_test(self, session: aiohttp.ClientSession, channel: Channel) -> bool:
        """执行单次测速"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            start = time.time()
            
            async with session.get(channel.url, headers=headers, timeout=self.timeout) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP状态码: {resp.status}")
                
                content_length = int(resp.headers.get('Content-Length', 0))
                if content_length <= 0:
                    raise Exception("无效内容长度")
                
                # 简单读取部分数据计算速度
                chunk_size = 1024 * 10  # 10KB
                read_bytes = 0
                async for chunk in resp.content.iter_chunked(chunk_size):
                    read_bytes += len(chunk)
                    if read_bytes >= chunk_size * 2:  # 读取20KB后停止
                        break
                
                download_time = time.time() - start
                download_speed = (read_bytes / 1024) / download_time  # KB/s
                
                channel.response_time = download_time
                channel.download_speed = download_speed
                
                if self.enable_logging:
                    status = "✅" if download_speed >= self.min_download_speed else "⚠️"
                    logger.info(f"{status} {channel.name} - 速度: {download_speed:.2f} KB/s")
                
                if download_speed >= self.min_download_speed:
                    channel.status = 'online'
                    return True
                else:
                    channel.status = 'offline'
                    return False
                    
        except asyncio.TimeoutError:
            if self.enable_logging:
                logger.warning(f"⏱️ 超时: {channel.url}")
            channel.status = 'offline'
            return False
        except Exception as e:
            if self.enable_logging:
                logger.warning(f"⚠️ 错误: {channel.url} - {str(e)}")
            channel.status = 'offline'
            return False

    async def _adjust_concurrency(self):
        """动态调整并发数"""
        success_rate = self.success_count / self.total_count if self.total_count > 0 else 1
        
        if success_rate > 0.8 and self.current_concurrency < self.concurrency * 1.5:
            # 成功率高时增加并发
            new_concurrency = min(self.concurrency * 2, self.current_concurrency + 2)
            for _ in range(new_concurrency - self.current_concurrency):
                self.semaphore.release()
            self.current_concurrency = new_concurrency
            logger.info(f"↑ 增加并发至 {new_concurrency} (成功率: {success_rate:.1%})")
        elif success_rate < 0.6 and self.current_concurrency > 1:
            # 成功率低时减少并发
            reduce_by = max(1, self.current_concurrency // 4)
            new_concurrency = max(1, self.current_concurrency - reduce_by)
            # 暂时减少并发（通过不释放信号量）
            self.current_concurrency = new_concurrency
            logger.info(f"↓ 减少并发至 {new_concurrency} (成功率: {success_rate:.1%})")

    def _is_in_white_list(self, channel: Channel, white_list: set) -> bool:
        """检查频道是否在白名单中（预处理为小写）"""
        lower_whitelist = {w.lower() for w in white_list}
        return (channel.name.lower() in lower_whitelist or 
                channel.url.lower() in lower_whitelist or
                any(w in channel.url.lower() for w in lower_whitelist))
