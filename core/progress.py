# core/progress.py

import time
import math
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

class SmartProgress:
    """智能进度系统（动态更新频率+精准时间预估）"""
    
    def __init__(self, total: int, desc: str = "Processing", min_update_interval: float = 0.5):
        self.total = total
        self.desc = desc
        self.min_update_interval = min_update_interval
        self.start_time = time.time()
        self.last_update_time = self.start_time
        self.current = 0
        self.completed = 0
        
        # 动态计算初始更新频率
        self.update_interval = self._calculate_initial_interval()
        
        # 历史记录用于预测
        self.history = []
        self.max_history_size = 10
        
    def _calculate_initial_interval(self) -> int:
        """根据总量计算初始更新频率"""
        if self.total <= 1000:
            return 10
        elif self.total <= 10000:
            return 100
        elif self.total <= 100000:
            return 500
        else:
            return max(1000, self.total // 100)
    
    def update(self, n: int = 1):
        """更新进度"""
        self.current += n
        self.completed += n
        
        # 检查是否需要更新显示
        current_time = time.time()
        if (current_time - self.last_update_time) >= self.min_update_interval:
            self._update_display()
            self.last_update_time = current_time
            
            # 自适应调整更新频率
            self._adjust_update_interval()
    
    def _update_display(self):
        """更新进度显示"""
        elapsed = time.time() - self.start_time
        
        # 智能时间格式转换
        elapsed_str = self._format_time(elapsed)
        
        # 计算剩余时间
        if self.current > 0:
            # 使用EMA平滑处理速度变化
            current_speed = self.current / elapsed
            self.history.append(current_speed)
            if len(self.history) > self.max_history_size:
                self.history.pop(0)
                
            # 计算加权平均速度
            avg_speed = self._weighted_average_speed()
            
            # 计算预估剩余时间
            remaining_items = self.total - self.completed
            if avg_speed > 0:
                remaining_time = remaining_items / avg_speed
                remaining_str = self._format_time(remaining_time)
            else:
                remaining_str = "计算中..."
        else:
            remaining_str = "计算中..."
            
        # 进度百分比
        percent = (self.completed / self.total) * 100 if self.total > 0 else 100
        
        # 进度条显示
        bar_length = 30
        filled_length = int(bar_length * self.completed // self.total)
        bar = '■' * filled_length + '□' * (bar_length - filled_length)
        
        # 状态信息
        status = f"\r{self.desc} {bar} {percent:.1f}% | 用时: {elapsed_str} | 预计剩余: {remaining_str}"
        print(status, end='', flush=True)
        
        # 完成时添加换行
        if self.completed >= self.total:
            print()
    
    def _weighted_average_speed(self) -> float:
        """计算加权平均速度（近期速度权重更高）"""
        if not self.history:
            return 0
        
        total = 0
        weights = 0
        for i, speed in enumerate(reversed(self.history)):
            weight = 2 ** i  # 指数权重
            total += speed * weight
            weights += weight
            
        return total / weights
    
    def _adjust_update_interval(self):
        """动态调整更新频率"""
        # 基于当前速度和剩余项目计算
        if self.history:
            current_speed = self.history[-1]
            if current_speed > 0:
                items_per_second = current_speed
                # 目标: 每秒更新1-2次
                ideal_interval = min(1.0, 0.5 / items_per_second) if items_per_second > 0 else 1.0
                
                # 平滑过渡
                self.update_interval = max(1, min(
                    self.update_interval * 0.7 + ideal_interval * 0.3,
                    self.total // 10  # 上限
                ))
    
    def _format_time(self, seconds: float) -> str:
        """智能时间格式转换"""
        if seconds < 60:
            return f"{seconds:.1f}秒"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f}分钟"
        else:
            hours = seconds / 3600
            return f"{hours:.1f}小时"
    
    def complete(self):
        """完成进度显示"""
        if self.completed < self.total:
            self.current = self.total
            self.completed = self.total
            self._update_display()
        else:
            self._update_display()
            
        # 记录最终用时
        elapsed = time.time() - self.start_time
        logger.info(f"{self.desc} 完成! 用时: {self._format_time(elapsed)}")
