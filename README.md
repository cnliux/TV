![IPTV](https://socialify.git.ci/cnliux/TV/image?description=1&descriptionEditable=IPTV%20%E7%9B%B4%E6%92%AD%E6%BA%90&forks=1&language=1&name=1&owner=1&pattern=Circuit%20Board&stargazers=1&theme=Auto)
# IPTV 频道管理工具
镜像地址 https://fastly.jsdelivr.net/gh/cnliux/TV@main/outputs/ipv4.m3u
镜像地址 https://fastly.jsdelivr.net/gh/cnliux/TV@main/outputs/ipv6.m3u

## 项目概述

这是一个用于管理和优化 IPTV 频道的工具，能够自动获取、解析、分类和测速 IPTV 频道，并导出结果。它可以帮助用户快速筛选出可用的 IPTV 频道，提高观看体验。

## 功能特点

- **自动获取订阅源**：从指定的订阅源 URL 获取 IPTV 频道数据。
- **智能分类**：根据预定义的分类模板对频道进行自动分类。
- **测速功能**：对每个频道进行速度测试，确保只保留可用且速度良好的频道。
- **黑名单过滤**：支持通过黑名单过滤不需要的频道。
- **白名单优先**：支持通过白名单优先排序频道，白名单中的频道在各自分类中优先显示。
- **多格式导出**：支持导出为 M3U、TXT 和 CSV 格式，方便不同设备使用。
- **IPv4/IPv6 分类导出**：将频道按 IPv4 和 IPv6 地址分别导出，便于针对性使用。

## 项目结构
project/

-├── core/

-│   ├── __init__.py

-│   ├── fetcher.py

-│   ├── parser.py

-│   ├── matcher.py

-│   ├── tester.py

-│   ├── exporter.py

-│   └── models.py

-├── config/

-│   ├── config.ini

-│   ├── urls.txt

-│   ├── templates.txt

-│   ├── blacklist.txt

-│   └── whitelist.txt

-├── main.py

-└── requirements.txt

### 说明

- **core/**：核心模块，包含项目的主要功能实现。
  - `__init__.py`：初始化文件，使 core 被识别为一个 Python 包。
  - `fetcher.py`：订阅源获取器，负责从指定 URL 获取 IPTV 频道数据。
  - `parser.py`：解析器，用于解析获取到的频道数据。
  - `matcher.py`：分类匹配器，根据预定义的模板对频道进行分类。
  - `tester.py`：测速模块，对每个频道进行速度测试。
  - `exporter.py`：导出模块，将处理后的结果导出为多种格式。
  - `models.py`：定义项目中使用的数据模型。
- **config/**：配置文件，包含项目运行所需的各类配置。
  - `config.ini`：主配置文件，设置输出目录、测速参数等。
  - `urls.txt`：订阅源 URL 列表。
  - `templates.txt`：频道分类模板。
  - `blacklist.txt`：黑名单列表，包含需要过滤的域名、URL 或频道名称。
  - `whitelist.txt`：白名单列表，包含需要优先保留的域名、URL 或频道名称。
- **main.py**：项目的入口文件，包含主工作流程。
- **requirements.txt**：项目依赖的 Python 包列表，用于安装项目运行所需的依赖。

## 配置项目

1. 编辑 `config/config.ini` 文件，设置输出目录、测速参数等。
2. 在 `config/urls.txt` 中添加您的 IPTV 订阅源 URL。
3. 在 `config/templates.txt` 中定义频道分类规则。
4. 在 `config/blacklist.txt` 中添加需要过滤的域名、URL 或频道名称。
5. 在 `config/whitelist.txt` 中添加需要优先保留的域名、URL 或频道名称。

## 更新日志

### v1.0.0 (2025-4-12)
- **新增功能**：
  - **白名单支持**：支持通过白名单优先排序频道，白名单中的频道在各自分类中优先显示。
- **优化**：
  - 改进了频道排序逻辑，确保白名单频道在分类内部优先显示。
  - 优化了进度条显示，提升了用户体验。
### v1.0.1 (2025-4-13)
- **新增功能**：
  - **URL 参数过滤**：新增 `[URL_FILTER]` 配置，用于移除 URL 中的指定参数，提高数据纯净度。在 `config.ini` 中配置 `remove_params` 以指定需要移除的参数。

其他
[![Star History Chart](https://api.star-history.com/svg?repos=cnliux/tv&type=Date)](https://www.star-history.com/#cnliux/tv&Date)

![Visitor Count](https://profile-counter.glitch.me/cnliux_TV/count.svg)
