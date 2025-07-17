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
        remaining = max(1, self.total - self.completed)  # 防止除零
        # 动态计算：剩余任务越多，刷新间隔越长（指数衰减）
        return min(self.max_interval, 
                  self.min_interval * math.log10(remaining + 1))
    
    def update(self, n: int = 1):
        self.completed += n
        if self._should_update() or self.completed == self.total:
            # 动态调整下次刷新间隔
            self.next_update_in = self._calculate_dynamic_interval()
            self.last_update_time = time.time()
            self._refresh_display()
    
    def _refresh_display(self):
        # 进度条显示优化（使用block更高效）
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
        print()  # 换行结束

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
            raise FileNotFoundError(f"❌❌❌❌ 配置文件不存在: {config_path}")
        config.read(config_path, encoding='utf-8')
        
        # 设置日志
        setup_logging(config)
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
        uncategorized_path = Path(config.get('PATHS', 'uncategorized_channels_path', fallback='config/uncategorized_channels.txt'))
        
        # 检查文件是否存在
        if not urls_path.exists():
            raise FileNotFoundError(f"❌❌❌❌ 缺少订阅源文件: {urls_path}")
        if not templates_path.exists():
            raise FileNotFoundError(f"❌❌❌❌ 缺少分类模板文件: {templates_path}")
        
        # 阶段1: 获取订阅源
        with open(urls_path, 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip()]
        
        fetcher = SourceFetcher(
            timeout=fetcher_timeout,
            concurrency=fetcher_concurrency
        )
        fetch_progress = SmartProgress(len(urls), "🌐🌐🌐🌐 获取源数据")
        contents = await fetcher.fetch_all(urls, fetch_progress.update)
        fetch_progress.complete()
        
        # 阶段2: 流式解析频道
        parser = PlaylistParser(config)
        valid_contents = [c for c in contents if c and c.strip()]
        
        # 优化1: 分批处理减少内存峰值
        batch_size = 200  # 每批处理200个频道
        all_channels = []
        
        parse_progress = SmartProgress(len(valid_contents), "🔍🔍🔍🔍 解析频道")
        for content in valid_contents:
            channels = parser.parse(content)
            all_channels.extend(channels)
            parse_progress.update()
            
            # 分批处理: 每处理500个频道进行一次内存释放
            if len(all_channels) > batch_size:
                gc.collect()
        parse_progress.complete()
        del contents, valid_contents  # 立即释放内存
        gc.collect()
        
        # 阶段3: 智能分类与过滤
        matcher = AutoCategoryMatcher(str(templates_path), config)
        classify_progress = SmartProgress(len(all_channels), "🏷🏷🏷🏷️ 分类频道")
        
        # 收集未分类的频道 - 按原始分类分组
        uncategorized_groups = defaultdict(list)
        
        # 优化2: 合并过滤步骤 (模板过滤、黑名单过滤、去重)
        processed_channels = []
        seen_urls = set()
        
        for chan in all_channels:
            # 保存原始分类信息
            original_category = chan.category or "未分类"
            
            # 频道名称标准化
            chan.name = matcher.normalize_channel_name(chan.name)
            # 智能分类
            chan.category = matcher.match(chan.name)
            
            # 检查是否分类成功
            if not chan.category or chan.category == "未分类":
                # 清理频道名称中的特殊字符
                clean_name = re.sub(r'[\n\r\t]', ' ', chan.name).strip()
                # 添加到未分类列表，按原始分类分组
                uncategorized_groups[original_category].append((clean_name, chan.url))
            
            # 过滤条件检查
            if not matcher.is_in_template(chan.name):  # 模板过滤
                classify_progress.update()
                continue
            if is_blacklisted(chan, blacklist):  # 黑名单过滤
                classify_progress.update()
                continue
            if chan.url in seen_urls:  # URL去重
                classify_progress.update()
                continue
                
            seen_urls.add(chan.url)
            processed_channels.append(chan)
            classify_progress.update()
            
            # 每处理500个频道释放一次内存
            if len(processed_channels) % batch_size == 0:
                gc.collect()
        
        classify_progress.complete()
        logger.info(f"过滤后频道数量: {len(processed_channels)}/{len(all_channels)}")
        
        # 计算未分类频道总数
        uncategorized_count = sum(len(channels) for channels in uncategorized_groups.values())
        logger.info(f"未分类频道数量: {uncategorized_count}")
        
        # 保存未分类频道到文件，按分类分组
        if uncategorized_groups:
            # 确保目录存在
            uncategorized_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 按分类名称排序
            sorted_categories = sorted(uncategorized_groups.keys())
            
            with open(uncategorized_path, 'w', encoding='utf-8') as f:
                f.write("# 未分类频道列表 (自动生成)\n")
                f.write("# 格式按原始分类分组\n\n")
                
                for category in sorted_categories:
                    # 写入分类标题行
                    f.write(f"{category},#genre#\n")
                    
                    # 对该分类下的频道按名称排序
                    channels = sorted(uncategorized_groups[category], key=lambda x: x[0])
                    
                    # 写入该分类下的所有频道
                    for name, url in channels:
                        # 确保名称没有逗号（替换为全角逗号）
                        name = name.replace(',', '，')
                        f.write(f"{name},{url}\n")
                    
                    # 添加空行分隔不同分类
                    f.write("\n")
            
            logger.info(f"📝📝📝📝 未分类频道已保存到: {uncategorized_path}")
        else:
            logger.info("✅ 所有频道均已分类，无未分类频道")
        
        del all_channels, uncategorized_groups  # 立即释放内存
        gc.collect()
        
        # 按模板排序并优先白名单频道
        sorted_channels = matcher.sort_channels_by_template(processed_channels, whitelist)
        
        # 阶段4: 测速测试 (分批处理)
        tester = SpeedTester(
            timeout=tester_timeout,
            concurrency=tester_concurrency,
            max_attempts=tester_max_attempts,
            min_download_speed=tester_min_download_speed,
            enable_logging=tester_enable_logging
        )
        
        # 优化3: 分批测速 (每批500个频道)
        batch_size = 500
        total_channels = len(sorted_channels)
        test_progress = SmartProgress(total_channels, "⏱⏱⏱️ 测速测试")
        failed_urls = set()
        
        for i in range(0, total_channels, batch_size):
            batch = sorted_channels[i:i+batch_size]
            await tester.test_channels(batch, test_progress.update, failed_urls, whitelist)
            # 立即释放已测试批次的内存
            del batch
            gc.collect()
            
        test_progress.complete()
        logger.info("测速测试完成")
        
        # 写入失败的 URL
        if failed_urls:
            failed_urls_path = Path(config.get('PATHS', 'failed_urls_path', fallback='config/failed_urls.txt'))
            # 确保目录存在
            failed_urls_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(failed_urls_path, 'w', encoding='utf-8') as f:
                f.write("# 测速失败的URL列表 (自动生成)\n")
                for url in failed_urls:
                    f.write(f"{url}\n")
            logger.info(f"📝📝📝📝 测速失败的 URL 已写入: {failed_urls_path}")
        
        # 阶段5: 结果导出
        exporter = ResultExporter(
            output_dir=str(output_dir),
            enable_history=enable_history,
            template_path=str(templates_path),
            config=config,
            matcher=matcher
        )
        export_progress = SmartProgress(1, "💾💾💾💾 导出结果")
        exporter.export(sorted_channels, export_progress.update)
        export_progress.complete()
        
        # 输出摘要
        online = sum(1 for c in sorted_channels if c.status == 'online')
        logger.info(f"✅ 任务完成！在线频道: {online}/{len(sorted_channels)}")
        logger.info(f"📂📂📂📂 输出目录: {output_dir.resolve()}")
    
    except Exception as e:
        logger.error(f"❌❌❌❌ 发生错误: {str(e)}", exc_info=True)
        logger.info("💡💡💡💡 排查建议:")
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
        logging.error(f"❌❌❌❌ 全局异常捕获: {str(e)}", exc_info=True)
