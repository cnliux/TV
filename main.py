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
    ResultExporter
)

class StageProgress:
    """阶段进度显示器"""
    
    def __init__(self, stage_name: str, total: int, update_interval: int = 10):
        self.stage = stage_name
        self.total = max(total, 1)  # 确保不为零
        self.current = 0
        self.bar_length = 30
        self.update_interval = update_interval

    def update(self, n=1):
        self.current = min(self.current + n, self.total)
        percent = min(100.0, self.current / self.total * 100)
        filled = min(self.bar_length, int(self.bar_length * self.current / self.total))
        bar = '▊' * filled + ' ' * (self.bar_length - filled)
        if self.update_interval > 0 and self.current % self.update_interval == 0:
            print(f"\r{self.stage} [{bar}] {percent:.1f}%", end='', flush=True)
        if self.current == self.total:
            print()  # 完成后换行

    def complete(self):
        bar = '▊' * self.bar_length
        print(f"\r{self.stage} [{bar}] 100.0%")

def is_blacklisted(channel, blacklist):
    """检查频道是否在黑名单中"""
    for entry in blacklist:
        if entry in channel.url or channel.url == entry or channel.name == entry:
            return True
    return False

async def main():
    """主工作流程"""
    try:
        # 初始化配置
        config = configparser.ConfigParser()
        config_path = Path('config/config.ini')
        if not config_path.exists():
            raise FileNotFoundError(f"❌ 配置文件不存在: {config_path}")
        config.read(config_path, encoding='utf-8')
        
        # 配置日志
        debug_mode = config.getboolean('DEBUG', 'enable_debug_logging', fallback=False)
        if debug_mode:
            logging.basicConfig(level=logging.DEBUG)
            logging.getLogger("asyncio").setLevel(logging.INFO)
        else:
            logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger(__name__)

        # 获取 output_dir
        output_dir = Path(config.get('MAIN', 'output_dir', fallback='outputs'))
        output_dir.mkdir(parents=True, exist_ok=True)

        # 读取 FETCHER 配置
        fetcher_timeout = float(config.get('FETCHER', 'timeout', fallback=15))
        fetcher_concurrency = int(config.get('FETCHER', 'concurrency', fallback=5))

        # 读取 TESTER 配置
        tester_timeout = float(config.get('TESTER', 'timeout', fallback=5))
        tester_concurrency = int(config.get('TESTER', 'concurrency', fallback=4))
        tester_max_attempts = int(config.get('TESTER', 'max_attempts', fallback=3))
        tester_min_download_speed = float(config.get('TESTER', 'min_download_speed', fallback=0.01))
        tester_enable_logging = config.getboolean('TESTER', 'enable_logging', fallback=False)

        # 读取 EXPORTER 配置
        enable_history = config.getboolean('EXPORTER', 'enable_history', fallback=False)

        # 读取 BLACKLIST 配置
        blacklist_path = Path(config.get('BLACKLIST', 'blacklist_path', fallback='config/blacklist.txt'))
        if blacklist_path.exists():
            with open(blacklist_path, 'r', encoding='utf-8') as f:
                blacklist = set(line.strip() for line in f if line.strip() and not line.startswith('#'))
        else:
            blacklist = set()

        # 读取 WHITELIST 配置
        whitelist_path = Path(config.get('WHITELIST', 'whitelist_path', fallback='config/whitelist.txt'))
        if whitelist_path.exists():
            with open(whitelist_path, 'r', encoding='utf-8') as f:
                whitelist = set(line.strip() for line in f if line.strip() and not line.startswith('#'))
        else:
            whitelist = set()

        # 读取 PATHS 配置
        urls_path = Path(config.get('PATHS', 'urls_path', fallback='config/urls.txt'))
        templates_path = Path(config.get('PATHS', 'templates_path', fallback='config/templates.txt'))

        # 检查文件是否存在
        if not urls_path.exists():
            raise FileNotFoundError(f"❌ 缺少订阅源文件: {urls_path}")
        if not templates_path.exists():
            raise FileNotFoundError(f"❌ 缺少分类模板文件: {templates_path}")

        # 读取 PROGRESS 配置
        progress_config = config['PROGRESS']
        update_interval_fetch = int(progress_config.get('update_interval_fetch', 10))
        update_interval_parse = int(progress_config.get('update_interval_parse', 40))
        update_interval_classify = int(progress_config.get('update_interval_classify', 50))
        update_interval_speedtest = int(progress_config.get('update_interval_speedtest', 100))
        update_interval_export = int(progress_config.get('update_interval_export', 1))

        # 阶段1: 获取订阅源
        with open(urls_path, 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip()]
        
        fetcher = SourceFetcher(
            timeout=fetcher_timeout,
            concurrency=fetcher_concurrency
        )
        progress = StageProgress("🌐 获取源数据", len(urls), update_interval=update_interval_fetch)
        contents = await fetcher.fetch_all(urls, progress.update)
        progress.complete()

        # 阶段2: 解析频道
        parser = PlaylistParser(config)
        valid_contents = [c for c in contents if c.strip()]
        progress = StageProgress("🔍 解析频道", len(valid_contents), update_interval=update_interval_parse)
        channels = []
        for content in valid_contents:
            channels.extend(parser.parse(content))
            progress.update()
        progress.complete()

        # 阶段3: 智能分类
        matcher = AutoCategoryMatcher(str(templates_path))
        progress = StageProgress("🏷️ 分类频道", len(channels), update_interval=update_interval_classify)
        for chan in channels:
            chan.name = matcher.normalize_channel_name(chan.name)
            chan.category = matcher.match(chan.name)
            progress.update()
        progress.complete()

        # 过滤频道：仅保留模板中定义的频道
        filtered_channels = [chan for chan in channels if matcher.is_in_template(chan.name)]
        logger.info(f"过滤后频道数量: {len(filtered_channels)}/{len(channels)}")

        # 过滤黑名单
        filtered_channels = [chan for chan in filtered_channels if not is_blacklisted(chan, blacklist)]
        logger.info(f"过滤黑名单后频道数量: {len(filtered_channels)}")

        # 按模板排序并优先白名单频道
        sorted_channels = matcher.sort_channels_by_template(filtered_channels, whitelist)

        # 阶段4: 测速测试
        unique_channels = []
        seen_urls = set()
        for chan in sorted_channels:
            if chan.url not in seen_urls:
                unique_channels.append(chan)
                seen_urls.add(chan.url)
        logger.info(f"去重后频道数量: {len(unique_channels)}/{len(sorted_channels)}")

        tester = SpeedTester(
            timeout=tester_timeout,
            concurrency=tester_concurrency,
            max_attempts=tester_max_attempts,
            min_download_speed=tester_min_download_speed,
            enable_logging=tester_enable_logging
        )
        progress = StageProgress("⏱️ 测速测试", len(unique_channels), update_interval=update_interval_speedtest)
        failed_urls = set()
        await tester.test_channels(unique_channels, progress.update, failed_urls, whitelist)
        progress.complete()
        logger.info("测速测试完成")

        # 写入失败的 URL
        if failed_urls:
            failed_urls_path = Path(config.get('PATHS', 'failed_urls_path', fallback='config/failed_urls.txt'))
            with open(failed_urls_path, 'w', encoding='utf-8') as f:
                for url in failed_urls:
                    f.write(f"{url}\n")
            logger.info(f"📝 测速失败的 URL 已写入: {failed_urls_path}")

        # 阶段5: 结果导出
        exporter = ResultExporter(
            output_dir=str(output_dir),
            enable_history=enable_history,
            template_path=str(templates_path),
            config=config,
            matcher=matcher
        )
        progress = StageProgress("💾 导出结果", 1, update_interval=update_interval_export)
        exporter.export(unique_channels, progress.update)
        progress.complete()

        # 输出摘要
        online = sum(1 for c in unique_channels if c.status == 'online')
        logger.info(f"✅ 任务完成！在线频道: {online}/{len(unique_channels)}")
        logger.info(f"📂 输出目录: {output_dir.resolve()}")

    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"❌ 发生错误: {str(e)}")
        logger.info("💡 排查建议:")
        logger.info("1. 检查 config 目录下的文件是否存在")
        logger.info("2. 确认订阅源URL可访问")
        logger.info("3. 验证分类模板格式是否正确")

if __name__ == "__main__":
    if os.name == 'nt':
        from asyncio import WindowsSelectorEventLoopPolicy
        asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"❌ 全局异常捕获: {str(e)}")
