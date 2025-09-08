# M3U8批量下载器 - 功能扩展说明

## 概述

本次扩展为HLSDownload项目添加了批量下载功能，使其能够处理Chrome扩展导出的请求记录，支持并行下载多个M3U8视频并完成后续的片段下载和合并操作。

## 新增功能

### 1. 批量下载器类 (BatchM3U8Downloader)

- **功能**: 处理Chrome扩展导出的JSON文件，实现批量视频下载
- **特性**:
  - 支持解析Chrome扩展导出的JSON格式
  - 自动应用扩展收集的请求头信息，提高下载成功率
  - 支持AES-128加密视频的自动解密
  - 智能错误处理和重试机制

### 2. 并行下载配置

- **并发视频数**: 可配置同时下载的视频数量 (`--max-concurrent`, 默认3个)
- **线程数控制**: 可配置每个视频的最大线程数 (`--max-workers`, 默认10个)
- **性能优化**: 通过合理的并发控制，既提高效率又避免系统资源过载

### 3. 增强的状态管理

- **实时进度显示**: 显示总体下载进度、成功/失败统计
- **详细错误报告**: 记录每个视频的下载状态和错误信息
- **下载报告**: 自动生成JSON格式的详细下载报告

### 4. 命令行接口扩展

原有的单个视频下载功能完全保留，新增批量下载模式：

```bash
# 单个视频下载 (保留原功能)
python m3u8_downloader.py https://example.com/video.m3u8

# 批量下载 (新功能)
python m3u8_downloader.py --batch m3u8_links.json --max-concurrent 5
```

## 使用流程

### 1. 使用Chrome扩展收集M3U8链接

1. 安装并启用Chrome扩展
2. 访问包含视频的网页
3. 扩展自动监控和捕获M3U8链接
4. 导出链接为JSON文件

### 2. 批量下载视频

```bash
# 基本批量下载
python m3u8_downloader.py --batch exported_links.json

# 高级配置
python m3u8_downloader.py --batch exported_links.json \
    --max-concurrent 5 \
    --max-workers 8 \
    --keep-segments
```

### 3. 查看下载结果

- 视频文件保存在 `downloads/` 目录下的各个子文件夹中
- 下载报告保存为 `download_report_YYYYMMDD_HHMMSS.json`

## JSON文件格式

Chrome扩展导出的JSON文件包含以下结构：

```json
{
  "timestamp": "2025-01-05T10:30:00.000Z",
  "count": 2,
  "links": [
    {
      "url": "https://example.com/video.m3u8",
      "domain": "example.com",
      "timestamp": 1704454200000,
      "source": "Network Monitor (Verified)",
      "method": "GET",
      "pageUrl": "https://example.com/page",
      "pageTitle": "视频标题",
      "headers": {
        "userAgent": "Mozilla/5.0...",
        "referer": "https://example.com/page",
        "origin": "https://example.com",
        "cookie": "session=abc123"
      },
      "securityHeaders": {
        "secFetchSite": "same-origin",
        "secFetchMode": "cors",
        "secFetchDest": "empty"
      }
    }
  ]
}
```

## 命令行参数

### 基本参数
- `--batch [JSON_FILE]`: 启用批量下载模式
- `-h, --help`: 显示帮助信息

### 性能配置
- `--max-concurrent N`: 同时下载的视频数量 (默认: 3)
- `--max-workers N`: 每个视频的最大线程数 (默认: 10)

### 下载控制
- `-k, --keep-segments`: 保留原始视频切片文件
- `-a, --abort-on-error`: 当有片段下载失败时终止程序
- `--test-mode`: 启用测试模式（模拟部分片段下载失败）

## 核心优势

### 1. 高成功率
- 自动应用Chrome扩展收集的真实浏览器请求头
- 包括User-Agent、Referer、Origin、Cookie等关键信息
- 支持现代浏览器安全头 (Sec-Fetch-*)

### 2. 高效率
- 支持多视频并行下载
- 每个视频内部多线程下载片段
- 智能断点续传机制

### 3. 可靠性
- 详细的错误处理和重试机制
- 自动处理加密视频 (AES-128)
- 完整的下载状态跟踪

### 4. 易用性
- 简单的命令行接口
- 详细的进度显示
- 完整的下载报告

## 技术实现亮点

### 1. 请求头复用
自动提取并应用Chrome扩展收集的请求头信息：

```python
enhanced_headers = {
    'User-Agent': headers.get('userAgent', '...'),
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Referer': headers.get('referer', ''),
    'Origin': headers.get('origin', ''),
    'Cookie': headers.get('cookie', ''),
    'Sec-Fetch-Site': sec_headers.get('secFetchSite', 'same-origin'),
    'Sec-Fetch-Mode': sec_headers.get('secFetchMode', 'cors'),
    'Sec-Fetch-Dest': sec_headers.get('secFetchDest', 'empty')
}
```

### 2. 并发控制
使用ThreadPoolExecutor实现多级并发控制：

```python
# 视频级并发
with ThreadPoolExecutor(max_workers=self.max_concurrent_videos) as executor:
    # 片段级并发 (在每个M3U8Downloader实例中)
    with ThreadPoolExecutor(max_workers=self.max_workers_per_video) as seg_executor:
```

### 3. 状态管理
实时跟踪下载状态并提供详细反馈：

```python
result = {
    'index': index,
    'url': url,
    'domain': domain,
    'status': 'pending',  # pending -> completed/failed
    'error': None,
    'output_dir': None,
    'start_time': None,
    'end_time': None,
    'duration': 0
}
```

## 兼容性

- **向后兼容**: 完全保留原有的单个视频下载功能
- **扩展兼容**: 与现有Chrome扩展完美集成
- **环境要求**: 
  - Python 3.x
  - ffmpeg (用于视频合并)
  - 现有依赖包: requests, cryptography

## 测试验证

项目包含完整的测试文件和示例：

1. `test_m3u8_batch.json`: 测试用的JSON文件
2. `batch_download_example.py`: 使用示例和演示脚本
3. 完整的命令行测试验证

通过测试验证了以下功能：
- ✅ JSON文件解析
- ✅ 批量下载流程
- ✅ 并发控制
- ✅ 错误处理
- ✅ 进度显示
- ✅ 报告生成

## 总结

本次扩展成功实现了您的需求：

1. **处理Chrome扩展数据**: 支持导入Chrome扩展的请求记录
2. **复制请求下载**: 自动应用扩展收集的请求头信息
3. **批量处理**: 支持同时处理多个视频清单
4. **并行配置**: 可配置同时下载的文件数量
5. **完整流程**: 从解析到下载、合并的完整自动化流程

扩展后的程序既保持了原有功能的完整性，又大大增强了批量处理能力，为用户提供了更高效、更可靠的M3U8视频下载解决方案。