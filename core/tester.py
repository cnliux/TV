#!/usr/bin/env python3
import asyncio
import aiohttp
from typing import List, Callable, Set
from .models import Channel
import logging
import re
from pathlib import Path
from datetime import datetime  # 添加这行导入

logger = logging.getLogger(__name__)

class SpeedTester:
    """测速模块"""

    def __init__(self, timeout: float, concurrency: int, max_attempts: int, 
                 min_download_speed: float, enable_logging: bool = True,
                 failed_urls_path: str = 'config/failed_urls.txt'):
        """
        初始化测速模块
        :param timeout: 测速超时时间（秒）
        :param concurrency: 并发测速数
        :param max_attempts: 最大尝试次数
        :param min_download_speed: 最小下载速度（KB/s）
        :param enable_logging: 是否启用日志输出
        :param failed_urls_path: 测速失败URL保存路径
        """
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(concurrency)
        self.max_attempts = max_attempts
        self.min_download_speed = min_download_speed
        self.enable_logging = enable_logging
        self.failed_urls_path = Path(failed_urls_path)
        self.logger = logging.getLogger(__name__)

    def is_in_white_list(self, channel: Channel, white_list: set) -> bool:
        """判断频道是否在白名单中"""
        normalized_name = re.sub(r'[^\w\s]', '', channel.name).strip().lower()
        normalized_url = channel.url.lower()
        
        for entry in white_list:
            norm_entry = re.sub(r'[^\w\s]', '', entry).strip().lower()
            if (norm_entry in normalized_url or 
                norm_entry == normalized_url or 
                norm_entry == normalized_name):
                return True
        return False

    async def test_channels(self, channels: List[Channel], progress_cb: Callable, 
                          failed_urls: Set[str], white_list: set):
        """
        批量测速并保存失败URL
        :param channels: 频道列表
        :param progress_cb: 进度回调函数
        :param failed_urls: 用于记录测速失败的URL
        :param white_list: 白名单列表
        """
        try:
            async with aiohttp.ClientSession() as session:
                tasks = [self._test(session, c, progress_cb, failed_urls, white_list) 
                        for c in channels]
                await asyncio.gather(*tasks)
        finally:
            # 确保保存失败URL
            if failed_urls:
                self._save_failed_urls(failed_urls)

    def _save_failed_urls(self, failed_urls: Set[str]):
        """保存测速失败的URL"""
        try:
            # 确保目录存在
            self.failed_urls_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.failed_urls_path, 'w', encoding='utf-8') as f:
                f.write("# 测速失败的URL列表\n")
                f.write(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write("\n".join(sorted(failed_urls)))
                f.write(f"\n\n# 总计: {len(failed_urls)} 个失败URL\n")
            
            self.logger.info(f"已保存 {len(failed_urls)} 个失败URL到 {self.failed_urls_path}")
        except Exception as e:
            self.logger.error(f"保存失败URL失败: {str(e)}", exc_info=True)

    async def _test(self, session: aiohttp.ClientSession, channel: Channel, 
                  progress_cb: Callable, failed_urls: Set[str], white_list: set):
        """
        测试单个频道
        :param session: aiohttp会话
        :param channel: 频道对象
        :param progress_cb: 进度回调函数
        :param failed_urls: 用于记录测速失败的URL
        :param white_list: 白名单列表
        """
        if self.is_in_white_list(channel, white_list):
            channel.status = 'online'
            progress_cb()
            return

        async with self.semaphore:
            for attempt in range(self.max_attempts):
                try:
                    headers = {'User-Agent': 'Mozilla/5.0'}
                    start = asyncio.get_event_loop().time()

                    # 发起请求
                    async with session.get(channel.url, headers=headers, 
                                         timeout=self.timeout) as resp:
                        # 检查响应状态码
                        if resp.status != 200:
                            if self.enable_logging:
                                self.logger.warning(
                                    f"⚠️ 测速失败 (尝试 {attempt + 1}/{self.max_attempts}): "
                                    f"{channel.name} ({channel.url}), 状态码: {resp.status}"
                                )
                            if attempt == self.max_attempts - 1:
                                channel.status = 'offline'
                                failed_urls.add(channel.url)
                            continue

                        # 检查响应体是否为空
                        content_length = int(resp.headers.get('Content-Length', 0))
                        if content_length <= 0:
                            if self.enable_logging:
                                self.logger.warning(
                                    f"⚠️ 测速失败 (尝试 {attempt + 1}/{self.max_attempts}): "
                                    f"{channel.name} ({channel.url}), 响应体为空"
                                )
                            if attempt == self.max_attempts - 1:
                                channel.status = 'offline'
                                failed_urls.add(channel.url)
                            continue

                        # 计算下载速度
                        download_time = asyncio.get_event_loop().time() - start
                        download_speed = (content_length / 1024) / download_time
                        channel.response_time = download_time
                        channel.download_speed = download_speed

                        if self.enable_logging:
                            if download_speed < self.min_download_speed:
                                self.logger.warning(
                                    f"⚠️ 测速失败 (尝试 {attempt + 1}/{self.max_attempts}): "
                                    f"{channel.name} ({channel.url}), "
                                    f"下载速度: {download_speed:.2f} KB/s "
                                    f"(低于 {self.min_download_speed:.2f} KB/s)"
                                )
                            else:
                                self.logger.info(
                                    f"✅ 测速成功: {channel.name} ({channel.url}), "
                                    f"下载速度: {download_speed:.2f} KB/s"
                                )

                        if download_speed < self.min_download_speed:
                            channel.status = 'offline'
                            if attempt == self.max_attempts - 1:
                                failed_urls.add(channel.url)
                        else:
                            channel.status = 'online'
                            break

                except aiohttp.ClientError as e:
                    if self.enable_logging:
                        self.logger.error(
                            f"❌ 网络错误 (尝试 {attempt+1}/{self.max_attempts}): "
                            f"{channel.name} ({channel.url}), 错误: {str(e)}"
                        )
                    if attempt == self.max_attempts - 1:
                        channel.status = 'offline'
                        failed_urls.add(channel.url)
                except asyncio.TimeoutError:
                    if self.enable_logging:
                        self.logger.error(
                            f"❌ 测速超时 (尝试 {attempt+1}/{self.max_attempts}): "
                            f"{channel.name} ({channel.url})"
                        )
                    if attempt == self.max_attempts - 1:
                        channel.status = 'offline'
                        failed_urls.add(channel.url)
                except Exception as e:
                    if self.enable_logging:
                        self.logger.error(
                            f"❌ 未知错误 (尝试 {attempt+1}/{self.max_attempts}): "
                            f"{channel.name} ({channel.url}), 错误: {str(e)}"
                        )
                    if attempt == self.max_attempts - 1:
                        channel.status = 'offline'
                        failed_urls.add(channel.url)

                # 每次尝试后等待1秒
                await asyncio.sleep(1)

        # 更新进度条
        progress_cb()
