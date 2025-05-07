#!/usr/bin/env python3
import re
from typing import Dict, List, Set
import logging
from .models import Channel

class AutoCategoryMatcher:
    """分类匹配器，支持从模板文件中读取分类规则和多名称映射"""

    def __init__(self, template_path: str):
        """
        初始化分类匹配器。

        :param template_path: 模板文件路径。
        """
        self.template_path = template_path
        self.categories = self._parse_template()
        self.name_mapping = self._build_name_mapping()
        self.suffixes = ["高清", "HD", "综合"]  # 可配置的后缀列表

    def _parse_template(self) -> Dict[str, List[re.Pattern]]:
        """
        解析模板文件。

        :return: 分类字典，键为分类名称，值为正则表达式列表。
        """
        categories = {}
        current_category = None
        with open(self.template_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue  # 跳过空行和注释行

                # 检查是否为分类行
                if line.endswith(',#genre#'):
                    current_category = line.split(',')[0]
                    categories[current_category] = []
                    continue

                # 处理频道名称或正则表达式规则
                if current_category:
                    try:
                        pattern = re.compile(line)
                        categories[current_category].append(pattern)
                    except re.error as e:
                        logging.error(f"正则表达式编译失败: {line} ({str(e)})")
                        continue  # 跳过无效的正则表达式
        return categories

    def _build_name_mapping(self) -> Dict[str, str]:
        """
        构建名称映射，将模板中的多个名称映射到标准名称。

        :return: 名称映射字典，键为频道名称，值为标准名称。
        """
        name_mapping = {}
        with open(self.template_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue  # 跳过空行和注释行

                # 检查是否为分类行
                if line.endswith(',#genre#'):
                    continue

                # 处理频道名称或正则表达式规则
                parts = line.split('|')
                if len(parts) > 1:
                    standard_name = parts[0]  # 第一个名称作为标准名称
                    for name in parts:
                        name_mapping[name] = standard_name
        return name_mapping

    def match(self, channel_name: str) -> str:
        """
        匹配频道分类。

        :param channel_name: 频道名称。
        :return: 匹配的分类名称，如果未匹配则返回 "其他"。
        """
        for category, patterns in self.categories.items():
            for pattern in patterns:
                if pattern.search(channel_name):
                    return category
        return "其他"

    def is_in_template(self, channel_name: str) -> bool:
        """
        检查频道名称是否在模板中。

        :param channel_name: 频道名称。
        :return: 如果频道名称匹配模板中的规则，则返回 True，否则返回 False。
        """
        for patterns in self.categories.values():
            for pattern in patterns:
                if pattern.search(channel_name):
                    return True
        return False

    def normalize_channel_name(self, channel_name: str) -> str:
        """
        将频道名称规范化为模板中的标准名称。

        :param channel_name: 原始频道名称。
        :return: 规范化后的频道名称。
        """
        # 去除多余的空格和特殊字符
        channel_name = channel_name.strip()

        # 如果频道名称中包含后缀，则去掉这些后缀
        for suffix in self.suffixes:
            if suffix in channel_name:
                channel_name = channel_name.replace(suffix, "")

        # 根据模板中的名称映射规范化频道名称
        if channel_name in self.name_mapping:
            return self.name_mapping[channel_name]

        return channel_name

    def sort_channels_by_template(self, channels: List[Channel], whitelist: Set[str]) -> List[Channel]:
        """
        根据模板顺序对频道进行排序，并在每个分类内部优先排序白名单频道。

        :param channels: 频道列表。
        :param whitelist: 白名单内容。
        :return: 排序后的频道列表。
        """
        # 解析模板文件，记录每个分类下的频道名称顺序
        template_order = {}  # 结构: {分类名称: [频道名称列表]}
        current_category = None

        with open(self.template_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                if line.endswith(',#genre#'):
                    # 新的分类
                    current_category = line.split(',')[0]
                    template_order[current_category] = []
                    continue

                # 当前分类下的频道名称
                if '|' in line:
                    # 处理名称列表（如 "CCTV-1|CCTV综合"）
                    names = line.split('|')
                    for name in names:
                        template_order[current_category].append(name.strip())
                else:
                    # 单个频道名称
                    template_order[current_category].append(line.strip())

        sorted_channels = []
        for category, channel_names in template_order.items():
            # 获取当前分类下的所有频道
            category_channels = [c for c in channels if c.category == category]

            # 分离白名单频道和非白名单频道
            whitelisted = [c for c in category_channels if self._is_whitelisted(c, whitelist)]
            non_whitelisted = [c for c in category_channels if not self._is_whitelisted(c, whitelist)]

            # 按照模板中的顺序排序白名单频道
            whitelisted.sort(key=lambda c: self._get_channel_order(c, channel_names))

            # 按照模板中的顺序排序非白名单频道
            non_whitelisted.sort(key=lambda c: self._get_channel_order(c, channel_names))

            # 合并白名单和非白名单频道，白名单频道优先
            sorted_category_channels = whitelisted + non_whitelisted

            # 将排序后的频道添加到结果列表中
            sorted_channels.extend(sorted_category_channels)

        # 添加未在模板中定义的分类的频道
        remaining_channels = [c for c in channels if c.category not in template_order]
        logging.info(f"未分类频道数量: {len(remaining_channels)}")
        sorted_channels.extend(remaining_channels)

        return sorted_channels

    def _is_whitelisted(self, channel: Channel, whitelist: Set[str]) -> bool:
        """检查频道是否在白名单中"""
        for entry in whitelist:
            if entry in channel.url or channel.url == entry or channel.name == entry:
                return True
        return False

    def _get_channel_order(self, channel: Channel, channel_names: List[str]) -> int:
        """
        获取频道在模板中的顺序。

        :param channel: 频道对象。
        :param channel_names: 模板中定义的频道名称列表。
        :return: 频道在模板中的顺序，未定义的频道返回一个较大的值。
        """
        try:
            # 使用 normalize_channel_name 方法去除后缀
            clean_name = self.normalize_channel_name(channel.name)
            # 匹配模板中的频道名称（支持正则表达式）
            for i, name in enumerate(channel_names):
                if re.match(f'^{name}$', clean_name):
                    return i
            return len(channel_names)  # 未定义的频道放在最后
        except Exception as e:
            logging.error(f"Error matching channel name: {channel.name}, error: {e}")
            return len(channel_names)#!/usr/bin/env python3
import re
from typing import Dict, List, Set
import logging
from .models import Channel

class AutoCategoryMatcher:
    """分类匹配器，支持从模板文件中读取分类规则和多名称映射"""

    def __init__(self, template_path: str):
        """
        初始化分类匹配器。

        :param template_path: 模板文件路径。
        """
        self.template_path = template_path
        self.categories = self._parse_template()
        self.name_mapping = self._build_name_mapping()
        self.suffixes = ["高清", "HD", "综合"]  # 可配置的后缀列表

    def _parse_template(self) -> Dict[str, List[re.Pattern]]:
        """
        解析模板文件。

        :return: 分类字典，键为分类名称，值为正则表达式列表。
        """
        categories = {}
        current_category = None
        with open(self.template_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue  # 跳过空行和注释行

                # 检查是否为分类行
                if line.endswith(',#genre#'):
                    current_category = line.split(',')[0]
                    categories[current_category] = []
                    continue

                # 处理频道名称或正则表达式规则
                if current_category:
                    try:
                        pattern = re.compile(line)
                        categories[current_category].append(pattern)
                    except re.error as e:
                        logging.error(f"正则表达式编译失败: {line} ({str(e)})")
                        continue  # 跳过无效的正则表达式
        return categories

    def _build_name_mapping(self) -> Dict[str, str]:
        """
        构建名称映射，将模板中的多个名称映射到标准名称。

        :return: 名称映射字典，键为频道名称，值为标准名称。
        """
        name_mapping = {}
        with open(self.template_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue  # 跳过空行和注释行

                # 检查是否为分类行
                if line.endswith(',#genre#'):
                    continue

                # 处理频道名称或正则表达式规则
                parts = line.split('|')
                if len(parts) > 1:
                    standard_name = parts[0]  # 第一个名称作为标准名称
                    for name in parts:
                        name_mapping[name] = standard_name
        return name_mapping

    def match(self, channel_name: str) -> str:
        """
        匹配频道分类。

        :param channel_name: 频道名称。
        :return: 匹配的分类名称，如果未匹配则返回 "其他"。
        """
        for category, patterns in self.categories.items():
            for pattern in patterns:
                if pattern.search(channel_name):
                    return category
        return "其他"

    def is_in_template(self, channel_name: str) -> bool:
        """
        检查频道名称是否在模板中。

        :param channel_name: 频道名称。
        :return: 如果频道名称匹配模板中的规则，则返回 True，否则返回 False。
        """
        for patterns in self.categories.values():
            for pattern in patterns:
                if pattern.search(channel_name):
                    return True
        return False

    def normalize_channel_name(self, channel_name: str) -> str:
        """
        将频道名称规范化为模板中的标准名称。

        :param channel_name: 原始频道名称。
        :return: 规范化后的频道名称。
        """
        # 去除多余的空格和特殊字符
        channel_name = channel_name.strip()

        # 如果频道名称中包含后缀，则去掉这些后缀
        for suffix in self.suffixes:
            if suffix in channel_name:
                channel_name = channel_name.replace(suffix, "")

        # 根据模板中的名称映射规范化频道名称
        if channel_name in self.name_mapping:
            return self.name_mapping[channel_name]

        return channel_name

    def sort_channels_by_template(self, channels: List[Channel], whitelist: Set[str]) -> List[Channel]:
        """
        根据模板顺序对频道进行排序，并在每个分类内部优先排序白名单频道。

        :param channels: 频道列表。
        :param whitelist: 白名单内容。
        :return: 排序后的频道列表。
        """
        # 解析模板文件，记录每个分类下的频道名称顺序
        template_order = {}  # 结构: {分类名称: [频道名称列表]}
        current_category = None

        with open(self.template_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                if line.endswith(',#genre#'):
                    # 新的分类
                    current_category = line.split(',')[0]
                    template_order[current_category] = []
                    continue

                # 当前分类下的频道名称
                if '|' in line:
                    # 处理名称列表（如 "CCTV-1|CCTV综合"）
                    names = line.split('|')
                    for name in names:
                        template_order[current_category].append(name.strip())
                else:
                    # 单个频道名称
                    template_order[current_category].append(line.strip())

        sorted_channels = []
        for category, channel_names in template_order.items():
            # 获取当前分类下的所有频道
            category_channels = [c for c in channels if c.category == category]

            # 分离白名单频道和非白名单频道
            whitelisted = [c for c in category_channels if self._is_whitelisted(c, whitelist)]
            non_whitelisted = [c for c in category_channels if not self._is_whitelisted(c, whitelist)]

            # 按照模板中的顺序排序白名单频道
            whitelisted.sort(key=lambda c: self._get_channel_order(c, channel_names))

            # 按照模板中的顺序排序非白名单频道
            non_whitelisted.sort(key=lambda c: self._get_channel_order(c, channel_names))

            # 合并白名单和非白名单频道，白名单频道优先
            sorted_category_channels = whitelisted + non_whitelisted

            # 将排序后的频道添加到结果列表中
            sorted_channels.extend(sorted_category_channels)

        # 添加未在模板中定义的分类的频道
        remaining_channels = [c for c in channels if c.category not in template_order]
        logging.info(f"未分类频道数量: {len(remaining_channels)}")
        sorted_channels.extend(remaining_channels)

        return sorted_channels

    def _is_whitelisted(self, channel: Channel, whitelist: Set[str]) -> bool:
        """检查频道是否在白名单中"""
        for entry in whitelist:
            if entry in channel.url or channel.url == entry or channel.name == entry:
                return True
        return False

    def _get_channel_order(self, channel: Channel, channel_names: List[str]) -> int:
        """
        获取频道在模板中的顺序。

        :param channel: 频道对象。
        :param channel_names: 模板中定义的频道名称列表。
        :return: 频道在模板中的顺序，未定义的频道返回一个较大的值。
        """
        try:
            # 使用 normalize_channel_name 方法去除后缀
            clean_name = self.normalize_channel_name(channel.name)
            # 匹配模板中的频道名称（支持正则表达式）
            for i, name in enumerate(channel_names):
                if re.match(f'^{name}$', clean_name):
                    return i
            return len(channel_names)  # 未定义的频道放在最后
        except Exception as e:
            logging.error(f"Error matching channel name: {channel.name}, error: {e}")
            return len(channel_names)
