# core/tester.py
import asyncio
import aiohttp
import random
import time
import re
import logging
from typing import List, Callable, Set, Tuple
from collections import defaultdict
from .models import Channel
from configparser import ConfigParser
import urllib.parse

logger = logging.getLogger(__name__)

class SpeedTester:
    """增强版测速模块（带IP封禁防护）"""
    
    def __init__(self, timeout: float, concurrency: int, max_attempts: int,
                 min_download_speed: float, enable_logging: bool = True,
                 config: ConfigParser = None):
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.concurrency = concurrency
        self.max_attempts = max_attempts
        self.min_download_speed = min_download_speed
        self.enable_logging = enable_logging
        self.config = config or ConfigParser()
        self.success_count = 0
        self.total_count = 0
        
        # IP防护机制
        self.ip_cooldown = {}  # IP冷却时间记录
        self.min_interval = 0.5  # 同一IP最小请求间隔(秒)
        
        # 协议识别
        self.rtp_udp_pattern = re.compile(r'/(rtp|udp)/')
        self.udp_timeout = max(0.5, timeout * 0.3)
        
        # 代理配置
        self.enable_proxy = self.config.getboolean('PROXY', 'enable_proxy', fallback=False)
        self.proxy_list = self._load_proxy_list()
        
        # 动态调整并发数
        self.adaptive_concurrency = concurrency
        self.semaphore = None  # 将在test_channels中初始化

    def _load_proxy_list(self):
        """加载代理列表"""
        if self.enable_proxy:
            proxies = self.config.get('PROXY', 'proxy_list', fallback='')
            return [p.strip() for p in proxies.split(',') if p.strip()]
        return []

    def extract_ip_from_url(self, url: str) -> str:
        """从URL中提取IP地址或主机名"""
        try:
            parsed = urllib.parse.urlparse(url)
            # 处理IPv6地址的特殊情况
            if '[' in parsed.netloc and ']' in parsed.netloc:
                return parsed.netloc.split(']')[0] + ']'
            # 提取主机名（可能是IP或域名）
            host = parsed.netloc.split(':')[0]
            return host
        except:
            return "unknown"

    async def test_channels(self, channels: List[Channel], progress_cb: Callable,
                          failed_urls: Set[str], white_list: set):
        """批量测速主方法"""
        self.total_count = len(channels)
        self.success_count = 0
        
        # 随机化测试顺序
        random.shuffle(channels)
        
        # 根据IP多样性动态调整并发数
        unique_ips = len({self.extract_ip_from_url(c.url) for c in channels})
        self.adaptive_concurrency = min(
            self.concurrency, 
            max(1, unique_ips // 2)  # 每2个IP分配1个并发槽
        )
        self.semaphore = asyncio.Semaphore(self.adaptive_concurrency)
        
        # 分组频道
        ip_groups = self.group_channels_by_ip(channels)
        
        # 创建测试任务
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            tasks = []
            for ip, group in ip_groups.items():
                # 对同一IP的频道批量测试
                task = self._batch_test_same_ip(session, group, progress_cb, failed_urls, white_list)
                tasks.append(task)
            
            await asyncio.gather(*tasks)

    def group_channels_by_ip(self, channels: List[Channel]) -> dict:
        """按IP分组频道"""
        groups = defaultdict(list)
        for channel in channels:
            ip = self.extract_ip_from_url(channel.url)
            groups[ip].append(channel)
        return groups

    async def _batch_test_same_ip(self, session: aiohttp.ClientSession, 
                                channels: List[Channel], progress_cb: Callable,
                                failed_urls: Set[str], white_list: set):
        """批量测试同一IP的多个频道"""
        ip = self.extract_ip_from_url(channels[0].url)
        
        # 检查IP冷却状态
        current_time = time.time()
        if ip in self.ip_cooldown:
            last_access = self.ip_cooldown[ip]
            elapsed = current_time - last_access
            if elapsed < self.min_interval:
                wait_time = self.min_interval - elapsed
                await asyncio.sleep(wait_time)
        
        # 执行批量测试
        try:
            for channel in channels:
                await self._test_channel(session, channel, progress_cb, failed_urls, white_list)
        finally:
            # 更新IP访问时间
            self.ip_cooldown[ip] = time.time()

    async def _test_channel(self, session: aiohttp.ClientSession, channel: Channel,
                          progress_cb: Callable, failed_urls: Set[str], white_list: set):
        """测试单个频道"""
        # 获取IP类型
        ip_type = Channel.classify_ip_type(channel.url)
        ipv6_match = Channel.IPV6_PATTERN.search(channel.url)
        
        # 白名单检查
        if self._is_in_white_list(channel, white_list):
            channel.status = 'online'
            if self.enable_logging:
                logger.debug(f"白名单免测: {channel.name} ({channel.url})")
            progress_cb()
            return

        async with self.semaphore:
            try:
                # 检查是否为RTP/UDP协议
                is_rtp_udp = bool(self.rtp_udp_pattern.search(channel.url))
                
                # 执行测速
                success, speed, latency = await self._perform_test(session, channel, is_rtp_udp)
                
                if success:
                    self.success_count += 1
                    channel.status = 'online'  # 设置频道状态
                else:
                    failed_urls.add(channel.url)
                    channel.status = 'offline'  # 设置频道状态
                
                # 调试日志
                if self.enable_logging:
                    log_msg = (
                        f"频道: {channel.name} | "
                        f"IP类型: {ip_type} | "
                        f"协议: {'RTP/UDP' if is_rtp_udp else 'HTTP'} | "
                        f"延迟: {latency:.2f}ms | "
                        f"速度: {speed:.2f}KB/s | "
                        f"状态: {channel.status}"
                    )
                    logger.debug(log_msg)
                
            except Exception as e:
                failed_urls.add(channel.url)
                channel.status = 'offline'  # 设置频道状态
                if self.enable_logging:
                    logger.error(f"测试出错: {channel.name} - {str(e)}")
            finally:
                progress_cb()

    async def _perform_test(self, session: aiohttp.ClientSession, 
                          channel: Channel, is_rtp_udp: bool) -> Tuple[bool, float, float]:
        """执行测速并返回结果"""
        proxy_session = 无
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            start_time = time.time()
            
            # 应用代理（如果启用）
            if self.enable_proxy and self.proxy_list:
                proxy = random.choice(self.proxy_list)
                connector = aiohttp.ProxyConnector(proxy=proxy)
                proxy_session = aiohttp.ClientSession(connector=connector, timeout=self.timeout)
                use_session = proxy_session
            else:
                use_session = session
            
            # RTP/UDP协议特殊处理
            if is_rtp_udp:
                async with use_session.head(
                    channel.url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.udp_timeout)
                ) as resp:
                    latency = (time.time() - start_time) * 1000
                    if 200 <= resp.status < 400:
                        return True, 0.0, latency
                    return False, 0.0, latency
                
            # 标准HTTP协议处理
            else:
                async with use_session.get(channel.url, headers=headers) as resp:
                    latency = (time.time() - start_time) * 1000
                    if resp.status != 200:
                        return False, 0.0, latency
                    
                    content = await resp.read()
                    download_time = time.time() - start_time
                    speed = len(content) / download_time / 1024
                    
                    if speed >= self.min_download_speed:
                        return True, speed, latency
                    return False, speed, latency
                
        except asyncio.TimeoutError:
            return False, 0.0, self.timeout.total * 1000
        except Exception:
            return False, 0.0, 0.0
        finally:
            # 关闭代理会话（如果是独立创建的）
            if proxy_session:
                await proxy_session.close()

    def _is_in_white_list(self, channel: Channel, white_list: set) -> bool:
        """检查白名单"""
        channel_url = channel.url.lower()
        channel_name = channel.name.lower()
        return any(
            (w.lower() in channel_url) or 
            (w.lower() == channel_name)
            for w in white_list
        )
