# 运行日志功能说明

## ✅ 日志保存机制已实现！

### 📁 日志文件位置

上位机的运行日志自动保存在程序目录下的 **`logs`** 文件夹中：

```
模型验证平台/
└── logs/
    └── platform_20260518.log    ← 今天的日志文件
```

### 📊 日志文件格式

- **文件名**: `platform_YYYYMMDD.log`（例如：`platform_20260518.log`）
- **编码**: UTF-8
- **轮转**: 单个文件超过10MB自动创建新文件
- **保留**: 自动保留最近30天的日志

---

## 🔍 三种查看日志的方法

### 方法1️⃣: 在程序中查看（推荐）

**步骤:**
1. 启动上位机程序 `python algorithm_platform.py`
2. 点击菜单栏 **"工具"** → **"查看运行日志"**
3. 弹出窗口显示今日日志，可以：
   - 🔄 实时刷新
   - 💾 导出为文件
   - 📋 复制内容

### 方法2️⃣: 直接打开文件

**步骤:**
1. 打开文件资源管理器
2. 进入 `c:\falcon\算法SDK\模型验证平台\logs` 文件夹
3. 双击当天的日志文件（如 `platform_20260518.log`）
4. 用记事本或其他文本编辑器查看

### 方法3️⃣: 命令行查看

```bash
# Windows PowerShell
cd "c:\falcon\算法SDK\模型验证平台"
Get-Content logs/platform_20260518.log -Tail 50

# 实时查看更新
Get-Content logs/platform_20260518.log -Wait -Tail 20
```

---

## 📝 日志内容示例

打开日志文件后，您会看到类似这样的内容：

```
2024-05-18 14:30:25 - AlgorithmValidationPlatform - INFO - [algorithm_platform.py:45] - ============================================================
2024-05-18 14:30:25 - AlgorithmValidationPlatform - INFO - [algorithm_platform.py:46] - 算法验证上位机平台启动
2024-05-18 14:30:25 - AlgorithmValidationPlatform - INFO - [algorithm_platform.py:47] - 启动时间: 2024-05-18 14:30:25
2024-05-18 14:30:25 - AlgorithmValidationPlatform - INFO - [algorithm_platform.py:48] - ============================================================
2024-05-18 14:31:15 - AlgorithmValidationPlatform - INFO - [algorithm_platform.py:535] - [DEVICE] 推送模型到 172.16.110.6: yolov5n.rknn
2024-05-18 14:31:20 - AlgorithmValidationPlatform - INFO - [device_manager.py:85] - 模型推送成功: /oem/usr/models/yolov5n.rknn
2024-05-18 14:32:05 - AlgorithmValidationPlatform - INFO - [OPERATION] 开始性能监控: 采样间隔2秒
```

---

## 📊 记录的信息类型

### ✅ 已记录的完整信息

| 类别 | 记录内容 | 示例 |
|------|----------|------|
| **程序启动** | 启动时间、版本信息 | `算法验证上位机平台启动` |
| **用户操作** | 所有按钮点击、文件选择 | `[OPERATION] 浏览模型文件` |
| **设备交互** | SSH连接、文件传输 | `[DEVICE] 推送模型到 172.16.110.6` |
| **性能数据** | NPU/CPU/内存占用（DEBUG级） | `[PERFORMANCE] NPU: 45.2%, CPU: 32.1%` |
| **错误异常** | 所有错误详情 | `[ERROR] 连接失败: timeout` |
| **配置变更** | 参数修改、配置推送 | `[OPERATION] 推送配置文件` |

### 🔍 日志级别说明

- **DEBUG**: 详细调试信息（性能采样等）
- **INFO**: 普通信息（用户操作、设备交互）
- **WARNING**: 警告信息（非致命问题）
- **ERROR**: 错误信息（操作失败）
- **CRITICAL**: 严重错误（程序崩溃）

---

## 🎯 实用技巧

### 快速定位问题

在日志文件中搜索关键字：
- `[ERROR]` → 查找所有错误
- `[OPERATION]` → 查看用户操作历史
- `[DEVICE]` → 查看设备交互记录
- `[PERFORMANCE]` → 分析性能数据

### 追踪操作流程

每个重要操作都有完整的开始和结束记录：
```
[OPERATION] 开始推送模型...
  ↓
[DEVICE] 建立SSH连接到 172.16.110.6
  ↓
[DEVICE] 传输文件: yolov5n.rknn (25.8MB)
  ↓
[OPERATION] 模型推送成功！
```

### 性能数据分析

DEBUG级别记录了所有性能采样点：
```
[PERFORMANCE] NPU: 45.2%, CPU: 32.1%, MEM: 67.8%
[PERFORMANCE] NPU: 46.1%, CPU: 33.5%, MEM: 68.2%
[PERFORMANCE] NPU: 47.8%, CPU: 35.2%, MEM: 69.1%
```

---

## ⚙️ 自定义配置（可选）

### 修改日志文件大小限制

编辑 `log_manager.py` 第45行：

```python
maxBytes=10*1024*1024,  # 10MB → 改为20MB: 20*1024*1024
```

### 修改日志保留天数

编辑 `log_manager.py` 第46行：

```python
backupCount=30,  # 30天 → 改为60天: backupCount=60
```

### 修改控制台显示级别

编辑 `log_manager.py` 第52行：

```python
console_handler.setLevel(logging.WARNING)  # 改为DEBUG可显示更多信息
```

---

## 🧪 测试日志功能

运行测试脚本验证日志功能是否正常：

```bash
python test_log.py
```

应该看到：
- ✓ Basic logging OK
- ✓ Special logging OK
- ✓ Log directory exists
- ✓ Log exported successfully

---

## 📖 更多详细信息

完整的日志使用说明请参考：**LOG_GUIDE.md**

---

## ✨ 总结

### ✅ 已实现的功能

1. ✅ **自动日志记录** - 所有操作自动记录到文件
2. ✅ **按日期分割** - 每天生成新的日志文件
3. ✅ **智能轮转** - 超过10MB自动创建新文件
4. ✅ **自动清理** - 保留最近30天日志
5. ✅ **GUI查看器** - 在程序中直接查看日志
6. ✅ **导出功能** - 支持导出为独立文件
7. ✅ **多级日志** - DEBUG/INFO/WARNING/ERROR/CRITICAL

### 🎯 使用方式

- **查看今日日志**: 工具菜单 → 查看运行日志
- **手动查看**: 打开 `logs/platform_YYYYMMDD.log`
- **命令行查看**: `Get-Content logs/platform_20260518.log -Tail 50`

---

**日志功能已完全就绪！可以放心使用上位机程序了！** 🎉
