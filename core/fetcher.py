import aiohttp
import asyncio
import logging
from typing import Dict, List, Optional, Callable
import socket
import sys

logger = logging.getLogger(__name__)

class FetchResult:
    """表示抓取结果的类，替代dataclass"""
    
    def __init__(self, url: str, content: Optional[str] = None, 
                 status: str = "pending", exception: Optional[Exception] = None, 
                 attempt: int = 0):
        self.url = url
        self.content = content
        self.status = status
        self.exception = exception
        self.attempt = attempt

class SourceFetcher:
    """增强版网络请求处理器，支持自动重试和连接管理"""
    
    def __init__(
        self,
        timeout: float = 15,
        concurrency: int = 5,
        retries: int = 3,
        connector_args: Optional[Dict] = None
    ):
        """
        初始化请求器
        
        Args:
            timeout: 请求超时时间(秒)
            concurrency: 最大并发数
            retries: 失败重试次数
            connector_args: 自定义连接器参数
        """
        self.timeout = timeout
        self.retries = retries
        self.semaphore = asyncio.Semaphore(concurrency)
        
        # Windows 特殊处理
        base_params = {
            'force_close': True,
            'enable_cleanup_closed': True,
            'limit_per_host': concurrency
        }
        if sys.platform == 'win32':
            base_params.update({
                'keepalive_timeout': 0,
                'ssl': False
            })
        
        self.connector_params = base_params
        if connector_args:
            self.connector_params.update(connector_args)
            
        self._session = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def start(self):
        """初始化会话"""
        if not self._session:
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(**self.connector_params),
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={'User-Agent': 'Mozilla/5.0'}
            )

    async def close(self):
        """安全关闭会话"""
        if self._session:
            try:
                await self._session.close()
            except (OSError, aiohttp.ClientError) as e:
                if sys.platform == 'win32':
                    logger.debug(f"安全关闭忽略错误: {str(e)}")
                else:
                    logger.error(f"关闭会话失败: {str(e)}")
                    raise
            finally:
                self._session = None

    async def fetch_all(self, urls: List[str], progress_cb: Callable = None) -> List[FetchResult]:
        """批量获取URL内容"""
        tasks = [self._fetch_with_retry(url, progress_cb) for url in urls]
        return await asyncio.gather(*tasks)

    async def _fetch_with_retry(self, url: str, progress_cb: Callable = None) -> FetchResult:
        """带自动重试的获取逻辑"""
        result = FetchResult(url=url)
        
        for attempt in range(self.retries):
            result.attempt = attempt + 1
            try:
                async with self.semaphore:
                    try:
                        async with self._session.get(url) as resp:
                            if resp.status == 200:
                                result.content = await resp.text()
                                result.status = "success"
                                break
                            result.status = f"http_{resp.status}"
                    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                        result.exception = e
                        result.status = "network_error"
                        await asyncio.sleep(1 * attempt)  # 指数退避
            except Exception as e:
                result.exception = e
                result.status = "fatal_error"
                break
            
            if progress_cb:
                progress_cb()
                
        return result
