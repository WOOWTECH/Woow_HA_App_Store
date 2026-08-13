# Home Assistant 分区控制

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/WOOWTECH/Woow_ha_permission_control)](https://github.com/WOOWTECH/Woow_ha_permission_control/releases)
[![License](https://img.shields.io/github/license/WOOWTECH/Woow_ha_permission_control)](LICENSE)

[English](README.md) | 简体中文

Home Assistant 自定义组件，提供侧边栏面板，用于按区域组织和控制实体。与 [Permission Manager](../ha_permission_manager/) 集成配合使用，仅显示每个用户有权限访问的区域。

**当前版本：1.0.3**

## 功能特点

- **按区域控制实体**：查看和控制按分配区域分组的实体
- **权限感知**：与 Permission Manager 集成，仅显示每个用户有权限的区域
- **多语言支持**：英语、繁体中文 (zh-Hant) 和简体中文 (zh-Hans)
- **原生 HA 风格界面**：简洁、响应式界面，匹配 Home Assistant 现代设计
- **域摘要仪表板**：3x3 网格显示 9 个域类别（灯光、温控、窗帘、风扇、媒体、门锁、扫地机、开关、辅助开关）
- **域详情视图**：点击域摘要卡片查看所有区域中该域的所有实体
- **区域详情视图**：点击区域卡片查看该区域内所有实体，按域分组
- **紧凑域标签页**：水平可滚动标签页显示域图标和实体数量
- **搜索功能**：按名称或实体 ID 实时过滤实体
- **交互式实体卡片**：
  - 灯光亮度滑块
  - 温控 +/- 温度按钮
  - 窗帘上/停/下按钮
  - 风扇速度滑块
  - 媒体播放器播放/暂停/下一曲控制
  - 门锁锁定/解锁按钮
  - 扫地机开始/暂停/返回按钮
  - 传感器 24 小时历史迷你图表
- **实时更新**：实体状态实时更新
- **优化性能**：并行数据加载，快速初始渲染

## 截图

面板有三个视图：

1. **主页视图**：9 个域类别摘要卡片 + 区域卡片网格
2. **域视图**：点击域摘要卡片查看所有区域中该域的所有实体
3. **区域视图**：点击区域卡片查看该区域内所有实体，使用紧凑域标签页切换

## 系统要求

- Home Assistant 2024.1.0 或更新版本
- [Permission Manager](../ha_permission_manager/) 集成（依赖项）

## 安装

### HACS（推荐）

1. 在 Home Assistant 中打开 HACS
2. 点击右上角的三个点
3. 选择"自定义存储库"
4. 添加此存储库 URL：`https://github.com/WOOWTECH/Woow_ha_permission_control`
5. 选择"Integration"作为类别
6. 点击"添加"
7. 搜索"Area Control"并安装
8. 重启 Home Assistant

### 手动安装

1. 从[发布页面](https://github.com/WOOWTECH/Woow_ha_permission_control/releases)下载最新版本
2. 将 `ha_area_control` 文件夹解压到 `custom_components` 目录
3. 重启 Home Assistant

## 配置

1. 转到**设置** > **设备与服务**
2. 点击**+ 添加集成**
3. 搜索"Area Control"
4. 点击添加

安装后，侧边栏会出现新的"分区控制"面板。

## 工作原理

### 管理员用户
管理员用户可以看到 Home Assistant 中定义的所有区域，具有完全访问权限。

### 非管理员用户
非管理员用户只能看到通过 Permission Manager 集成授予访问权限的区域。权限级别：

- **关闭 (0)**：无访问权限
- **查看 (1)**：可以查看区域及其实体
- **受限 (2)**：可以查看和有限控制
- **编辑 (3)**：完全控制

## 支持的域

面板为以下域提供专用卡片控制：

| 域 | 功能 |
|---|------|
| `light` | 切换、亮度滑块、RGB 颜色支持 |
| `climate` | 切换、温度 +/- 按钮、当前温度显示 |
| `cover` | 开/停/关按钮、位置显示 |
| `fan` | 切换、速度滑块 |
| `media_player` | 上一曲/播放暂停/下一曲按钮 |
| `lock` | 锁定/解锁按钮 |
| `vacuum` | 开始/暂停/返回按钮 |
| `switch` | 切换 |
| `input_boolean` | 切换 |
| `scene` | 激活、上次触发时间 |
| `script` | 激活、上次触发时间 |
| `automation` | 切换启用/禁用 |
| `sensor` | 显示数值和单位、24小时历史图表 |
| `binary_sensor` | 显示状态 |
| `button` | 按下操作 |
| `humidifier` | 切换、湿度滑块 |

## 文件结构

```
custom_components/ha_area_control/
├── __init__.py           # 主集成设置
├── manifest.json         # 组件清单
├── config_flow.py        # 配置流程
├── const.py              # 常量
├── panel.py              # WebSocket API 处理程序
├── strings.json          # 默认字符串
├── frontend/
│   └── ha-area-control-panel.js  # 前端面板
└── translations/
    ├── en.json           # 英语翻译
    ├── zh-Hant.json      # 繁体中文
    └── zh-Hans.json      # 简体中文
```

## WebSocket API

该集成公开两个 WebSocket 命令：

### `area_control/get_permitted_areas`
返回当前用户有权限访问的区域列表。

### `area_control/get_area_entities`
返回特定区域按域分组的实体。

## 更新日志

### v1.0.2
- 新增：紧凑水平域标签页，替代可折叠部分
- 新增：搜索栏，按名称或实体 ID 过滤
- 新增：传感器卡片 24 小时历史迷你图表
- 修复：统一卡片大小，防止长名称撑开

### v1.0.1
- 性能优化：区域实体并行加载
- 减少初始加载时的界面抖动

### v1.0.0
- 原生 HA 风格界面重新设计
- 域摘要仪表板 3x3 网格
- 域详情视图
- 带嵌入式控件的交互实体卡片

## 贡献

欢迎贡献！请随时提交 Pull Request。

## 许可证

本项目采用 MIT 许可证 - 详情请参阅 [LICENSE](LICENSE) 文件。

## 支持

如果您遇到任何问题或有功能请求，请[提交 Issue](https://github.com/WOOWTECH/Woow_ha_permission_control/issues)。

## 致谢

由 [WOOWTECH](https://github.com/WOOWTECH) 开发
