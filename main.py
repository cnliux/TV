#!/usr/bin/env python3
import os
import asyncio
import configparser
from pathlib import Path
from typing import List, Set, Callable, Iterable, Dict, Tuple
import re
import logging
import gc
import math
import time
from collections import defaultdict
from core import (
    SourceFetcher,
    PlaylistParser,
    AutoCategoryMatcher,
    SpeedTester,
    ResultExporter,
    Channel
)

# 配置日志
def setup_logging(config):
    log_level = getattr(logging, config.get('LOGGING', 'log_level', fallback='INFO').upper())
    log_to_file = config.getboolean('LOGGING', 'log_to_file', fallback=False)
    
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
    logger.addHandler(console_handler)
    
    # 文件处理器
    if log_to_file:
        log_file = Path(config.get('LOGGING', 'log_file_path', fallback='outputs/debug.log'))
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)

# 动态进度条实现
class SmartProgress:
    def __init__(self, total: int, description: str, 
                 min_interval: float = 0.5, max_interval: float = 2.0):
        self.total = total
        self.description = description
        self.completed = 0
        self.start_time = time.time()
        self.last_update_time = 0
        # 动态刷新控制参数
        self.min_interval = min_interval  # 最小刷新间隔(秒)
        self.max_interval = max_interval  # 最大刷新间隔
        self.next_update_in = min_interval  # 下次刷新时间间隔
    
    def _should_update(self) -> bool:
        current_time = time.time()
        elapsed = current_time - self.last_update_time
        return elapsed >= self.next_update_in
    
    def _calculate_dynamic_interval(self) -> float:
        """根据剩余任务量动态调整刷新频率"""
        remaining = max(1, self.total - self.completed)
        return min(self.max_interval, 
                  self.min_interval * math.log10(remaining + 1))
    
    def update(self, n: int = 1):
        self.completed += n
        if self._should_update() or self.completed == self.total:
            self.next_update_in = self._calculate_dynamic_interval()
            self.last_update_time = time.time()
            self._refresh_display()
    
    def _refresh_display(self):
        bar_length = 30
        if self.total > 0:
            percent = self.completed / self.total * 100
            filled_length = int(bar_length * self.completed // self.total)
            elapsed = time.time() - self.start_time
            if self.completed > 0:
                eta = (elapsed / self.completed) * (self.total - self.completed)
            else:
                eta = 0
        else:
            percent = 0
            filled_length = 0
            elapsed = 0
            eta = 0
            
        bar = '■' * filled_length + '□' * (bar_length - filled_length)
        print(f"\r{self.description} {bar} {percent:.1f}% | 用时: {elapsed/60:.1f}分钟 | 预计剩余: {eta/60:.1f}分钟", 
              end='', flush=True)
    
    def complete(self):
        if self.completed < self.total:
            self.completed = self.total
        self._refresh_display()
        print()

# 判断频道是否在黑名单中
def is_blacklisted(channel: Channel, blacklist: Set[str]) -> bool:
    """检查频道是否在黑名单中（预处理为小写）"""
    lower_blacklist = {entry.lower() for entry in blacklist}
    return (channel.name.lower() in lower_blacklist or 
            channel.url.lower() in lower_blacklist or
            any(entry in channel.url.lower() for entry in lower_blacklist))

async def main():
    """主工作流程"""
    try:
        # 初始化配置
        config = configparser.ConfigParser()
        config_path = Path('config/config.ini')
        if not config_path.exists():
            raise FileNotFoundError(f"❌❌ 配置文件不存在: {config_path}")
        config.read(config_path, encoding='utf-8')
        
        # 设置日志
        setup_logging(config)
        logger = logging.getLogger(__name__)
        
        # 获取 output_dir
        output_dir = Path(config.get('MAIN', 'output_dir', fallback='outputs'))
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 读取配置
        fetcher_timeout = float(config.get('FETCHER', 'timeout', fallback=15))
        fetcher_concurrency = int(config.get('FETCHER', 'concurrency', fallback=5))
        tester_timeout = float(config.get('TESTER', 'timeout', fallback=5))
        tester_concurrency = int(config.get('TESTER', 'concurrency', fallback=4))
        tester_max_attempts = int(config.get('TESTER', 'max_attempts', fallback=3))
        tester_min_download_speed = float(config.get('TESTER', 'min_download_speed', fallback=0.01))
        tester_enable_logging = config.getboolean('TESTER', 'enable_logging', fallback=False)
        enable_history = config.getboolean('EXPORTER', 'enable_history', fallback=False)
        
        # 读取黑名单和白名单
        blacklist_path = Path(config.get('BLACKLIST', 'blacklist_path', fallback='config/blacklist.txt'))
        blacklist = set()
        if blacklist_path.exists():
            with open(blacklist_path, 'r', encoding='utf-8') as f:
                blacklist = {line.strip() for line in f if line.strip() and not line.startswith('#')}
        
        whitelist_path = Path(config.get('WHITELIST', 'whitelist_path', fallback='config/whitelist.txt'))
        whitelist = set()
        if whitelist_path.exists():
            with open(whitelist_path, 'r', encoding='utf-8') as f:
                whitelist = {line.strip() for line in f if line.strip() and not line.startswith('#')}
        
        # 读取路径配置
        urls_path = Path(config.get('PATHS', 'urls_path', fallback='config/urls.txt'))
        templates_path = Path(config.get('PATHS', 'templates_path', fallback='config/templates.txt'))
        uncategorized_path = Path(config.get('PATHS', 'uncategorized_channels_path', fallback='config/uncategorized_channels.txt'))
        failed_urls_path = Path(config.get('PATHS', 'failed_urls_path', fallback='config/failed_urls.txt'))
        
        # 检查文件是否存在
        if not urls_path.exists():
            raise FileNotFoundError(f"❌❌ 缺少订阅源文件: {urls_path}")
        if not templates_path.exists():
            raise FileNotFoundError(f"❌❌ 缺少分类模板文件: {templates_path}")
        
        # 阶段1: 获取订阅源
        with open(urls_path, 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip()]
        
        fetcher = SourceFetcher(
            timeout=fetcher_timeout,
            concurrency=fetcher_concurrency
        )
        fetch_progress = SmartProgress(len(urls), "🌐🌐 获取源数据")
        contents = await fetcher.fetch_all(urls, fetch_progress.update)
        fetch_progress.complete()
        
        # 阶段2: 解析频道
        parser = PlaylistParser(config)
        valid_contents = [c for c in contents if c and c.strip()]
        all_channels = []
        parse_progress = SmartProgress(len(valid_contents), "🔍🔍 解析频道")
        
        for content in valid_contents:
            channels = list(parser.parse(content))
            all_channels.extend(channels)
            parse_progress.update()
            if len(all_channels) % 500 == 0:
                gc.collect()
        
        parse_progress.complete()
        logger.info(f"解析完成: 共获取 {len(all_channels)} 个频道")
        
        # 阶段3: 智能分类与过滤
        matcher = AutoCategoryMatcher(str(templates_path), config)
        classify_progress = SmartProgress(len(all_channels), "🏷🏷 分类频道")
        
        # 批量分类
        channel_names = [c.name for c in all_channels]
        category_mapping = matcher.batch_match(channel_names)
        
        # 处理分类结果
        processed_channels = []
        uncategorized_groups = defaultdict(list)
        seen_urls = set()
        
        for chan in all_channels:
            # 应用分类结果
            chan.category = category_mapping[chan.name]
            
            # 应用名称规范化
            normalized_name = matcher.normalize_channel_name(chan.name)
            chan.name = normalized_name
            
            if chan.category == "未分类":
                clean_name = re.sub(r'[\n\r\t]', ' ', chan.name).strip()
                uncategorized_groups[chan.original_category].append((clean_name, chan.url))
                if matcher.enable_debug:
                    logger.debug(f"未分类频道: {chan.name} (原分类: {chan.original_category})")
            
            # 过滤条件
            if (not matcher.is_in_template(chan.name) or 
                is_blacklisted(chan, blacklist) or 
                chan.url in seen_urls):
                classify_progress.update()
                continue
                
            seen_urls.add(chan.url)
            processed_channels.append(chan)
            classify_progress.update()
            
            if len(processed_channels) % 500 == 0:
                gc.collect()
        
        classify_progress.complete()
        logger.info(f"过滤后频道数量: {len(processed_channels)}/{len(all_channels)}")
        
        # 打印分类统计
        matcher.print_cache_stats()
        matcher.print_performance_report()
        
        # 保存未分类频道
        if uncategorized_groups:
            uncategorized_path.parent.mkdir(parents=True, exist_ok=True)
            with open(uncategorized_path, 'w', encoding='utf-8') as f:
                f.write("# 未分类频道列表 (按源分类分组)\n\n")
                for category in sorted(uncategorized_groups.keys()):
                    f.write(f"{category},#genre#\n")
                    for name, url in sorted(uncategorized_groups[category]):
                        f.write(f"{name.replace(',', '，')},{url}\n")
                    f.write("\n")
            logger.info(f"📝📝 未分类频道已保存到: {uncategorized_path}")
        else:
            logger.info("✅ 所有频道均已分类")
        
        # 阶段4: 测速测试
        sorted_channels = matcher.sort_channels_by_template(processed_channels, whitelist)
        tester = SpeedTester(
            timeout=tester_timeout,
            concurrency=tester_concurrency,
            max_attempts=tester_max_attempts,
            min_download_speed=tester_min_download_speed,
            enable_logging=tester_enable_logging
        )
        
        batch_size = 500
        total_channels = len(sorted_channels)
        test_progress = SmartProgress(total_channels, "⏱⏱⏱ 测速测试")
        failed_urls = set()
        
        for i in range(0, total_channels, batch_size):
            batch = sorted_channels[i:i+batch_size]
            await tester.test_channels(batch, test_progress.update, failed_urls, whitelist)
            del batch
            gc.collect()
            
        test_progress.complete()
        logger.info("测速测试完成")
        
        # 保存失败URL
        if failed_urls:
            failed_urls_path.parent.mkdir(parents=True, exist_ok=True)
            with open(failed_urls_path, 'w', encoding='utf-8') as f:
                f.write("# 测速失败的URL列表\n")
                for url in failed_urls:
                    f.write(f"{url}\n")
            logger.info(f"📝📝 测速失败URL已保存: {failed_urls_path}")
        
        # 阶段5: 结果导出
        exporter = ResultExporter(
            output_dir=str(output_dir),
            enable_history=enable_history,
            template_path=str(templates_path),
            config=config,
            matcher=matcher
        )
        export_progress = SmartProgress(1, "💾💾 导出结果")
        exporter.export(sorted_channels, export_progress.update)
        export_progress.complete()
        
        # 输出摘要
        online = sum(1 for c in sorted_channels if c.status == 'online')
        logger.info(f"✅ 任务完成！在线频道: {online}/{len(sorted_channels)}")
        logger.info(f"📂📂 输出目录: {output_dir.resolve()}")
    
    except Exception as e:
        logger.error(f"❌❌ 发生错误: {str(e)}", exc_info=True)
        logger.info("💡💡 排查建议:")
        logger.info("1. 检查config目录下的文件是否存在")
        logger.info("2. 确认订阅源URL可访问")
        logger.info("3. 验证分类模板格式是否正确")

if __name__ == "__main__":
    if os.name == 'nt':
        from asyncio import WindowsSelectorEventLoopPolicy
        asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except Exception as e:
        logging.error(f"❌❌ 全局异常: {str(e)}", exc_info=True)
