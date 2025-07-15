#!/usr/bin/env python3
import os
import asyncio
import configparser
from pathlib import Path
from typing import List, Set, Callable, Dict, Optional
import re
import logging
import sys
import io
import time
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
import gc

# 确保 Python 能找到 core 模块
sys.path.append(str(Path(__file__).parent))

# 导入 core 模块中的类
from core.fetcher import SourceFetcher
from core.parser import PlaylistParser
from core.matcher import AutoCategoryMatcher
from core.tester import SpeedTester
from core.exporter import ResultExporter
from core.models import Channel

# 设置标准输出编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 预编译正则表达式
CLEAN_NAME_PATTERN = re.compile(r'[^\w\u4e00-\u9fff\-_ ]')
URL_BASE_PATTERN = re.compile(r'^([^?#]+)')

# 进度显示器
class StageProgress:
    def __init__(self, stage_name: str, total: int, update_interval: int = 1000):
        self.stage = stage_name
        self.total = max(total, 1)
        self.current = 0
        self.update_interval = update_interval
        self.start_time = time.time()

    def update(self, n=1):
        self.current = min(self.current + n, self.total)
        if self.current % self.update_interval == 0 or self.current == self.total:
            self._print_progress()

    def _print_progress(self):
        percent = min(100.0, self.current / self.total * 100)
        elapsed = time.time() - self.start_time
        eta = (elapsed / self.current) * (self.total - self.current) if self.current > 0 else 0
        print(f"\r{self.stage.ljust(15)} [{percent:.1f}%] | 已用: {elapsed:.1f}s | 剩余: {eta:.1f}s", end='', flush=True)

    def complete(self):
        self.current = self.total
        self._print_progress()
        print()

# 黑名单处理
def load_blacklist(config: configparser.ConfigParser) -> Set[str]:
    """加载黑名单文件"""
    blacklist_path = Path(config.get('BLACKLIST', 'blacklist_path', fallback='config/blacklist.txt'))
    blacklist = set()
    if blacklist_path.exists():
        with open(blacklist_path, 'r', encoding='utf-8') as f:
            blacklist = {line.strip() for line in f if line.strip() and not line.startswith('#')}
    return blacklist

# 数据获取
async def fetch_source_channels(config: configparser.ConfigParser) -> List[Channel]:
    """获取原始频道数据"""
    urls_path = Path(config.get('PATHS', 'urls_path', fallback='config/urls.txt'))
    if not urls_path.exists():
        raise FileNotFoundError(f"订阅源文件不存在: {urls_path}")
    
    with open(urls_path, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip()]
    
    fetcher = SourceFetcher(
        timeout=float(config.get('FETCHER', 'timeout', fallback=15)),
        concurrency=int(config.get('FETCHER', 'concurrency', fallback=5)),
        retries=int(config.get('FETCHER', 'retries', fallback=3))
    )
    
    progress = StageProgress("🌐 获取源数据", len(urls))
    contents = await fetcher.fetch_all(urls, progress.update)
    progress.complete()
    
    parser = PlaylistParser(config)
    channels = []
    for content in contents:
        if content:
            channels.extend(list(parser.parse(content)))
    return channels

# 并行预处理
async def batch_preprocess(
    channels: List[Channel],
    blacklist: Set[str],
    progress: StageProgress,
    batch_size: int = 5000
) -> List[Channel]:
    """并行预处理频道数据"""
    valid_channels = []
    seen_urls = set()
    
    # 预编译黑名单规则
    @lru_cache(maxsize=1024)
    def compile_pattern(p: str):
        return re.compile(p, re.IGNORECASE)
    blacklist_patterns = [compile_pattern(p) for p in blacklist]
    
    for i in range(0, len(channels), batch_size):
        batch = channels[i:i + batch_size]
        
        # 并行处理
        with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
            processed_batch = []
            futures = []
            
            for chan in batch:
                future = executor.submit(
                    process_single_channel,
                    chan,
                    blacklist_patterns,
                    seen_urls
                )
                futures.append(future)
            
            for future in as_completed(futures):
                result = future.result()
                if result:
                    processed_batch.append(result)
                    progress.update()
        
        valid_channels.extend(processed_batch)
        gc.collect()
    
    return valid_channels

def process_single_channel(
    chan: Channel,
    blacklist_patterns: List[re.Pattern],
    seen_urls: Set[str]
) -> Optional[Channel]:
    """处理单个频道（线程安全）"""
    # 名称清理
    chan.name = CLEAN_NAME_PATTERN.sub('', chan.name.strip()) or f"未命名_{hash(chan.url)}"
    
    # URL去重
    base_url = URL_BASE_PATTERN.match(chan.url).group(1)
    if base_url in seen_urls:
        return None
    seen_urls.add(base_url)
    
    # 黑名单检查
    normalized_name = chan.name.lower()
    normalized_url = chan.url.lower()
    for pattern in blacklist_patterns:
        if pattern.search(normalized_url) or pattern.fullmatch(normalized_name):
            return None
    
    return chan

async def main():
    try:
        # Windows编码设置
        if os.name == 'nt':
            os.system('chcp 65001 > nul')

        # 初始化配置
        config = configparser.ConfigParser()
        config_path = Path('config/config.ini')
        if not config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        config.read(config_path, encoding='utf-8')
        
        # 日志配置
        logging.basicConfig(
            level=logging.DEBUG if config.getboolean('DEBUG', 'enable_debug_logging', fallback=False) else logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler()]
        )
        logger = logging.getLogger(__name__)

        # 1. 加载黑名单
        blacklist = load_blacklist(config)
        logger.info(f"已加载黑名单: {len(blacklist)} 条规则")

        # 2. 获取原始数据
        channels = await fetch_source_channels(config)
        logger.info(f"获取到原始频道: {len(channels)} 个")

        # 3. 预处理
        pre_progress = StageProgress("🛠️ 预处理频道", len(channels))
        valid_channels = await batch_preprocess(channels, blacklist, pre_progress)
        pre_progress.complete()
        logger.info(f"预处理后有效频道: {len(valid_channels)}/{len(channels)}")

        # 4. 分类
        templates_path = Path(config.get('PATHS', 'templates_path', fallback='config/templates.txt'))
        matcher = AutoCategoryMatcher(str(templates_path))
        classify_progress = StageProgress("🏷️ 分类频道", len(valid_channels))
        for chan in valid_channels:
            chan.category = matcher.match(chan)
            classify_progress.update()
        classify_progress.complete()

        # 5. 测速
        tester = SpeedTester(
            timeout=float(config.get('TESTER', 'timeout', fallback=5)),
            concurrency=int(config.get('TESTER', 'concurrency', fallback=4)),
            max_attempts=int(config.get('TESTER', 'max_attempts', fallback=3)),
            min_download_speed=float(config.get('TESTER', 'min_download_speed', fallback=0.2)),
            enable_logging=config.getboolean('TESTER', 'enable_logging', fallback=False)
        )
        failed_urls = set()
        speed_progress = StageProgress("⏱️ 测速测试", len(valid_channels))
        await tester.test_channels(valid_channels, speed_progress.update, failed_urls, set())
        speed_progress.complete()

        # 6. 导出
        exporter = ResultExporter(
            output_dir=config.get('MAIN', 'output_dir', fallback='outputs'),
            enable_history=config.getboolean('EXPORTER', 'enable_history', fallback=False),
            template_path=str(templates_path),
            config=config,
            matcher=matcher
        )
        export_progress = StageProgress("💾 导出结果", 1)
        exporter.export(valid_channels, export_progress.update)
        export_progress.complete()

        # 最终统计
        online = sum(1 for c in valid_channels if c.status == 'online')
        logger.info(f"\n{'='*50}")
        logger.info(f"✅ 任务完成! 总计: {len(valid_channels)} 个频道")
        logger.info(f"🟢 在线: {online} | 🔴 离线: {len(valid_channels)-online}")
        logger.info(f"📂 输出目录: {config.get('MAIN', 'output_dir', fallback='outputs')}")
        logger.info("="*50)

    except Exception as e:
        logging.error(f"❌ 主流程异常: {str(e)}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(main())
