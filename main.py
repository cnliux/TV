#!/usr/bin/env python3
import os
import asyncio
import configparser
from pathlib import Path
from typing import List, Set, Callable
import re
import logging
from core import (
    SourceFetcher,
    PlaylistParser,
    AutoCategoryMatcher,
    SpeedTester,
    ResultExporter,
    Channel
)

# 配置日志格式
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class StageProgress:
    """阶段进度显示器"""
    
    def __init__(self, stage_name: str, total: int, update_interval: int = 10):
        self.stage = stage_name
        self.total = max(total, 1)
        self.current = 0
        self.bar_length = 30
        self.update_interval = update_interval

    def update(self, n=1):
        self.current = min(self.current + n, self.total)
        if self.current % self.update_interval == 0 or self.current == self.total:
            percent = self.current / self.total * 100
            filled = int(self.bar_length * self.current / self.total)
            bar = '▊' * filled + ' ' * (self.bar_length - filled)
            print(f"\r{self.stage} [{bar}] {percent:.1f}%", end='', flush=True)

    def complete(self):
        bar = '▊' * self.bar_length
        print(f"\r{self.stage} [{bar}] 100.0%")

def is_blacklisted(channel: Channel, blacklist: Set[str]) -> bool:
    """检查频道是否在黑名单中"""
    for entry in blacklist:
        if entry in channel.url or channel.url == entry or channel.name == entry:
            return True
    return False

def load_config() -> configparser.ConfigParser:
    """加载配置文件"""
    config = configparser.ConfigParser()
    config_path = Path('config/config.ini')
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    config.read(config_path, encoding='utf-8')
    return config

def load_list_file(file_path: str) -> Set[str]:
    """加载黑名单或白名单文件"""
    path = Path(file_path)
    if not path.exists():
        return set()
    with open(path, 'r', encoding='utf-8') as f:
        return {
            line.strip() for line in f 
            if line.strip() and not line.startswith('#')
        }

async def fetch_sources(
    urls: List[str], 
    timeout: float, 
    concurrency: int, 
    progress_cb: Callable[[], None]
) -> List[str]:
    """获取所有订阅源内容"""
    fetcher = SourceFetcher(timeout=timeout, concurrency=concurrency)
    return await fetcher.fetch_all(urls, progress_cb)

def parse_channels(
    contents: List[str], 
    config: configparser.ConfigParser, 
    progress_cb: Callable[[], None]
) -> List[Channel]:
    """解析频道列表"""
    parser = PlaylistParser(config)
    channels = []
    for content in contents:
        if not content.strip():
            continue
        channels.extend(parser.parse(content))
        progress_cb()
    return channels

def categorize_channels(
    channels: List[Channel], 
    templates_path: str, 
    progress_cb: Callable[[], None]
) -> List[Channel]:
    """对频道进行分类"""
    matcher = AutoCategoryMatcher(templates_path)
    for channel in channels:
        channel.name = matcher.normalize_channel_name(channel.name)
        channel.category = matcher.match(channel.name)
        progress_cb()
    return channels

def filter_channels(
    channels: List[Channel], 
    blacklist: Set[str], 
    whitelist: Set[str], 
    matcher: AutoCategoryMatcher
) -> List[Channel]:
    """过滤频道（黑名单、白名单、模板匹配）"""
    # 过滤黑名单
    filtered = [c for c in channels if not is_blacklisted(c, blacklist)]
    logger.info(f"过滤黑名单后频道数量: {len(filtered)}/{len(channels)}")
    
    # 仅保留模板中定义的频道
    filtered = [c for c in filtered if matcher.is_in_template(c.name)]
    logger.info(f"模板匹配后频道数量: {len(filtered)}")
    
    # 按模板排序并优先白名单频道
    return matcher.sort_channels_by_template(filtered, whitelist)

async def test_channels(
    channels: List[Channel], 
    timeout: float, 
    concurrency: int, 
    max_attempts: int, 
    min_speed: float, 
    progress_cb: Callable[[], None]
) -> Set[str]:
    """测速测试"""
    tester = SpeedTester(
        timeout=timeout,
        concurrency=concurrency,
        max_attempts=max_attempts,
        min_download_speed=min_speed,
        enable_logging=True
    )
    failed_urls = set()
    await tester.test_channels(channels, progress_cb, failed_urls)
    return failed_urls

async def main():
    """主工作流程"""
    try:
        # 初始化配置
        config = load_config()
        output_dir = Path(config.get('MAIN', 'output_dir', fallback='outputs'))
        output_dir.mkdir(parents=True, exist_ok=True)

        # 读取配置参数
        fetcher_timeout = config.getfloat('FETCHER', 'timeout', fallback=15)
        fetcher_concurrency = config.getint('FETCHER', 'concurrency', fallback=5)
        tester_timeout = config.getfloat('TESTER', 'timeout', fallback=10)
        tester_concurrency = config.getint('TESTER', 'concurrency', fallback=20)
        tester_max_attempts = config.getint('TESTER', 'max_attempts', fallback=3)
        tester_min_speed = config.getfloat('TESTER', 'min_download_speed', fallback=0.5)
        enable_history = config.getboolean('EXPORTER', 'enable_history', fallback=False)

        # 加载黑名单和白名单
        blacklist = load_list_file(config.get('BLACKLIST', 'blacklist_path'))
        whitelist = load_list_file(config.get('WHITELIST', 'whitelist_path'))

        # 检查必要文件
        urls_path = Path(config.get('PATHS', 'urls_path'))
        templates_path = Path(config.get('PATHS', 'templates_path'))
        if not urls_path.exists():
            raise FileNotFoundError(f"订阅源文件不存在: {urls_path}")
        if not templates_path.exists():
            raise FileNotFoundError(f"分类模板文件不存在: {templates_path}")

        # 阶段1: 获取订阅源
        with open(urls_path, 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip()]
        
        logger.info(f"开始获取 {len(urls)} 个订阅源")
        progress = StageProgress("🌐 获取源数据", len(urls))
        contents = await fetch_sources(urls, fetcher_timeout, fetcher_concurrency, progress.update)
        progress.complete()

        # 阶段2: 解析频道
        logger.info("解析频道数据")
        progress = StageProgress("🔍 解析频道", len(contents))
        channels = parse_channels(contents, config, progress.update)
        progress.complete()
        logger.info(f"解析到 {len(channels)} 个频道")

        # 阶段3: 智能分类
        logger.info("对频道进行分类")
        progress = StageProgress("🏷️ 分类频道", len(channels))
        matcher = AutoCategoryMatcher(str(templates_path))
        channels = categorize_channels(channels, str(templates_path), progress.update)
        progress.complete()

        # 阶段4: 过滤频道
        logger.info("过滤频道（黑名单/白名单）")
        filtered_channels = filter_channels(channels, blacklist, whitelist, matcher)

        # 去重
        unique_channels = []
        seen_urls = set()
        for channel in filtered_channels:
            if channel.url not in seen_urls:
                unique_channels.append(channel)
                seen_urls.add(channel.url)
        logger.info(f"去重后频道数量: {len(unique_channels)}")

        # 阶段5: 测速测试
        logger.info("开始测速测试")
        progress = StageProgress("⏱️ 测速测试", len(unique_channels))
        failed_urls = await test_channels(
            unique_channels,
            tester_timeout,
            tester_concurrency,
            tester_max_attempts,
            tester_min_speed,
            progress.update
        )
        progress.complete()
        logger.info(f"测速完成，失败URL数量: {len(failed_urls)}")

        # 写入失败的URL
        if failed_urls:
            failed_path = Path(config.get('PATHS', 'failed_urls_path'))
            with open(failed_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(failed_urls))
            logger.info(f"失败的URL已写入: {failed_path}")

        # 阶段6: 导出结果
        logger.info("导出结果文件")
        exporter = ResultExporter(
            output_dir=str(output_dir),
            enable_history=enable_history,
            template_path=str(templates_path),
            config=config,
            matcher=matcher
        )
        progress = StageProgress("💾 导出结果", 3)  # 3个导出步骤
        exporter.export(unique_channels, progress.update)
        progress.complete()

        # 输出摘要
        online_channels = [c for c in unique_channels if c.status == 'online']
        logger.info(f"任务完成！在线频道: {len(online_channels)}/{len(unique_channels)}")
        logger.info(f"输出目录: {output_dir.resolve()}")

    except Exception as e:
        logger.error(f"发生错误: {str(e)}", exc_info=True)
        logger.info("排查建议:")
        logger.info("1. 检查配置文件 config.ini 是否存在")
        logger.info("2. 确认订阅源URL可访问")
        logger.info("3. 查看日志文件获取详细错误信息")

if __name__ == "__main__":
    if os.name == 'nt':
        from asyncio import WindowsSelectorEventLoopPolicy
        asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("用户中断操作")
    except Exception as e:
        logger.error(f"全局异常: {str(e)}", exc_info=True)
