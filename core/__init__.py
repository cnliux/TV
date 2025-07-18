# core/__init__.py

# 基础模块
from .models import Channel
from .fetcher import SourceFetcher
from .parser import PlaylistParser
from .matcher import AutoCategoryMatcher
from .tester import SpeedTester
from .exporter import ResultExporter
from .progress import SmartProgress

# 显式声明导出的公共API
__all__ = [
    'Channel',
    'SourceFetcher',
    'PlaylistParser',
    'AutoCategoryMatcher',
    'SpeedTester',
    'ResultExporter',
    'SmartProgress'
]

# 版本信息
__version__ = '1.0.1'
__author__ = 'Your Name <your.email@example.com>'
