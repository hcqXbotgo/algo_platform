# 运行日志说明文档

## 📋 日志保存机制

### 1. 日志文件位置

上位机的运行日志保存在程序目录下的 `logs` 文件夹中：

```
模型验证平台/
└── logs/
    ├── platform_20240515.log    # 今天的日志
    ├── platform_20240514.log    # 昨天的日志
    └── ...
```

### 2. 日志文件命名规则

- **文件名格式**: `platform_YYYYMMDD.log`
- **按日期分割**: 每天生成一个新的日志文件
- **自动清理**: 保留最近30天的日志，超过的自动删除

### 3. 日志文件大小限制

- **单个文件最大**: 10 MB
- **备份数量**: 最多30个备份文件
- **轮转策略**: 当日志超过10MB时，自动创建新文件

---

## 📊 日志内容示例

### 日志格式
```
2024-05-15 14:30:25 - AlgorithmValidationPlatform - INFO - [algorithm_platform.py:45] - ============================================================
2024-05-15 14:30:25 - AlgorithmValidationPlatform - INFO - [algorithm_platform.py:46] - 算法验证上位机平台启动
2024-05-15 14:30:25 - AlgorithmValidationPlatform - INFO - [algorithm_platform.py:47] - 启动时间: 2024-05-15 14:30:25
2024-05-15 14:30:25 - AlgorithmValidationPlatform - INFO - [algorithm_platform.py:48] - ============================================================
2024-05-15 14:30:45 - AlgorithmValidationPlatform - INFO - [algorithm_platform.py:520] - [OPERATION] 浏览模型文件: C:/models/yolov5n.rknn
2024-05-15 14:30:50 - AlgorithmValidationPlatform - INFO - [algorithm_platform.py:535] - [DEVICE] 推送模型到 172.16.110.6: yolov5n.rknn
2024-05-15 14:31:15 - AlgorithmValidationPlatform - INFO - [device_manager.py:85] - 模型推送成功: /oem/usr/models/yolov5n.rknn
```

### 日志级别说明

| 级别 | 说明 | 何时使用 |
|------|------|----------|
| DEBUG | 调试信息 | 详细的处理过程、性能数据采样 |
| INFO | 普通信息 | 用户操作、设备交互、系统事件 |
| WARNING | 警告信息 | 非致命问题，不影响程序运行 |
| ERROR | 错误信息 | 操作失败、异常发生 |
| CRITICAL | 严重错误 | 导致程序无法继续运行的错误 |

---

## 🔍 如何查看日志

### 方法1：直接打开日志文件

1. 打开文件资源管理器
2. 进入 `logs` 文件夹
3. 双击当天的日志文件（例如：`platform_20240515.log`）
4. 使用记事本或其他文本编辑器查看

### 方法2：在程序中查看（推荐）

**步骤：**
1. 启动上位机程序
2. 点击菜单栏 **"工具"** → **"查看运行日志"**
3. 在弹出的窗口中可以：
   - 📖 查看实时日志
   - 🔄 刷新日志内容
   - 💾 导出日志到指定位置
   - 🗑️ 清空显示

### 方法3：使用命令行查看

```bash
# Windows PowerShell
Get-Content logs/platform_20240515.log -Tail 50

# Linux/Mac
tail -f logs/platform_20240515.log
```

---

## 📝 记录的内容包括

### 1. 程序启动和关闭
- ✅ 启动时间
- ✅ Python版本
- ✅ 依赖模块加载状态

### 2. 用户操作记录
- ✅ 模型文件选择和推送
- ✅ 配置文件修改
- ✅ 性能监控启停
- ✅ 日志分析操作
- ✅ RTSP连接操作
- ✅ MQTT控制指令发送

### 3. 设备交互
- ✅ SSH连接状态
- ✅ 文件传输进度
- ✅ 进程控制命令
- ✅ WiFi配置操作

### 4. 性能数据
- ✅ NPU/CPU/内存采样数据（DEBUG级别）
- ✅ DDR带宽数据
- ✅ 网络延迟信息

### 5. 错误和异常
- ✅ 网络连接失败
- ✅ 文件传输错误
- ✅ 设备响应超时
- ✅ 参数配置错误

---

## 💡 实用技巧

### 技巧1：快速定位问题

在日志文件中搜索关键字：
- `[ERROR]` - 查找所有错误
- `[OPERATION]` - 查找用户操作
- `[DEVICE]` - 查找设备交互
- `[PERFORMANCE]` - 查找性能数据

### 技巧2：追踪完整操作流程

每个操作都有开始和结束标记：
```
[OPERATION] 开始推送模型...
[DEVICE] 连接到 172.16.110.6
[DEVICE] 传输文件...
[OPERATION] 模型推送成功！
```

### 技巧3：性能数据分析

DEBUG级别记录了所有性能采样：
```
[PERFORMANCE] NPU: 45.2%, CPU: 32.1%, MEM: 67.8%
[PERFORMANCE] NPU: 46.1%, CPU: 33.5%, MEM: 68.2%
```

### 技巧4：导出日志用于分析

1. 在日志查看器中点击"导出日志"
2. 选择保存位置
3. 可以将日志分享给技术支持团队

---

## 🔧 自定义日志配置

### 修改日志级别

编辑 `log_manager.py` 中的配置：

```python
# 文件日志级别（默认DEBUG，记录所有信息）
file_handler.setLevel(logging.DEBUG)

# 控制台日志级别（默认WARNING，只显示重要信息）
console_handler.setLevel(logging.WARNING)
```

### 修改日志文件大小限制

```python
# 修改maxBytes参数（单位：字节）
maxBytes=10*1024*1024,  # 10MB → 改为20MB: 20*1024*1024
```

### 修改日志保留天数

```python
# 修改backupCount参数
backupCount=30,  # 30天 → 改为60天: backupCount=60
```

---

## 🚨 常见问题

### Q1: 找不到logs文件夹？
**A**: logs文件夹会在首次写入日志时自动创建。如果没看到，请先运行一次程序。

### Q2: 日志文件太大怎么办？
**A**: 系统会自动轮转，超过10MB会创建新文件。也可以手动删除旧日志。

### Q3: 如何查看历史日志？
**A**: logs文件夹中保留了所有历史日志文件，按日期命名，直接打开即可查看。

### Q4: 可以禁用日志记录吗？
**A**: 不建议禁用，但可以调整日志级别。将file_handler改为logging.WARNING可以减少记录量。

### Q5: 日志会影响程序性能吗？
**A**: 几乎不会。日志写入采用异步方式，对性能影响微乎其微（<1%）。

---

## 📈 日志分析示例

### 查看某次模型推送的完整过程

```bash
# 搜索特定操作的日志
grep "推送模型" logs/platform_20240515.log
```

### 统计错误数量

```bash
# Windows PowerShell
Select-String -Path logs/platform_20240515.log -Pattern "ERROR" | Measure-Object

# Linux/Mac
grep -c "ERROR" logs/platform_20240515.log
```

### 提取性能数据

```python
# 使用Python分析性能数据
import re
with open('logs/platform_20240515.log', 'r') as f:
    for line in f:
        if '[PERFORMANCE]' in line:
            # 提取NPU/CPU/MEM数据
            match = re.search(r'NPU: ([\d.]+)%, CPU: ([\d.]+)%, MEM: ([\d.]+)%', line)
            if match:
                npu, cpu, mem = match.groups()
                # 处理数据...
```

---

## 🎯 最佳实践

1. **定期备份重要日志** - 在进行重要操作前，备份当前日志
2. **遇到问题立即保存** - 出现错误时，立即导出日志
3. **添加操作备注** - 在关键操作前，记录说明信息
4. **使用合适的日志级别** - 开发时用DEBUG，生产环境用INFO
5. **定期检查日志** - 每周检查日志，发现潜在问题

---

## 📞 技术支持

如需技术支持，请：
1. 导出问题发生时的日志
2. 记录操作步骤
3. 截图错误提示
4. 联系开发团队

---

**更新日期**: 2024-05-15  
**版本**: v1.0
