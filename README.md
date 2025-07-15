
# IPTV频道管理工具

![IPTV标志](https://socialify.git.ci/cnliux/TV/image?description=1&descriptionEditable=IPTV%20%E7%9B%B4%E6%92%AD%E6%BA%90&forks=1&language=1&name=1&owner=1&pattern=Circuit%20Board&stargazers=1&theme=Auto)

------------
### 免责条款
使用风险：您使用本技术内容时，需自行承担所有风险，包括但不限于数据丢失、系统故障或兼容性问题。
无保证声明：本技术内容不包含任何形式的明示或暗示保证，包括但不限于适销性、特定用途的适用性或不侵权保证。
责任限制：对于因使用本技术内容而导致的任何直接、间接、附带或后果性损害，我们不承担任何责任。

## 🌐 镜像地址

---

## 📌 项目概述
自动化IPTV频道管理解决方案，支持：
- 多源订阅抓取
- 智能规则分类
- 实时速度测试
- 多格式导出

---

# 🚦 使用指南
- IPv4编辑config.ini配置参数

- IPv4将订阅源添加到urls.txt

- IPv4运行主程序：

- bash
- python main.py
## 📂 项目结构详解
- project/
- │
- ├── core/                       # 核心功能模块
- │   ├── __init__.py             # 模块初始化文件
- │   ├── fetcher.py              # 订阅源抓取模块
- │   │   ├── SourceFetcher       # 多线程 URL 抓取器
- │   │   └── 支持超时/重试机制
- │   │
- │   ├── parser.py               # 播放列表解析器
- │   │   ├── PlaylistParser      # 支持 M3U/EXTINF 格式
- │   │   └── URL 参数过滤
- │   │
- │   ├── matcher.py              # 智能分类引擎
- │   │   ├── AutoCategoryMatcher # 自动分类匹配器
- │   │   ├── 正则规则匹配
- │   │   └── 频道名称标准化
- │   │
- │   ├── tester.py               # 速度测试模块
- │   │   ├── SpeedTester         # 多线程测速器
- │   │   └── 白名单跳过机制
- │   │
- │   ├── exporter.py             # 结果导出器
- │   │   ├── ResultExporter      # 导出结果
- │   │   ├── 支持 M3U/TXT/CSV 格式
- │   │   └── IP 版本分类导出
- │   │
- │   └── models.py               # 数据模型
- │       └── Channel 类定义
- │
- ├── config/                     # 配置目录
- │   ├── config.ini              # 主配置文件
- │   │   ├── [MAIN] 基础设置
- │   │   ├── [FETCHER] 抓取参数
- │   │   ├── [TESTER] 测速设置
- │   │   └── [DEBUG] 调试选项
- │   │
- │   ├── urls.txt                # 订阅源列表
- │   ├── templates.txt           # 分类规则模板
- │   ├── blacklist.txt           # 黑名单数据
- │   └── whitelist.txt           # 白名单数据
- │
- ├── outputs/                    # 生成文件目录
- │   ├── ipv4.m3u                # IPv4 频道列表
- │   ├── ipv6.m3u                # IPv6 频道列表
- │   ├── all.txt                 # 合并文本格式
- │   └── history_*.csv           # 历史记录文件
- │
- ├── main.py                     # 程序主入口
- ├── requirements.txt            # 依赖库清单
- └── README.md                   # 项目文档
  [![Star History Chart](https://api.star-history.com/svg?repos=cnliux/tv&type=Date)](https://www.star-history.com/#cnliux/tv&Date)
### 典型工作流程
```mermaid
graph TD
    A[main.py] --> B[获取订阅源]
    B --> C[解析频道数据]
    C --> D[智能分类]
    D --> E[速度测试]
    E --> F[结果导出]
    F --> G[生成播放列表]



