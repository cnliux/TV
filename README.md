
# IPTV频道管理工具

![IPTV标志](https://socialify.git.ci/cnliux/TV/image?description=1&descriptionEditable=IPTV%20%E7%9B%B4%E6%92%AD%E6%BA%90&forks=1&language=1&name=1&owner=1&pattern=Circuit%20Board&stargazers=1&theme=Auto)

------------
## 📌 免责声明​
- ⚠️ ​使用风险​：本工具仅供学习和技术研究，使用者需自行承担所有风险，包括但不限于数据丢失、系统故障或兼容性问题。
- ⚠️ ​无保证声明​：本工具不提供任何形式的明示或暗示保证，包括但不限于适销性、特定用途的适用性或不侵权保证。
- ⚠️ ​责任限制​：对于因使用本工具而导致的任何直接、间接、附带或后果性损害，开发者不承担任何责任。

## 🌐 镜像地址

---

## 📌 项目概述
自动化IPTV频道管理解决方案，支持：
- ​多源数据获取​：并行抓取多个订阅源
- ​智能分类系统​：基于正则规则自动分类频道
- ​动态测速引擎​：多线程测试频道可用性和速度
- ​协议识别​：自动区分IPv4/IPv6频道
- ​黑白名单过滤​：自定义频道过滤规则
- ​多格式导出​：支持M3U、TXT、CSV等格式
- ​历史记录​：可选启用带时间戳的历史记录
- ​性能优化​：动态进度条和批量处理机制
---

# 🚦 使用指南
- IPv4编辑config.ini配置参数

- IPv4将订阅源添加到urls.txt

- IPv4运行主程序：

- bash
- python main.py
## 📂 项目结构详解
- project/
- ├── core/                       # 核心功能模块
- │   ├── fetcher.py              # 订阅源抓取
- │   ├── parser.py               # 播放列表解析
- │   ├── matcher.py              # 智能分类引擎
- │   ├── tester.py               # 速度测试
- │   ├── exporter.py             # 结果导出
- │   ├── models.py               # 数据模型
- │   └── progress.py             # 智能进度系统
- ├── config/                     # 配置目录
- │   ├── config.ini              # 主配置文件
- │   ├── urls.txt                # 订阅源列表
- │   ├── templates.txt           # 分类规则模板
- │   ├── blacklist.txt           # 黑名单
- │   └── whitelist.txt           # 白名单
- ├── outputs/                    # 生成文件目录
- │   ├── ipv4.m3u                # IPv4频道列表
- │   ├── ipv6.m3u                # IPv6频道列表
- │   ├── all.txt                 # 合并文本格式
- │   └── history_*.csv           # 历史记录文件
- ├── main.py                     # 程序主入口
- ├── requirements.txt            # 依赖库清单
- └── README.md                   # 项目文档
### 典型工作流程
```mermaid
graph TD
    A[main.py] --> B[获取订阅源]
    B --> C[解析频道数据]
    C --> D[智能分类]
    D --> E[速度测试]
    E --> F[结果导出]
    F --> G[生成播放列表]



