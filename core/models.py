import re
from dataclasses import dataclass
from typing import ClassVar

@dataclass
class Channel:
    """频道数据模型（简化版，移除__slots__以避免冲突）"""
    name: str
    url: str
    category: str = "未分类"
    status: str = "pending"
    response_time: float = 0.0
    download_speed: float = 0.0

    # 类变量（使用ClassVar明确标记，避免与实例属性冲突）
    IPV4_PATTERN: ClassVar[re.Pattern] = re.compile(r'https?://(?:\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|[a-zA-Z0-9.-]+)(?::\d+)?')
    IPV6_PATTERN: ClassVar[re.Pattern] = re.compile(r'https?://(?:\[[a-fA-F0-9:]+\]|[\w:]+:[a-fA-F0-9:]+)')
    RTP_PATTERN: ClassVar[re.Pattern] = re.compile(r'^rtp://', re.IGNORECASE)

    @classmethod
    def classify_ip_type(cls, url: str) -> str:
        """分类IP类型: ipv4, ipv6, rtp 或 other"""
        if cls.RTP_PATTERN.match(url):
            return "rtp"
        if cls.IPV6_PATTERN.search(url):
            return "ipv6"
        if cls.IPV4_PATTERN.search(url):
            return "ipv4"
        return "other"
