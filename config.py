"""
配置文件，包含常量和默认配置
"""
import os

# 默认请求头
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}

# 默认下载配置
DEFAULT_DOWNLOAD_CONFIG = {
    'max_workers': 10,
    'max_retries': 3,
    'retry_delay': 2,
    'max_concurrent_videos': 3,
    'max_workers_per_video': 10
}

# ffmpeg路径配置
FFMPEG_PATHS = [
    r"C:\Soft\ffmpeg\ffmpeg.exe",  # 用户指定的路径
    "ffmpeg"  # 系统PATH中的ffmpeg
]

# 临时文件名
STATE_FILE_NAME = 'download_state.json'
FILE_LIST_NAME = 'file_list.txt'

# 输出目录
DEFAULT_OUTPUT_DIR = os.path.join(os.getcwd(), 'downloads')