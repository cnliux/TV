#!/usr/bin/env python3
import os
import asyncio
import configparser
from pathlib import Path
from typing import List, Set, Dict, Optional
import re
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
import gc
from functools import lru_cache
from datetime import datetime

# 设置模块路径
sys.path.append(str(Path(__file__).parent))

# 导入核心模块
from core.fetcher import SourceFetcher, FetchResult
from core.parser import PlaylistParser
from core.matcher import AutoCategoryMatcher
from core.tester import SpeedTester
from core.exporter import ResultExporter
from core.models import Channel

# 配置日志
def setup_logging(config: configparser.ConfigParser):
    """设置日志配置"""
    log_to_file = config.getboolean('DEBUG', 'log_to_file', fallback=False)
    enable_debug_logging = config.getboolean('DEBUG', 'enable_debug_logging', fallback=True)
    
    # 设置根日志级别
    logging.basicConfig(
        level=logging.DEBUG if enable_debug_logging else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )
    
    # 单独设置模块日志级别
    for module in ['__main__', 'core.fetcher', 'core.parser', 'core.matcher', 'core.tester', 'core.exporter']:
        logger = logging.getLogger(module)
        logger.setLevel(logging.DEBUG if enable_debug_logging else logging.INFO)
    
    if log_to_file:
        file_handler = logging.FileHandler('debug.log')
        file_handler.setLevel(logging.DEBUG if enable_debug_logging else logging.INFO)
        logging.getLogger().addHandler(file_handler)

logger = logging.getLogger(__name__)

# 预编译正则
CLEAN_NAME_PATTERN = re.compile(r'[^\w\u4e00-\u9fff\-_ ]')
URL_BASE_PATTERN = re.compile(r'^([^?#]+)')

class SmartProgress:
    """智能进度显示器"""
    def __init__(self, total: int, desc: str = "进度"):
        self.total = total
        self.done = 0
        self.desc = desc
        self.start = time.time()
        
    def update(self, n=1):
        self.done += n
        if self.done % 100 == 0 or self.done == self.total:
            self._print()
            
    def _print(self):
        elapsed = time.time() - self.start
        percent = self.done / self.total * 100
        eta = (elapsed / self.done) * (self.total - self.done) if self.done > 0 else 0
        print(
            f"\r{self.desc}: {percent:.1f}% | "
            f"已处理: {self.done}/{self.total} | "
            f"耗时: {elapsed:.1f}s | "
            f"剩余: {eta:.1f}s",
            end='', 
            flush=True
        )
        
    def close(self):
        if self.done < self.total:
            self.done = self.total
            self._print()
        print()  # 换行

def load_config() -> configparser.ConfigParser:
    """加载配置文件"""
    config = configparser.ConfigParser()
    config_path = Path('config/config.ini')
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    config.read(config_path, encoding='utf-8')
    return config

def load_blacklist(config: configparser.ConfigParser) -> Set[str]:
    """加载黑名单"""
    blacklist_path = Path(config.get('BLACKLIST', 'blacklist_path', fallback='config/blacklist.txt'))
    if blacklist_path.exists():
        with open(blacklist_path, 'r', encoding='utf-8') as f:
            return {line.strip() for line in f if line.strip() and not line.startswith('#')}
    return set()

def load_whitelist(config: configparser.ConfigParser) -> Set[str]:
    """加载白名单"""
    whitelist_path = Path(config.get('WHITELIST', 'whitelist_path', fallback='config/whitelist.txt'))
    if whitelist_path.exists():
        with open(whitelist_path, 'r', encoding='utf-8') as f:
            return {line.strip() for line in f if line.strip() and not line.startswith('#')}
    return set()

def process_channel(
    chan: Channel,
    blacklist_patterns: List[re.Pattern],
    seen_urls: Set[str],
    seen_names: Set[str],
    whitelist: Set[str]
) -> Optional[Channel]:
    """处理单个频道"""
    # 名称清理
    chan.name = CLEAN_NAME_PATTERN.sub('', chan.name.strip()) or f"未命名_{hash(chan.url)}"
    
    # URL去重
    base_url = URL_BASE_PATTERN.match(chan.url).group(1)
    if base_url in seen_urls:
        return None
    seen_urls.add(base_url)
    
    # 名称去重
    if chan.name in seen_names:
        return None
    seen_names.add(chan.name)
    
    # 黑名单检查
    norm_name = chan.name.lower()
    norm_url = chan.url.lower()
    if any(p.search(norm_url) or p.fullmatch(norm_name) for p in blacklist_patterns):
        return None
    
    # 白名单优先
    if norm_url in whitelist or norm_name in whitelist:
        return chan
    
    return chan

async def preprocess_channels(
    channels: List[Channel],
    blacklist: Set[str],
    whitelist: Set[str],
    batch_size: int = 5000
) -> List[Channel]:
    """并行预处理频道"""
    # 预编译黑名单规则
    @lru_cache(maxsize=1024)
    def compile_pattern(p: str):
        return re.compile(p, re.IGNORECASE)
    blacklist_patterns = [compile_pattern(p) for p in blacklist]
    
    valid_channels = []
    seen_urls = set()
    seen_names = set()
    progress = SmartProgress(len(channels), "🛠️ 预处理")
    
    for i in range(0, len(channels), batch_size):
        batch = channels[i:i + batch_size]
        
        with ThreadPoolExecutor() as executor:
            # 并行处理批次
            processed = list(executor.map(
                lambda c: process_channel(c, blacklist_patterns, seen_urls, seen_names, whitelist),
                batch
            ))
            
            # 收集有效结果
            valid_channels.extend([c for c in processed if c])
            progress.update(len(batch))
            gc.collect()
    
    progress.close()
    return valid_channels

async def fetch_channels(config: configparser.ConfigParser) -> List[Channel]:
    """获取并解析频道数据"""
    # 加载URL列表
    urls_path = Path(config.get('PATHS', 'urls_path', fallback='config/urls.txt'))
    with open(urls_path, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip()]
    
    # 初始化fetcher
    fetcher = SourceFetcher(
        timeout=float(config.get('FETCHER', 'timeout', fallback=15)),
        concurrency=int(config.get('FETCHER', 'concurrency', fallback=10)),
        retries=int(config.get('FETCHER', 'retries', fallback=2))
    )
    
    # 获取数据
    progress = SmartProgress(len(urls), "🌐 获取源数据")
    contents = await fetcher.fetch_all(urls, progress.update)
    progress.close()
    
    # 解析内容
    parser = PlaylistParser(config)
    channels = []
    parse_progress = SmartProgress(len(contents), "🔍 解析频道")
    
    for content in contents:
        if content:
            channels.extend(list(parser.parse(content)))
        parse_progress.update()
    parse_progress.close()
    
    await fetcher.close()
    return channels

async def main():
    try:
        # Windows编码设置
        if os.name == 'nt':
            os.system('chcp 65001 > nul')
        
        # 初始化
        config = load_config()
        setup_logging(config)
        logger.info("配置加载完成")
        
        # 加载黑名单
        blacklist = load_blacklist(config)
        logger.info(f"已加载黑名单: {len(blacklist)} 条规则")
        
        # 加载白名单
        whitelist = load_whitelist(config)
        logger.info(f"已加载白名单: {len(whitelist)} 条规则")
        
        # 获取频道数据
        channels = await fetch_channels(config)
        logger.info(f"获取到原始频道: {len(channels)} 个")
        
        # 预处理
        valid_channels = await preprocess_channels(channels, blacklist, whitelist)
        logger.info(f"预处理后有效频道: {len(valid_channels)}/{len(channels)}")
        
        # 分类
        matcher = AutoCategoryMatcher(
            config.get('PATHS', 'templates_path', fallback='config/templates.txt')
        )
        classify_progress = SmartProgress(len(valid_channels), "🏷️ 分类")
        for chan in valid_channels:
            chan.category = matcher.match(chan)
            classify_progress.update()
        classify_progress.close()
        
        # 测速（只测速已分类频道）
        categorized_channels = [c for c in valid_channels if c.category != "未分类"]
        tester = SpeedTester(
            timeout=float(config.get('TESTER', 'timeout', fallback=5)),
            concurrency=int(config.get('TESTER', 'concurrency', fallback=10)),
            max_attempts=int(config.get('TESTER', 'max_attempts', fallback=3)),
            min_download_speed=float(config.get('TESTER', 'min_download_speed', fallback=0.2)),
            enable_logging=config.getboolean('TESTER', 'enable_logging', fallback=False),
            failed_urls_path=config.get('TESTER', 'failed_urls_path', fallback='config/failed_urls.txt')
        )
        failed_urls = set()
        speed_progress = SmartProgress(len(categorized_channels), "⏱️ 测速")
        await tester.test_channels(categorized_channels, speed_progress.update, failed_urls, whitelist)
        speed_progress.close()
        
        # 导出
        exporter = ResultExporter(
            output_dir=config.get('MAIN', 'output_dir', fallback='outputs'),
            enable_history=config.getboolean('EXPORTER', 'enable_history', fallback=False),
            template_path=config.get('PATHS', 'templates_path', fallback='config/templates.txt'),
            config=config,
            matcher=matcher
        )
        exporter.export(valid_channels, lambda: None)
        
        # 统计
        online = sum(1 for c in valid_channels if c.status == 'online')
        uncategorized = sum(1 for c in valid_channels if c.category == "未分类")
        logger.info(f"\n{'='*50}")
        logger.info(f"✅ 任务完成! 总计: {len(valid_channels)} 个频道")
        logger.info(f"🟢 在线: {online} | 🔴 离线: {len(valid_channels)-online}")
        logger.info(f"📦 未分类: {uncategorized}")
        logger.info(f"💾 失败URL保存到: {tester.failed_urls_path}")
        logger.info(f"📝 未分类频道保存到: {exporter.uncategorized_path}")
        logger.info("⚠️ 免责声明: 以上频道信息仅供参考，使用时请自行验证其合法性和可用性")
        logger.info("="*50)

    except Exception as e:
        logger.error(f"❌ 主流程异常: {str(e)}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(main())
