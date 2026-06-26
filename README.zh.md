# NodeRC

[English](README.md) | [Русский](README.ru.md) | [Español](README.es.md) | [中文](README.zh.md)

NodeRC 是一个使用 PyQt5 用 Python 编写的基于节点的可视化编辑器。该项目允许您在交互式画布上创建、连接和管理节点，为可视化编程或逻辑图构建提供用户友好的界面。

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
