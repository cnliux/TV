# core/models.py
import re
from dataclasses import dataclass
from typing import ClassVar

@dataclass
class Channel:
    """频道数据模型"""
    name: str
    url: str
    category: str = "未分类"
    original_category: str = "未分类"
    status: str = "pending"
    response_time: float = 0.0
    download_speed: float = 0.0

    # IP分类正则表达式
    IPV4_PATTERN: ClassVar[re.Pattern] = re.compile(
        r'https?://(?:'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}'  # IPv4地址
        r'|'  # 或
        r'[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'  # 域名
        r')(?::\d+)?'  # 可选端口号
    )
    
    IPV6_PATTERN: ClassVar[re.Pattern] = re.compile(
        r'https?://(?:'  # IPv6地址
        r'\[[0-9a-fA-F:]+\]'  # 方括号格式的IPv6地址
        r'|'  # 或
        r'[0-9a-fA-F]*:[0-9a-fA-F:]+'  # 不带方括号的IPv6地址
        r')'
    )

    @classmethod
    def classify_ip_type(cls, url: str) -> str:
        """分类IP类型: ipv4 或 ipv6"""
        if cls.IPV6_PATTERN.search(url):
            return "ipv6"
        # 所有其他地址都视为ipv4
        return "ipv4"
