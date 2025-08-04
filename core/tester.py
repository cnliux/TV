# core/tester.py
import asyncio
import aiohttp
from typing import List, Callable, Set, Tuple  # 添加 Tuple 导入
from .models import Channel
import logging
import time

logger = logging.getLogger(__name__)

class SpeedTester:
    """增强版测速模块（带详细调试日志）"""
    
    def __init__(self, timeout: float, concurrency: int, max_attempts: int,
                 min_download_speed: float, enable_logging: bool = True):
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.semaphore = asyncio.Semaphore(concurrency)
        self.max_attempts = max_attempts
        self.min_download_speed = min_download_speed
        self.enable_logging = enable_logging
        self.success_count = 0
        self.total_count = 0

    async def test_channels(self, channels: List[Channel], progress_cb: Callable,
                          failed_urls: Set[str], white_list: set):
        """批量测速主方法"""
        self.total_count = len(channels)
        self.success_count = 0
        
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            tasks = []
            for channel in channels:
                task = self._test_channel(
                    session, channel, progress_cb, failed_urls, white_list
                )
                tasks.append(task)
            
            await asyncio.gather(*tasks)

    async def _test_channel(self, session: aiohttp.ClientSession, channel: Channel,
                          progress_cb: Callable, failed_urls: Set[str], white_list: set):
        """测试单个频道（带详细调试日志）"""
        # 获取IP类型
        ip_type = Channel.classify_ip_type(channel.url)
        ipv6_match = Channel.IPV6_PATTERN.search(channel.url)
        
        if self._is_in_white_list(channel, white_list):
            channel.status = 'online'
            logger.debug(
                f"DEBUG - 频道分类: {channel.name} | "
                f"URL={channel.url} | "
                f"类型={ip_type} | "
                f"IPv6匹配={ipv6_match.group(0) if ipv6_match else '无'} | "
                f"状态=白名单免测"
            )
            progress_cb()
            return

        async with self.semaphore:
            try:
                success, speed, latency = await self._perform_test(session, channel)
                if success:
                    self.success_count += 1
                    status = 'online'
                else:
                    failed_urls.add(channel.url)
                    status = 'offline'
                
                # 调试日志（精确到每个频道的测速结果）
                logger.debug(
                    f"DEBUG - 频道分类: {channel.name} | "
                    f"URL={channel.url} | "
                    f"类型={ip_type} | "
                    f"IPv6匹配={ipv6_match.group(0) if ipv6_match else '无'} | "
                    f"网速={speed:.2f}KB/s | "
                    f"延迟={latency:.2f}ms | "
                    f"状态={status}"
                )
                
            except Exception as e:
                failed_urls.add(channel.url)
                logger.debug(
                    f"DEBUG - 频道分类: {channel.name} | "
                    f"URL={channel.url} | "
                    f"类型={ip_type} | "
                    f"IPv6匹配={ipv6_match.group(0) if ipv6_match else '无'} | "
                    f"网速=0.00KB/s | "
                    f"延迟=0.00ms | "
                    f"状态=error({str(e)})"
                )
            finally:
                progress_cb()

    async def _perform_test(self, session: aiohttp.ClientSession, channel: Channel) -> Tuple[bool, float, float]:
        """执行测速并返回（是否成功，速度KB/s，延迟ms）"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            start_time = time.time()
            
            async with session.get(channel.url, headers=headers) as resp:
                # 测量连接延迟
                latency = (time.time() - start_time) * 1000  # 转换为毫秒
                
                if resp.status != 200:
                    channel.status = 'offline'
                    return False, 0.0, latency
                
                # 测量下载速度
                content = await resp.read()
                download_time = time.time() - start_time
                speed = len(content) / download_time / 1024  # KB/s
                
                if speed >= self.min_download_speed:
                    channel.status = 'online'
                    channel.response_time = latency
                    channel.download_speed = speed
                    return True, speed, latency
                else:
                    channel.status = 'offline'
                    return False, speed, latency
                
        except Exception as e:
            channel.status = 'offline'
            raise e

    def _is_in_white_list(self, channel: Channel, white_list: set) -> bool:
        """检查白名单（不区分大小写）"""
        channel_url_lower = channel.url.lower()
        channel_name_lower = channel.name.lower()
        return any(
            w.lower() in channel_url_lower or 
            w.lower() == channel_name_lower 
            for w in white_list
        )
