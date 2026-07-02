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

### 控制与快捷键

- **平移画布：** 按住**鼠标中键 (MMB)** 并拖动。
- **缩放：** 滚动**鼠标滚轮**。
- **添加节点：** 按下**空格键**或在画布空白处**右键单击**以打开搜索菜单。选择要创建的命令或参数节点。
- **连接套接字：** 从输出套接字拖动一条线到兼容的输入套接字。
  - 从套接字拖动并在空白区域释放，将自动打开搜索菜单以添加并自动连接新节点。
- **删除节点/连接：** 选择项并按下 **Delete** 键。
- **组合节点：** 选择多个节点并按下 **Ctrl + G** 将它们放入一个逻辑框架中。
- **复制节点：** 选择节点并按下 **Ctrl + D** 进行复制。
- **复制 / 粘贴：** 选择节点并按 **Ctrl + C** 复制，在光标位置按 **Ctrl + V** 粘贴。
- **撤销 / 重做：** 按 **Ctrl + Z** 撤销，按 **Ctrl + Y**（或 **Ctrl + Shift + Z**）重做。
- **全选：** 按 **Ctrl + A**。
- **切换网格：** 按 **G** 键切换网格可见性。
- **适应视口：** 按 **F** 键聚焦于所选节点（如果未选择任何节点，则聚焦于所有节点）。
- **重命名节点：** 选择参数节点并按下 **F2** 键。
- **全屏：** 按 **F11** 键切换全屏模式。

### 执行流程

1. **初始化链：** `> START` 节点始终存在于画布上。
2. **添加命令节点：** 按**空格键**添加命令（例如 `-addFolder`, `-align` 等）。
3. **链接执行路径：** 从 `> START` 节点的输出开始，依次连接命令节点的执行套接字（箭头形状）。
4. **配置参数：** 通过搜索菜单（空格键）添加参数节点（String、Integer、Float、File/Dir Path 等），并将其输出连接到命令节点的输入套接字。
5. **运行：** 单击 `> START` 节点上的 **> Launch** 按钮以在 RealityCapture 中执行命令行链。


## 项目结构

- `nodeRC.py` - 主入口点。
- `ui/editor_window.py` - 主编辑器窗口：键盘快捷键、撤销历史、项目对话框。
- `ui/scene.py` - 画布场景、连接拖拽和可视项事件处理。
- `ui/view.py` - 图形视图逻辑、平移和缩放。
- `ui/graph_items.py` - 场景可视元素：套接字、连接、节点/框架渲染。
- `ui/command_nodes.py` - Start 和 Command 节点类。
- `ui/param_nodes.py` - 参数节点类（String、Bool、Integer、Float、Enum、Path 等）。
- `core/node_blueprint.py` - 节点/套接字规格以及命令与参数定义构建器。
- `core/graph_serialization.py` - 保存/加载/复制粘贴/撤销共用的快照格式。
- `core/chain_execution.py` - 根据节点图构建 RealityCapture CLI 调用。
- `core/command_database.py` - 加载已解析的 RealityCapture 命令目录。
- `ui/theme.py` - 派生颜色以及内嵌控件的 Qt 样式表。
- `ui/color_picker.py` - 应用内 HSVA 取色器弹窗。
- `ui/inset_fill_checkbox.py` - 共享的复选框基础控件。
- `ui/flag_icon.py` - 反映当前界面语言的窗口图标。
- `configuration.py` - 样式、UI 设置和快捷键的单数据源。
- `ui/search_menu.py` - 用于生成节点的自动完成搜索对话框。
- `diagnostics.py` - 异常处理和错误日志记录。
- `localization.py` - 基于 gettext 的运行时翻译层。
- `core/rc_documentation_extractor.py` - 从本地 RealityCapture 文档构建命令数据库的实用程序。

## 许可证

本项目按“原样”分发。有关更多信息，请参阅项目文件。

## 免责声明

本项目是一个独立的、非官方的开源工具，与 Capturing Reality、Epic Games 或其任何关联公司没有关联、认可、赞助或联系。“RealityCapture”和“RealityScan”是 Epic Games, Inc. 或其关联公司的商标或注册商标。
