# 配置文件使用说明

## 概述

本程序支持通过外部JSON配置文件来设置默认参数，这样可以在不重新编译程序的情况下修改配置。

## 配置文件结构

配置文件是一个JSON格式的文件，包含以下主要部分：

```json
{
  "default_headers": {
    "User-Agent": "Mozilla/5.0 ...",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9"
  },
  "download_config": {
    "max_workers": 10,
    "max_retries": 3,
    "retry_delay": 2,
    "max_concurrent_videos": 3,
    "max_workers_per_video": 10,
    "keep_segments": false,
    "abort_on_error": false
  },
  "ffmpeg_paths": [
    "C:\\Soft\\ffmpeg\\ffmpeg.exe",
    "ffmpeg"
  ],
  "temp_file_names": {
    "state_file": "download_state.json",
    "file_list": "file_list.txt"
  },
  "output_dir": "downloads"
}
```

## 配置项说明

### default_headers
- **User-Agent**: 默认的User-Agent请求头
- **Accept**: 默认的Accept请求头
- **Accept-Language**: 默认的Accept-Language请求头

### download_config
- **max_workers**: 每个视频下载时使用的最大线程数
- **max_retries**: 下载失败时的最大重试次数
- **retry_delay**: 重试间隔（秒）
- **max_concurrent_videos**: 批量下载时同时下载的视频数量
- **max_workers_per_video**: 每个视频的最大线程数
- **keep_segments**: 是否保留原始视频切片文件（默认：false）
- **abort_on_error**: 当有片段下载失败时是否终止程序（默认：false）

### ffmpeg_paths
- **ffmpeg_paths**: ffmpeg可执行文件的路径列表

### temp_file_names
- **state_file**: 下载状态文件名
- **file_list**: 文件列表名

### output_dir
- **output_dir**: 默认输出目录

## 使用方法

### 1. 使用默认配置文件
程序会自动加载同目录下的`config.json`文件作为默认配置。

### 2. 指定配置文件
可以通过命令行参数`--config`指定配置文件：

```bash
python main.py --config my_config.json [其他参数]
```

### 3. 命令行参数优先级
命令行参数的优先级高于配置文件中的设置。例如，如果配置文件中设置了`keep_segments: true`，但命令行中使用了`--keep-segments false`，则会使用命令行中的设置。

## 示例

### 示例配置文件 (config.json)
```json
{
  "default_headers": {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
  },
  "download_config": {
    "max_workers": 5,
    "keep_segments": true,
    "abort_on_error": true
  },
  "ffmpeg_paths": [
    "C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe",
    "ffmpeg"
  ],
  "output_dir": "my_videos"
}
```

使用此配置文件后，程序将：
- 使用指定的User-Agent
- 每个视频使用5个线程下载
- 默认保留原始视频切片文件
- 默认在遇到错误时终止程序
- 在my_videos目录中保存下载的视频