#!/usr/bin/env python3
# core/__init__.py

from .models import Channel
from .fetcher import SourceFetcher
from .parser import PlaylistParser
from .matcher import AutoCategoryMatcher
from .tester import SpeedTester
from .exporter import ResultExporter

__all__ = [
    'SourceFetcher',
    'PlaylistParser',
    'AutoCategoryMatcher',
    'SpeedTester', 
    'ResultExporter',
    'Channel'  # 确保导出Channel类
]
