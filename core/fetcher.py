#!/usr/bin/env python3
import aiohttp
import asyncio
from typing import List, Callable, Optional
import logging
import os
import socket  # 新增导入
from dataclasses import dataclass

@dataclass
class FetchResult:
    """获取结果的数据类"""
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
        """
        初始化获取器
        
        :param timeout: 请求超时时间（秒）
        :param concurrency: 并发请求数
        :param retries: 重试次数
        :param whitelist: 白名单扩展名列表
        """
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.semaphore = asyncio.Semaphore(concurrency)
        self.retries = retries
        self.whitelist = whitelist or [".m3u", ".txt"]
        self.logger = logging.getLogger(__name__)
        self._session = None  # aiohttp会话实例

    async def fetch_all(self, urls: List[str], progress_cb: Callable) -> List[str]:
        """批量获取订阅源"""
        # 创建会话（如果不存在）
        if not self._session:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        
        results = []
        tasks = []
        
        # 预过滤URL（只保留白名单扩展名）
        filtered_urls = [u for u in urls if any(ext in u for ext in self.whitelist)]
        
        # 创建获取任务
        for url in filtered_urls:
            task = asyncio.create_task(
                self._fetch_with_retry(url, progress_cb))
            tasks.append(task)
        
        # 分批处理避免内存问题
        for i in range(0, len(tasks), 100):
            batch = tasks[i:i+100]
            batch_results = await asyncio.gather(*batch)
            results.extend(batch_results)
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
                        # 检查响应状态码
                        if resp.status != 200:
                            raise ValueError(f"HTTP {resp.status}")
                        
                        # 读取响应内容
                        result.content = await resp.text(
                            encoding='utf-8',
                            errors='replace'
                        )
                        result.success = True
                        return result
                        
            except Exception as e:
                self.logger.debug(f"获取失败 (尝试 {attempt + 1}/{self.retries}): {url} ({str(e)})")
                if attempt == self.retries - 1:
                    break  # 最后一次尝试失败，不再重试
                await asyncio.sleep(1)  # 重试前等待
        
        return result  # 返回失败结果

    async def close(self):
        """安全关闭会话和连接池"""
        if self._session:
            try:
                # 关闭会话
                await self._session.close()
                
                # 清理连接池和DNS缓存
                connector = self._session.connector
                if connector:
                    # 关闭所有连接
                    await connector.close()
                    
                    # 清理DNS缓存
                    if hasattr(connector, '_resolve_host'):
                        connector._resolve_host.cache_clear()
                    
                    # 强制关闭连接池中的套接字
                    if hasattr(connector, '_conns'):
                        for key in list(connector._conns.keys()):
                            for conn in connector._conns[key]:
                                try:
                                    # Windows特殊处理：安全关闭套接字
                                    if os.name == 'nt':
                                        if hasattr(conn, '_sock'):
                                            try:
                                                conn._sock.shutdown(socket.SHUT_RDWR)
                                            except (OSError, AttributeError):
                                                pass
                                    conn.close()
                                except Exception:
                                    pass
                            del connector._conns[key]
                self.logger.info("成功关闭所有网络连接")
            except Exception as e:
                self.logger.error(f"关闭会话时出错: {str(e)}", exc_info=True)
            finally:
                self._session = None
