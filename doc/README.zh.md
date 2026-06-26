# NodeRC

![Screenshot](images/Screenshot.png)

[English](../README.md) | [Українська](README.uk.md) | [Español](README.es.md) | [中文](README.zh.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [日本語](README.ja.md) | [हिन्दी](README.hi.md) | [Português](README.pt.md) | [العربية](README.ar.md)

NodeRC 是一个用于 RealityCapture / RealityScan CLI 命令的非官方基于节点的可视化界面和编辑器。该项目使用 Python 和 PyQt5 编写，允许您在交互式画布上可视化地连接和管理命令节点，为工作流自动化提供用户友好的界面。

## 特性

- **交互式画布 (Canvas)：** 支持平移和缩放的无限工作区。
- **节点架构：** 支持输入和输出连接 (套接字) 的各种类型的节点。
- **动态连接：** 执行端口和数据端口的可视化链接。
- **配置系统：** 通过集中式配置文件自定义颜色、大小和样式。
- **搜索菜单：** 用于快速向画布添加新节点的便捷菜单。

## 要求

- Python 3.7+
- PyQt5

## 安装

1. 克隆仓库：

   ```bash
   git clone <仓库的URL>
   cd nodeRC
   ```

2. 安装依赖项：
   ```bash
   pip install -r requirements.txt
   ```

## 运行

要启动编辑器，请运行：

```bash
python nodeRC.py
```

## 项目结构

- `nodeRC.py` - 主入口点。
- `canvas.py` - 交互式画布逻辑和图表管理。
- `nodes.py` - 节点和套接字的基础和专用类。
- `configuration.py` - 配置文件 (颜色、样式、UI 参数)。
- `search_menu.py` - 用于搜索和添加节点的对话框。
- `diagnostics.py` - 日志记录和异常处理。
- `rc_documentation_extractor.py` - 用于提取命令文档的实用程序。

## 许可证

本项目按“原样”分发。有关更多信息，请参阅项目文件。

## 免责声明

本项目是一个独立的、非官方的开源工具，与 Capturing Reality、Epic Games 或其任何关联公司没有关联、认可、赞助或联系。“RealityCapture”和“RealityScan”是 Epic Games, Inc. 或其关联公司的商标或注册商标。
