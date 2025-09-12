"""
数据模型模块
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any
from urllib.parse import urlparse

@dataclass
class DownloadResult:
    """下载结果数据类"""
    index: int
    url: str
    domain: str
    status: str
    error: Optional[str] = None
    output_dir: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    duration: float = 0.0

    def __post_init__(self):
        if not self.domain and self.url:
            self.domain = urlparse(self.url).netloc

@dataclass
class VideoInfo:
    """视频信息数据类"""
    url: str
    domain: str = "Unknown"
    headers: Optional[Dict[str, Any]] = None
    security_headers: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if not self.domain and self.url:
            self.domain = urlparse(self.url).netloc