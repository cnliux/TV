#!/usr/bin/env python3
import os
import asyncio
import configparser
from pathlib import Path
from typing import List, Set, Callable
import re
import logging
import sys
import io
from core.models import Channel
from core import (
    SourceFetcher,
    PlaylistParser,
    AutoCategoryMatcher,
    SpeedTester,
    ResultExporter
)

# 设置标准输出编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

class StageProgress:
    """阶段进度显示器"""
    
    def __init__(self, stage_name: str, total: int, update_interval: int = 10):
        self.stage = stage_name
        self.total = max(total, 1)
        self.current = 0
        self.bar_length = 30
        self.update_interval = update_interval
        self.start_time = asyncio.get_event_loop().time()

    def update(self, n=1):
        self.current = min(self.current + n, self.total)
        if self.update_interval <= 0 or self.current % self.update_interval == 0 or self.current == self.total:
            self._print_progress()

    def _print_progress(self):
        percent = min(100.0, self.current / self.total * 100)
        filled = int(self.bar_length * self.current / self.total)
        bar = '■' * filled + ' ' * (self.bar_length - filled)
        elapsed = asyncio.get_event_loop().time() - self.start_time
        remaining = (elapsed / self.current) * (self.total - self.current) if self.current > 0 else 0
        time_str = f"{remaining:.1f}s" if remaining < 60 else f"{remaining/60:.1f}m"
        print(f"\r{self.stage.ljust(15)} [{bar}] {percent:.1f}% | 剩余: {time_str}", end='', flush=True)

    def complete(self):
        self.current = self.total
        self._print_progress()
        print()

def is_blacklisted(channel: Channel, blacklist: Set[str]) -> bool:
    """检查频道是否在黑名单中"""
    normalized_name = re.sub(r'[^\w\u4e00-\u9fff]', '', channel.name).lower()
    normalized_url = channel.url.lower()
    
    for entry in blacklist:
        norm_entry = re.sub(r'[^\w\u4e00-\u9fff]', '', entry).lower()
        if norm_entry and (norm_entry in normalized_url or norm_entry == normalized_name):
            return True
    return False

async def main():
    """主工作流程"""
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
        
        # 动态配置日志（关键改进点）
        debug_mode = config.getboolean('DEBUG', 'enable_debug_logging', fallback=False)
        log_to_file = config.getboolean('DEBUG', 'log_to_file', fallback=False)

        handlers = [logging.StreamHandler()]
        if log_to_file:
            log_file_path = config.get('DEBUG', 'log_file_path', fallback='debug.log')
            handlers.append(logging.FileHandler(log_file_path, encoding='utf-8'))

        logging.basicConfig(
            level=logging.DEBUG if debug_mode else logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=handlers
        )
        logger = logging.getLogger(__name__)

        # 创建输出目录
        output_dir = Path(config.get('MAIN', 'output_dir', fallback='outputs'))
        output_dir.mkdir(parents=True, exist_ok=True)

        # 加载黑名单
        blacklist_path = Path(config.get('BLACKLIST', 'blacklist_path', fallback='config/blacklist.txt'))
        blacklist = set()
        if blacklist_path.exists():
            with open(blacklist_path, 'r', encoding='utf-8') as f:
                blacklist = {line.strip() for line in f if line.strip() and not line.startswith('#')}
        logger.info(f"已加载黑名单: {len(blacklist)} 条规则")

        # 加载白名单
        whitelist_path = Path(config.get('WHITELIST', 'whitelist_path', fallback='config/whitelist.txt'))
        whitelist = set()
        if whitelist_path.exists():
            with open(whitelist_path, 'r', encoding='utf-8') as f:
                whitelist = {line.strip() for line in f if line.strip() and not line.startswith('#')}
        logger.info(f"已加载白名单: {len(whitelist)} 条规则")

        # 阶段1: 获取订阅源
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
        
        progress = StageProgress("🌐 获取源数据", len(urls), 
                               int(config.get('PROGRESS', 'update_interval_fetch', fallback=10)))
        contents = await fetcher.fetch_all(urls, progress.update)
        progress.complete()
        logger.info(f"获取到 {len([c for c in contents if c])}/{len(urls)} 个有效订阅源")

        # 阶段2: 解析频道
        parser = PlaylistParser(config)
        valid_contents = [c for c in contents if c and c.strip()]
        progress = StageProgress("🔍 解析频道", len(valid_contents),
                               int(config.get('PROGRESS', 'update_interval_parse', fallback=40)))
        
        channels = []
        for content in valid_contents:
            try:
                channels.extend(list(parser.parse(content)))
                progress.update()
            except Exception as e:
                logger.error(f"解析失败: {str(e)}")
                continue
                
        progress.complete()
        logger.info(f"初步解析完成，共 {len(channels)} 个频道")

        # 预处理频道数据
        pre_progress = StageProgress("🛠️ 预处理频道", len(channels))
        valid_channels = []
        seen_urls = set()
        
        for chan in channels:
            # 基础清理
            chan.name = re.sub(r'[^\w\u4e00-\u9fff\-_ ]', '', chan.name.strip())
            if not chan.name:
                chan.name = f"未命名_{hash(chan.url)}"
            
            # URL去重
            base_url = chan.url.split('?')[0].split('#')[0]
            if base_url in seen_urls:
                continue
            seen_urls.add(base_url)
            
            # 过滤黑名单
            if is_blacklisted(chan, blacklist):
                continue
                
            valid_channels.append(chan)
            pre_progress.update()
        
        pre_progress.complete()
        logger.info(f"预处理后有效频道: {len(valid_channels)}/{len(channels)}")

        # 阶段3: 智能分类
        templates_path = Path(config.get('PATHS', 'templates_path', fallback='config/templates.txt'))
        if not templates_path.exists():
            raise FileNotFoundError(f"分类模板文件不存在: {templates_path}")
        
        matcher = AutoCategoryMatcher(str(templates_path))
        progress = StageProgress("🏷️ 分类频道", len(valid_channels),
                               int(config.get('PROGRESS', 'update_interval_classify', fallback=50)))
        
        for chan in valid_channels:
            chan.category = matcher.match(chan)
            progress.update()
        
        progress.complete()
        
        # 统计分类结果
        category_counts = {}
        for chan in valid_channels:
            category_counts[chan.category] = category_counts.get(chan.category, 0) + 1
        stats = ", ".join(f"{k}:{v}" for k, v in sorted(category_counts.items()))
        logger.info(f"分类统计: {stats}")

        # 阶段4: 测速测试
        tester = SpeedTester(
            timeout=float(config.get('TESTER', 'timeout', fallback=5)),
            concurrency=int(config.get('TESTER', 'concurrency', fallback=4)),
            max_attempts=int(config.get('TESTER', 'max_attempts', fallback=3)),
            min_download_speed=float(config.get('TESTER', 'min_download_speed', fallback=0.2)),
            enable_logging=config.getboolean('TESTER', 'enable_logging', fallback=False)
        )
        
        # 分批测速
        batch_size = 5000
        failed_urls = set()
        total_batches = (len(valid_channels) + batch_size - 1) // batch_size
        
        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            batch = valid_channels[start_idx: start_idx + batch_size]
            
            logger.info(f"\n=== 开始测速批次 {batch_num + 1}/{total_batches} ({len(batch)} 个频道) ===")
            progress = StageProgress(f"⏱️ 测速批次 {batch_num+1}", len(batch),
                                   int(config.get('PROGRESS', 'update_interval_speedtest', fallback=100)))
            
            await tester.test_channels(batch, progress.update, failed_urls, whitelist)
            progress.complete()
            
            # 释放内存
            del batch
            import gc; gc.collect()

        # 保存测速结果
        if failed_urls:
            failed_path = Path(config.get('PATHS', 'failed_urls_path', fallback='config/failed_urls.txt'))
            with open(failed_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(sorted(failed_urls)))
            logger.info(f"保存测速失败URL到: {failed_path}")

        # 阶段5: 结果导出
        exporter = ResultExporter(
            output_dir=str(output_dir),
            enable_history=config.getboolean('EXPORTER', 'enable_history', fallback=False),
            template_path=str(templates_path),
            config=config,
            matcher=matcher
        )
        
        progress = StageProgress("💾 导出结果", 1)
        exporter.export(valid_channels, progress.update)
        progress.complete()

        # 最终统计
        online = sum(1 for c in valid_channels if c.status == 'online')
        logger.info(f"\n{'='*50}")
        logger.info(f"✅ 任务完成! 总计: {len(valid_channels)} 个频道")
        logger.info(f"🟢 在线: {online} | 🔴 离线: {len(valid_channels)-online}")
        logger.info(f"📂 输出目录: {output_dir.resolve()}")
        logger.info("="*50)

    except Exception as e:
        logger.error(f"❌ 主流程异常: {str(e)}", exc_info=True)
        raise

if __name__ == "__main__":
    # Windows事件循环策略
    if os.name == 'nt':
        from asyncio import WindowsSelectorEventLoopPolicy
        asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n用户中断操作")
    except Exception as e:
        logging.error(f"全局异常: {str(e)}", exc_info=True)
        sys.exit(1)
