#!/usr/bin/env python3
import asyncio
import aiohttp
from typing import List, Callable, Set
from .models import Channel
import logging
import re

class SpeedTester:
    """测速模块"""

    def __init__(self, timeout: float, concurrency: int, max_attempts: int, min_download_speed: float, enable_logging: bool = True):
        """
        初始化测速模块。

        :param timeout: 测速超时时间（秒）。
        :param concurrency: 并发测速数。
        :param max_attempts: 最大尝试次数。
        :param min_download_speed: 最小下载速度（KB/s）。
        :param enable_logging: 是否启用日志输出。
        """
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(concurrency)
        self.max_attempts = max_attempts
        self.min_download_speed = min_download_speed  # 现在以 KB/s 为单位
        self.enable_logging = enable_logging
        self.logger = logging.getLogger(__name__)

    def is_in_white_list(self, channel: Channel, white_list: set) -> bool:
        """判断频道是否在白名单中"""
        # 使用规范化名称检查
        normalized_name = re.sub(r'[^\w\s]', '', channel.name).strip().lower()
        normalized_url = channel.url.lower()
        
        for entry in white_list:
            norm_entry = re.sub(r'[^\w\s]', '', entry).strip().lower()
            if (norm_entry in normalized_url or 
                norm_entry == normalized_url or 
                norm_entry == normalized_name):
                return True
        return False

    async def test_channels(self, channels: List[Channel], progress_cb: Callable, failed_urls: Set[str], white_list: set):
        """
        批量测速。

        :param channels: 频道列表。
        :param progress_cb: 进度回调函数，用于通知测速进度。
        :param failed_urls: 用于记录测速失败的 URL。
        :param white_list: 白名单列表。
        """
        async with aiohttp.ClientSession() as session:
            tasks = [self._test(session, c, progress_cb, failed_urls, white_list) for c in channels]
            await asyncio.gather(*tasks)

    async def _test(self, session: aiohttp.ClientSession, channel: Channel, progress_cb: Callable, failed_urls: Set[str], white_list: set):
        """
        测试单个频道。

        :param session: aiohttp 会话。
        :param channel: 频道对象。
        :param progress_cb: 进度回调函数。
        :param failed_urls: 用于记录测速失败的 URL。
        :param white_list: 白名单列表。
        """
        if self.is_in_white_list(channel, white_list):
            channel.status = 'online'
            return

        async with self.semaphore:
            for attempt in range(self.max_attempts):
                try:
                    headers = {'User-Agent': 'Mozilla/5.0'}
                    start = asyncio.get_event_loop().time()

                    # 发起请求
                    async with session.get(channel.url, headers=headers, timeout=self.timeout) as resp:
                        # 检查响应状态码
                        if resp.status != 200:
                            if self.enable_logging:
                                self.logger.warning(f"⚠️ 测速失败 (尝试 {attempt + 1}/{self.max_attempts}): {channel.name} ({channel.url}), 状态码: {resp.status}")
                            if attempt == self.max_attempts - 1:
                                channel.status = 'offline'
                                failed_urls.add(channel.url)
                            continue

                        # 检查响应体是否为空
                        content_length = int(resp.headers.get('Content-Length', 0))
                        if content_length <= 0:
                            if self.enable_logging:
                                self.logger.warning(f"⚠️ 测速失败 (尝试 {attempt + 1}/{self.max_attempts}): {channel.name} ({channel.url}), 响应体为空")
                            if attempt == self.max_attempts - 1:
                                channel.status = 'offline'
                                failed_urls.add(channel.url)
                            continue

                        # 计算下载速度并始终记录和输出实际速度
                        download_time = asyncio.get_event_loop().time() - start
                        download_speed = (content_length / 1024) / download_time  # 转换为 KB/s
                        channel.response_time = download_time
                        channel.download_speed = download_speed

                        if self.enable_logging:
                            if download_speed < self.min_download_speed:
                                self.logger.warning(f"⚠️ 测速失败 (尝试 {attempt + 1}/{self.max_attempts}): {channel.name} ({channel.url}), 下载速度: {download_speed:.2f} KB/s (低于 {self.min_download_speed:.2f} KB/s)")
                            else:
                                self.logger.info(f"✅ 测速成功: {channel.name} ({channel.url}), 下载速度: {download_speed:.2f} KB/s")

                        if download_speed < self.min_download_speed:  # 直接使用 KB/s 单位进行比较
                            channel.status = 'offline'
                            if attempt == self.max_attempts - 1:
                                failed_urls.add(channel.url)
                        else:
                            channel.status = 'online'
                            break

                except aiohttp.ClientError as e:
                    if self.enable_logging:
                        self.logger.error(f"❌ 网络错误 (尝试 {attempt+1}/{self.max_attempts}): {channel.name} ({channel.url}), 错误: {str(e)}")
                    if attempt == self.max_attempts - 1:
                        channel.status = 'offline'
                        failed_urls.add(channel.url)
                except asyncio.TimeoutError:
                    if self.enable_logging:
                        self.logger.error(f"❌ 测速超时 (尝试 {attempt+1}/{self.max_attempts}): {channel.name} ({channel.url})")
                    if attempt == self.max_attempts - 1:
                        channel.status = 'offline'
                        failed_urls.add(channel.url)
                except Exception as e:
                    if self.enable_logging:
                        self.logger.error(f"❌ 未知错误 (尝试 {attempt+1}/{self.max_attempts}): {channel.name} ({channel.url}), 错误: {str(e)}")
                    if attempt == self.max_attempts - 1:
                        channel.status = 'offline'
                        failed_urls.add(channel.url)

                # 每次尝试后等待 1 秒
                await asyncio.sleep(1)

            # 更新进度条
            progress_cb()
