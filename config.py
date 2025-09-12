"""
配置文件，包含常量和默认配置
"""
import os
import json

def load_config(config_file='config.json'):
    """从JSON配置文件加载配置"""
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config
    except FileNotFoundError:
        # 如果配置文件不存在，使用默认配置
        print(f"配置文件 {config_file} 不存在，使用默认配置")
        return get_default_config()
    except json.JSONDecodeError:
        # 如果配置文件格式错误，使用默认配置
        print(f"配置文件 {config_file} 格式错误，使用默认配置")
        return get_default_config()

def get_default_config():
    """获取默认配置"""
    return {
        "default_headers": {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        },
        "download_config": {
            'max_workers': 10,
            'max_retries': 3,
            'retry_delay': 2,
            'max_concurrent_videos': 3,
            'max_workers_per_video': 10,
            'keep_segments': False,
            'abort_on_error': False
        },
        "ffmpeg_paths": [
            r"C:\Soft\ffmpeg\ffmpeg.exe",  # 用户指定的路径
            "ffmpeg"  # 系统PATH中的ffmpeg
        ],
        "temp_file_names": {
            "state_file": 'download_state.json',
            "file_list": 'file_list.txt'
        },
        "output_dir": os.path.join(os.getcwd(), 'downloads')
    }

# 加载配置
CONFIG = load_config()

# 导出配置项
DEFAULT_HEADERS = CONFIG['default_headers']
DEFAULT_DOWNLOAD_CONFIG = CONFIG['download_config']
FFMPEG_PATHS = CONFIG['ffmpeg_paths']
STATE_FILE_NAME = CONFIG['temp_file_names']['state_file']
FILE_LIST_NAME = CONFIG['temp_file_names']['file_list']
DEFAULT_OUTPUT_DIR = CONFIG['output_dir'] if not CONFIG['output_dir'].startswith('downloads') else os.path.join(os.getcwd(), CONFIG['output_dir'])