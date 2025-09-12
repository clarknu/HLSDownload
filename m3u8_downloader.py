#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M3U8视频下载器 (向后兼容版本)
"""

import os
import re
import sys
import hashlib
import json
import requests
import time
import subprocess
import shutil
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urljoin
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

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

class M3U8Downloader:
    def __init__(self, m3u8_url, max_workers=10, max_retries=3, retry_delay=2, test_mode=False, custom_headers=None):
        self.m3u8_url = m3u8_url
        self.max_workers = max_workers
        self.max_retries = max_retries  # 最大重试次数
        self.retry_delay = retry_delay  # 重试间隔（秒）
        self.custom_headers = custom_headers or {}
        self.temp_dir = self._create_temp_dir()
        self.segments = []
        self.total_size = 0
        self.success_count = 0
        self.fail_count = 0
        self.retry_count = 0  # 重试次数统计
        self.start_time = None
        self.base_url = self._get_base_url()
        # 解密相关属性
        self.is_encrypted = False
        self.key_url = None
        self.key = None
        self.iv = None
        # 测试模式：用于模拟部分片段下载失败
        self.test_mode = test_mode
        # 断点续传相关
        self.state_file = os.path.join(self.temp_dir, STATE_FILE_NAME)
        self.downloaded_segments = set()  # 已成功下载的片段索引
        self.failed_segments = set()     # 下载失败的片段索引
        self._load_download_state()

    def _get_headers(self):
        """获取请求头"""
        headers = DEFAULT_HEADERS.copy()
        headers.update(self.custom_headers)
        headers['Referer'] = self.base_url
        return headers

    def _create_temp_dir(self):
        # 计算URL的哈希值作为目录名
        url_hash = hashlib.md5(self.m3u8_url.encode()).hexdigest()
        temp_dir = os.path.join(os.getcwd(), url_hash)
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
        return temp_dir

    def _get_base_url(self):
        parsed_url = urlparse(self.m3u8_url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        path_parts = parsed_url.path.split('/')[:-1]
        if path_parts:
            base_url += '/'.join(path_parts) + '/'
        else:
            base_url += '/'
        return base_url

    def _download_m3u8(self):
        try:
            # 添加浏览器请求头，避免403错误
            headers = self._get_headers()
            
            response = requests.get(self.m3u8_url, headers=headers, timeout=30)
            response.raise_for_status()
            m3u8_content = response.text
            
            # 检查是否为加密的m3u8文件
            if '#EXT-X-KEY' in m3u8_content:
                self.is_encrypted = True
                print("检测到加密的m3u8文件，正在解析密钥信息...")
                
                # 解析密钥URL
                key_match = re.search(r'#EXT-X-KEY:METHOD=AES-128,URI="(.*?)"', m3u8_content)
                if key_match:
                    self.key_url = key_match.group(1)
                    # 确保密钥URL是完整的
                    if not self.key_url.startswith('http'):
                        self.key_url = urljoin(self.m3u8_url, self.key_url)
                    
                    # 下载密钥，添加请求头避免403错误
                    print(f"正在下载密钥: {self.key_url}")
                    key_headers = self._get_headers()
                    key_response = requests.get(self.key_url, headers=key_headers, timeout=30)
                    key_response.raise_for_status()
                    self.key = key_response.content
                    
                    # 解析IV（初始化向量）
                    iv_match = re.search(r'IV=(.*?)(?:,|\r|\n)', m3u8_content)
                    if iv_match:
                        iv_hex = iv_match.group(1)
                        if iv_hex.startswith('0x'):
                            iv_hex = iv_hex[2:]
                        self.iv = bytes.fromhex(iv_hex)
                    else:
                        # 如果没有指定IV，使用默认的IV（通常是片段的序号）
                        self.iv = None
                    
                    print("密钥解析成功")
                else:
                    print("无法解析密钥信息")
                    return False
            
            # 解析m3u8文件，获取所有ts片段的URL
            # 改进正则表达式，更精确地匹配真正的TS片段URL（不包含#开头的行，且是独立的.ts文件）
            ts_pattern = re.compile(r'^(?!#)[^\n]*\.ts\s*$', re.MULTILINE)
            self.segments = ts_pattern.findall(m3u8_content)
            
            # 清理URL中的换行符和空白字符
            self.segments = [segment.strip().replace('\n', '').replace('\r', '') for segment in self.segments]
            
            if not self.segments:
                print("未找到ts片段")
                return False
            
            print(f"找到 {len(self.segments)} 个ts片段")
            return True
        except Exception as e:
            print(f"下载m3u8文件失败: {e}")
            return False

    def _download_segment(self, segment_url, index):
        retries = 0
        success = False
        last_error = None
        
        # 检查文件是否已存在且完整
        segment_path = os.path.join(self.temp_dir, f"segment_{index:05d}.ts")
        if os.path.exists(segment_path) and os.path.getsize(segment_path) > 0:
            print(f"\n片段 {index} 已存在且完整，跳过下载")
            self.downloaded_segments.add(index)
            self.success_count += 1
            return
        
        # 测试模式：模拟部分片段下载失败（每5个片段中让第3个和第5个失败）
        if self.test_mode and (index % 5 == 2 or index % 5 == 4):
            self.fail_count += 1
            self.failed_segments.add(index)
            # 清理失败片段的本地文件
            segment_path = os.path.join(self.temp_dir, f"segment_{index:05d}.ts")
            if os.path.exists(segment_path):
                os.remove(segment_path)
            print(f"\n测试模式: 模拟片段 {index} 下载失败")
            self._save_download_state()
            return
        
        # 确保URL是完整的
        if not segment_url.startswith('http'):
            if segment_url.startswith('/'):
                parsed_url = urlparse(self.m3u8_url)
                segment_url = f"{parsed_url.scheme}://{parsed_url.netloc}{segment_url}"
            else:
                segment_url = f"{self.base_url}{segment_url}"
        
        # 添加浏览器请求头
        headers = self._get_headers()
        
        # 下载和重试逻辑
        while retries <= self.max_retries and not success:
            try:
                # 如果是重试，打印重试信息
                if retries > 0:
                    self.retry_count += 1
                    print(f"\n重试下载片段 {index} (第{retries}次/{self.max_retries}次)")
                    # 等待指定的重试间隔
                    time.sleep(self.retry_delay)
                
                # 下载ts片段
                response = requests.get(segment_url, headers=headers, stream=True, timeout=60)
                response.raise_for_status()
                
                # 保存文件
                file_path = os.path.join(self.temp_dir, f"segment_{index:05d}.ts")
                
                # 检查是否需要解密
                if self.is_encrypted and self.key:
                    # 读取加密数据
                    encrypted_data = response.content
                    
                    # 设置IV（如果未指定，使用片段序号）
                    if self.iv is None:
                        # 通常IV是16字节的，这里使用index的16字节表示
                        iv = index.to_bytes(16, byteorder='big')
                    else:
                        iv = self.iv
                    
                    # 创建解密器
                    cipher = Cipher(algorithms.AES(self.key), modes.CBC(iv), backend=default_backend())
                    decryptor = cipher.decryptor()
                    
                    # 解密数据
                    decrypted_data = decryptor.update(encrypted_data) + decryptor.finalize()
                    
                    # 保存解密后的数据
                    with open(file_path, 'wb') as f:
                        f.write(decrypted_data)
                    
                    self.total_size += len(decrypted_data)
                else:
                    # 直接保存未加密的数据
                    with open(file_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                self.total_size += len(chunk)
                
                self.success_count += 1
                success = True
                self.downloaded_segments.add(index)
                self.failed_segments.discard(index)
                
                # 显示下载进度
                if self.start_time is not None:
                    elapsed_time = time.time() - self.start_time
                    speed = self.total_size / elapsed_time if elapsed_time > 0 else 0
                else:
                    elapsed_time = 0
                    speed = 0
                progress = (self.success_count + self.fail_count) / len(self.segments) * 100
                
                sys.stdout.write(f"\r下载进度: {progress:.2f}% | 成功: {self.success_count} | 失败: {self.fail_count} | 重试: {self.retry_count} | 速度: {speed/1024/1024:.2f} MB/s")
                sys.stdout.flush()
                
            except Exception as e:
                last_error = e
                retries += 1
        
        # 如果所有重试都失败
        if not success:
            self.fail_count += 1
            self.failed_segments.add(index)
            # 清理失败片段的本地文件
            segment_path = os.path.join(self.temp_dir, f"segment_{index:05d}.ts")
            if os.path.exists(segment_path):
                os.remove(segment_path)
            print(f"\n下载片段 {index} 失败 (已尝试{retries-1}次): {last_error}")
            
        # 保存下载状态
        self._save_download_state()

    def download_all_segments(self):
        # 重新初始化计数器，确保准确
        self.success_count = 0
        self.fail_count = 0
        self.retry_count = 0
        
        # 计算需要下载的片段数量
        segments_to_download = []
        for i, segment in enumerate(self.segments):
            segment_path = os.path.join(self.temp_dir, f"segment_{i:05d}.ts")
            if not os.path.exists(segment_path) or os.path.getsize(segment_path) == 0 or i in self.failed_segments:
                segments_to_download.append((segment, i))
            else:
                # 文件存在且不为空，视为下载成功
                self.success_count += 1
        
        # 如果所有片段都已下载完成且没有失败片段
        if not segments_to_download and self.fail_count == 0:
            print(f"所有 {len(self.segments)} 个ts片段已下载完成，无需重新下载")
            return True
        
        # 显示需要下载的片段信息
        print(f"开始下载 {len(segments_to_download)} 个ts片段到 {self.temp_dir}")
        if len(self.segments) > len(segments_to_download):
            print(f"跳过 {len(self.segments) - len(segments_to_download)} 个已成功下载的片段")
        
        # 如果有失败片段，显示相关信息
        if self.failed_segments:
            print(f"发现 {len(self.failed_segments)} 个标记为失败的片段，将重新下载")
            # 清理失败片段的本地文件
            for i in self.failed_segments:
                segment_path = os.path.join(self.temp_dir, f"segment_{i:05d}.ts")
                if os.path.exists(segment_path):
                    os.remove(segment_path)
                    print(f"已删除失败片段文件: segment_{i:05d}.ts")
        
        self.start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for segment, i in segments_to_download:
                executor.submit(self._download_segment, segment, i)
        
        print("\n所有片段下载完成")
        
        if self.retry_count > 0:
            print(f"重试统计: 共尝试重试 {self.retry_count} 次")
            
        if self.fail_count > 0:
            print(f"注意: 有 {self.fail_count} 个片段下载失败 (已重试所有可能)")
        
        return self.fail_count == 0

    def merge_segments(self, output_filename=None, output_dir=None):
        """合并视频片段"""
        # 默认输出文件名，生成更具唯一性的文件名
        if not output_filename:
            parsed_url = urlparse(self.m3u8_url)
            domain = parsed_url.netloc.replace('.', '_')  # 将域名中的点替换为下划线
            timestamp = time.strftime('%Y%m%d_%H%M%S')  # 添加时间戳
            random_str = hashlib.md5(self.m3u8_url.encode()).hexdigest()[:8]  # 基于URL生成随机字符串
            output_filename = f"{domain}_{timestamp}_{random_str}.mp4"
        
        # 确定输出路径
        if output_dir:
            # 确保输出目录存在
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, output_filename)
        else:
            output_path = os.path.join(self.temp_dir, output_filename)
        
        # 优先检查预设的ffmpeg路径
        ffmpeg_path = None
        for path in FFMPEG_PATHS:
            if path == "ffmpeg":
                # 使用shutil.which检查PATH中的ffmpeg
                found_path = shutil.which('ffmpeg')
                if found_path:
                    ffmpeg_path = found_path
                    print(f"找到系统PATH中的ffmpeg: {ffmpeg_path}")
                    break
            else:
                # 检查具体路径
                if os.path.exists(path):
                    ffmpeg_path = path
                    print(f"找到预设路径的ffmpeg: {ffmpeg_path}")
                    break
        
        if not ffmpeg_path:
            print("未找到ffmpeg，请先安装ffmpeg")
            print("Windows用户可以从https://ffmpeg.org/download.html下载，并将bin目录添加到环境变量")
            print("或者确保ffmpeg.exe位于 C:\\Soft\\ffmpeg\\ 目录下")
            
            # 询问用户是否要手动指定ffmpeg路径
            choice = input("是否要手动指定ffmpeg的路径？(y/n): ").lower()
            if choice == 'y':
                ffmpeg_path = input("请输入ffmpeg可执行文件的完整路径: ").strip()
                if not os.path.exists(ffmpeg_path):
                    print(f"指定的路径不存在: {ffmpeg_path}")
                    return False
            else:
                # 如果用户不想指定ffmpeg路径，提供手动合并的方法
                print("\n您可以稍后手动合并视频片段。合并方法：")
                print(f"1. 安装ffmpeg")
                print(f"2. 打开命令行，切换到目录: {self.temp_dir}")
                print(f"3. 运行命令: ffmpeg -f concat -safe 0 -i {FILE_LIST_NAME} -c copy {output_filename}")
                return False
        
        # 创建文件列表
        file_list_path = os.path.join(self.temp_dir, FILE_LIST_NAME)
        with open(file_list_path, 'w', encoding='utf-8') as f:
            for i in range(len(self.segments)):
                segment_path = os.path.join(self.temp_dir, f"segment_{i:05d}.ts")
                if os.path.exists(segment_path):
                    f.write(f"file '{segment_path}'\n")
        
        print(f"开始合并视频片段到 {output_path}")
        
        # 使用ffmpeg合并视频
        try:
            # 添加-y参数自动覆盖已存在的文件，无需用户确认
            # 不捕获输出，让ffmpeg的输出直接显示在终端中
            subprocess.run(
                [ffmpeg_path, '-y', '-f', 'concat', '-safe', '0', '-i', file_list_path, '-c', 'copy', output_path],
                check=True
            )
            print("视频合并成功")
            return True
        except subprocess.CalledProcessError:
            print("视频合并失败")
            return False

    def _load_download_state(self):
        """加载之前的下载状态"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                    self.downloaded_segments = set(state.get('downloaded_segments', []))
                    self.failed_segments = set(state.get('failed_segments', []))
                    
                    # 检查哪些已下载的文件可能丢失了
                    current_downloaded = set()
                    for i in self.downloaded_segments:
                        segment_path = os.path.join(self.temp_dir, f"segment_{i:05d}.ts")
                        if os.path.exists(segment_path) and os.path.getsize(segment_path) > 0:
                            current_downloaded.add(i)
                        else:
                            # 文件已丢失，需要重新下载
                            self.failed_segments.add(i)
                    
                    self.downloaded_segments = current_downloaded
                    print(f"加载下载状态成功: 已下载 {len(self.downloaded_segments)} 个片段，失败 {len(self.failed_segments)} 个片段")
            except Exception as e:
                print(f"加载下载状态失败: {e}")
                self.downloaded_segments = set()
                self.failed_segments = set()
    
    def _save_download_state(self):
        """保存当前的下载状态"""
        try:
            state = {
                'downloaded_segments': list(self.downloaded_segments),
                'failed_segments': list(self.failed_segments),
                'last_update_time': time.time()
            }
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存下载状态失败: {e}")
    
    def cleanup(self):
        # 删除临时文件，但保留最终视频
        try:
            for i in range(len(self.segments)):
                segment_path = os.path.join(self.temp_dir, f"segment_{i:05d}.ts")
                if os.path.exists(segment_path):
                    os.remove(segment_path)
            
            file_list_path = os.path.join(self.temp_dir, FILE_LIST_NAME)
            if os.path.exists(file_list_path):
                os.remove(file_list_path)
            
            # 清理下载状态文件
            if os.path.exists(self.state_file):
                os.remove(self.state_file)
            
            print("临时文件清理完成")
        except Exception as e:
            print(f"清理临时文件失败: {e}")

class BatchM3U8Downloader:
    """
    批量M3U8下载器类
    支持处理Chrome扩展导出的JSON文件，实现批量下载和并行处理
    """
    
    def __init__(self, json_file_path, max_concurrent_videos=3, max_workers_per_video=10, output_base_dir=None, custom_headers=None):
        """
        初始化批量下载器
        
        Args:
            json_file_path: Chrome扩展导出的JSON文件路径
            max_concurrent_videos: 同时下载的视频数量
            max_workers_per_video: 每个视频的最大线程数
            output_base_dir: 输出目录，默认为当前目录下的downloads文件夹
            custom_headers: 自定义请求头
        """
        self.json_file_path = json_file_path
        self.max_concurrent_videos = max_concurrent_videos
        self.max_workers_per_video = max_workers_per_video
        self.custom_headers = custom_headers or {}
        self.video_list = []
        self.download_results = []
        self.start_time = None
        self.lock = threading.Lock()
        
        # 设置输出目录
        if output_base_dir is None:
            self.output_base_dir = DEFAULT_OUTPUT_DIR
        else:
            self.output_base_dir = output_base_dir
            
        if not os.path.exists(self.output_base_dir):
            os.makedirs(self.output_base_dir)
            
        # 状态统计
        self.total_videos = 0
        self.completed_videos = 0
        self.failed_videos = 0
        self.skipped_videos = 0
        
        print(f"批量下载器初始化完成")
        print(f"输出目录: {self.output_base_dir}")
        print(f"最大并发视频数: {max_concurrent_videos}")
        print(f"每个视频的最大线程数: {max_workers_per_video}")
    
    def load_json_file(self):
        """
        加载Chrome扩展导出的JSON文件
        """
        try:
            if not os.path.exists(self.json_file_path):
                print(f"错误: JSON文件不存在: {self.json_file_path}")
                return False
                
            with open(self.json_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 解析JSON数据结构
            if 'links' in data and isinstance(data['links'], list):
                self.video_list = data['links']
            elif isinstance(data, list):
                # 如果直接是链接列表
                self.video_list = data
            else:
                print("错误: JSON文件格式不正确")
                return False
            
            self.total_videos = len(self.video_list)
            print(f"成功加载 {self.total_videos} 个M3U8链接")
            
            # 显示加载的链接概览
            for i, video_info in enumerate(self.video_list[:5]):
                url = video_info.get('url', '') if isinstance(video_info, dict) else str(video_info)
                domain = video_info.get('domain', 'Unknown') if isinstance(video_info, dict) else urlparse(url).netloc
                print(f"  {i+1}. {domain} - {url[:60]}...")
                
            if self.total_videos > 5:
                print(f"  ... 还有 {self.total_videos - 5} 个链接")
                
            return True
            
        except json.JSONDecodeError as e:
            print(f"错误: JSON文件格式错误: {e}")
            return False
        except Exception as e:
            print(f"错误: 读取JSON文件失败: {e}")
            return False
    
    def _create_enhanced_downloader(self, video_info):
        """
        根据Chrome扩展提供的信息创建增强的下载器实例
        """
        if isinstance(video_info, dict):
            m3u8_url = video_info.get('url', '')
            
            # 应用Chrome扩展收集的请求头信息
            enhanced_headers = self.custom_headers.copy()
            if 'headers' in video_info:
                headers = video_info['headers']
                if 'userAgent' in headers:
                    enhanced_headers['User-Agent'] = headers['userAgent']
                if 'referer' in headers:
                    enhanced_headers['Referer'] = headers['referer']
                if 'origin' in headers:
                    enhanced_headers['Origin'] = headers['origin']
                if 'cookie' in headers:
                    enhanced_headers['Cookie'] = headers['cookie']
                
                # 添加现代浏览器安全头
                if 'securityHeaders' in video_info:
                    sec_headers = video_info['securityHeaders']
                    enhanced_headers.update({
                        'Sec-Fetch-Site': sec_headers.get('secFetchSite', 'same-origin'),
                        'Sec-Fetch-Mode': sec_headers.get('secFetchMode', 'cors'),
                        'Sec-Fetch-Dest': sec_headers.get('secFetchDest', 'empty')
                    })
            
            # 创建下载器实例
            downloader = M3U8Downloader(
                m3u8_url=m3u8_url,
                max_workers=self.max_workers_per_video,
                max_retries=3,
                retry_delay=2,
                custom_headers=enhanced_headers
            )
            
            return downloader
        else:
            # 简单字符串URL
            return M3U8Downloader(
                m3u8_url=str(video_info),
                max_workers=self.max_workers_per_video,
                custom_headers=self.custom_headers
            )
    
    def _download_single_video(self, video_info, index):
        """
        下载单个视频
        """
        url = video_info.get('url', '') if isinstance(video_info, dict) else str(video_info)
        domain = video_info.get('domain', 'Unknown') if isinstance(video_info, dict) else urlparse(url).netloc
        
        result = {
            'index': index,
            'url': url,
            'domain': domain,
            'status': 'pending',
            'error': None,
            'output_dir': None,
            'start_time': None,
            'end_time': None,
            'duration': 0
        }
        
        try:
            result['start_time'] = time.time()
            
            with self.lock:
                print(f"\n[{index+1}/{self.total_videos}] 开始下载: {domain}")
                print(f"URL: {url[:80]}...")
            
            # 创建增强的下载器
            downloader = self._create_enhanced_downloader(video_info)
            
            # 下载M3U8文件并解析
            if not downloader._download_m3u8():
                result['status'] = 'failed'
                result['error'] = 'M3U8文件下载或解析失败'
                return result
            
            # 下载所有片段
            success = downloader.download_all_segments()
            
            if success:
                # 合并视频片段
                if downloader.merge_segments():
                    result['status'] = 'completed'
                    result['output_dir'] = downloader.temp_dir
                    
                    with self.lock:
                        self.completed_videos += 1
                        print(f"\n✅ [{index+1}/{self.total_videos}] 下载完成: {domain}")
                        print(f"输出目录: {downloader.temp_dir}")
                else:
                    result['status'] = 'failed'
                    result['error'] = '视频合并失败'
            else:
                result['status'] = 'failed'
                result['error'] = f'片段下载失败 ({downloader.fail_count}/{len(downloader.segments)} 个片段失败)'
            
        except Exception as e:
            result['status'] = 'failed'
            result['error'] = str(e)
            
            with self.lock:
                self.failed_videos += 1
                print(f"\n❌ [{index+1}/{self.total_videos}] 下载失败: {domain}")
                print(f"错误: {result['error']}")
        
        finally:
            result['end_time'] = time.time()
            result['duration'] = result['end_time'] - result['start_time'] if result['start_time'] else 0
        
        return result
    
    def start_batch_download(self, skip_existing=True):
        """
        开始批量下载
        
        Args:
            skip_existing: 是否跳过已存在的视频
        """
        if not self.video_list:
            print("错误: 没有可下载的视频列表")
            return False
        
        print(f"\n开始批量下载 {self.total_videos} 个视频")
        print(f"并发数: {self.max_concurrent_videos}")
        print(f"输出目录: {self.output_base_dir}")
        print("=" * 80)
        
        self.start_time = time.time()
        
        # 使用线程池执行并发下载
        with ThreadPoolExecutor(max_workers=self.max_concurrent_videos) as executor:
            # 提交所有下载任务
            future_to_video = {
                executor.submit(self._download_single_video, video_info, i): (video_info, i)
                for i, video_info in enumerate(self.video_list)
            }
            
            # 等待任务完成并收集结果
            for future in as_completed(future_to_video):
                video_info, index = future_to_video[future]
                try:
                    result = future.result()
                    self.download_results.append(result)
                    
                    # 显示进度
                    completed = len([r for r in self.download_results if r['status'] in ['completed', 'failed']])
                    progress = (completed / self.total_videos) * 100
                    
                    with self.lock:
                        print(f"\n总进度: {progress:.1f}% ({completed}/{self.total_videos})")
                        print(f"成功: {self.completed_videos} | 失败: {self.failed_videos}")
                        
                except Exception as e:
                    print(f"处理下载任务时出错: {e}")
        
        # 显示最终结果
        self._show_final_results()
        return True
    
    def _show_final_results(self):
        """
        显示最终下载结果统计
        """
        end_time = time.time()
        total_duration = end_time - self.start_time if self.start_time else 0
        
        print("\n" + "=" * 80)
        print("批量下载完成!")
        print("=" * 80)
        
        print(f"总视频数: {self.total_videos}")
        print(f"成功下载: {self.completed_videos}")
        print(f"下载失败: {self.failed_videos}")
        print(f"总耗时: {total_duration:.1f} 秒")
        
        if self.completed_videos > 0:
            avg_time = total_duration / self.completed_videos
            print(f"平均每个视频: {avg_time:.1f} 秒")
        
        # 显示失败的视频详情
        failed_results = [r for r in self.download_results if r['status'] == 'failed']
        if failed_results:
            print(f"\n失败的视频详情:")
            for result in failed_results:
                print(f"  ❌ {result['domain']}: {result['error']}")
        
        # 显示成功的视频路径
        success_results = [r for r in self.download_results if r['status'] == 'completed']
        if success_results:
            print(f"\n成功下载的视频:")
            for result in success_results:
                print(f"  ✅ {result['domain']}: {result['output_dir']}")
        
        # 保存下载报告
        self._save_download_report(total_duration)
    
    def _save_download_report(self, total_duration):
        """
        保存下载报告到JSON文件
        """
        try:
            report = {
                'timestamp': datetime.now().isoformat(),
                'total_videos': self.total_videos,
                'completed_videos': self.completed_videos,
                'failed_videos': self.failed_videos,
                'total_duration': total_duration,
                'average_duration': total_duration / max(self.completed_videos, 1),
                'settings': {
                    'max_concurrent_videos': self.max_concurrent_videos,
                    'max_workers_per_video': self.max_workers_per_video,
                    'output_base_dir': self.output_base_dir
                },
                'results': self.download_results
            }
            
            report_file = os.path.join(self.output_base_dir, f'download_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            
            print(f"\n下载报告已保存: {report_file}")
            
        except Exception as e:
            print(f"保存下载报告失败: {e}")

def parse_args():
    """解析命令行参数"""
    import argparse
    parser = argparse.ArgumentParser(description='M3U8视频下载器')
    parser.add_argument('url', nargs='?', help='M3U8文件的网址')
    parser.add_argument('--batch', help='批量下载模式，指定JSON文件路径')
    parser.add_argument('--keep-segments', action='store_true', help='保留原始视频切片文件')
    parser.add_argument('--abort-on-error', action='store_true', help='当有片段下载失败时终止程序')
    parser.add_argument('--test-mode', action='store_true', help='启用测试模式（模拟部分片段下载失败）')
    parser.add_argument('--max-concurrent', type=int, default=DEFAULT_DOWNLOAD_CONFIG['max_concurrent_videos'], 
                        help='同时下载的视频数量')
    parser.add_argument('--max-workers', type=int, default=DEFAULT_DOWNLOAD_CONFIG['max_workers_per_video'], 
                        help='每个视频的最大线程数')
    parser.add_argument('--max-retries', type=int, default=DEFAULT_DOWNLOAD_CONFIG['max_retries'],
                        help='下载失败时的最大重试次数')
    parser.add_argument('--retry-delay', type=int, default=DEFAULT_DOWNLOAD_CONFIG['retry_delay'],
                        help='重试间隔（秒）')
    parser.add_argument('--user-agent', type=str, default=DEFAULT_HEADERS['User-Agent'],
                        help='自定义User-Agent')
    parser.add_argument('--referer', type=str, help='自定义Referer')
    parser.add_argument('--output-dir', type=str, default=DEFAULT_OUTPUT_DIR,
                        help='输出目录')
    
    return parser.parse_args()

def single_download(args):
    """单个视频下载"""
    print("=== 单个视频下载模式 ===")
    
    # 获取M3U8 URL
    m3u8_url = args.url
    if not m3u8_url:
        m3u8_url = input("请输入m3u8文件的网址: ").strip()
    
    if not m3u8_url:
        print("网址不能为空")
        return
    
    # 显示当前的设置
    if args.keep_segments:
        print("注意：将保留原始视频切片文件")
    else:
        print("注意：将自动清理临时视频切片文件")
    
    if args.abort_on_error:
        print("注意：当有片段下载失败时将终止程序，不进行合并")
    else:
        print("注意：当有片段下载失败时将自动排除失败片段，继续合并")
    
    if args.test_mode:
        print("注意：已启用测试模式，将模拟部分片段下载失败")
    
    # 创建自定义请求头
    custom_headers = {}
    if args.user_agent:
        custom_headers['User-Agent'] = args.user_agent
    if args.referer:
        custom_headers['Referer'] = args.referer
    
    # 创建下载器实例
    downloader = M3U8Downloader(
        m3u8_url, 
        max_workers=args.max_workers, 
        max_retries=args.max_retries,
        retry_delay=args.retry_delay,
        test_mode=args.test_mode,
        custom_headers=custom_headers
    )
    
    try:
        # 下载m3u8文件并解析
        if not downloader._download_m3u8():
            return
        
        # 下载所有ts片段
        all_segments_successful = downloader.download_all_segments()
        
        # 如果有片段下载失败
        if not all_segments_successful:
            if args.abort_on_error:
                print("错误：有片段下载失败，已按照--abort-on-error参数设置终止程序")
                return
            else:
                # 自动排除失败的片段，继续合并
                print(f"警告：有 {downloader.fail_count} 个片段下载失败，将只使用成功下载的片段进行合并")
                # 检查是否还有成功下载的片段
                if downloader.success_count == 0:
                    print("错误：没有成功下载的片段，无法进行合并")
                    return
                # 更新下载状态
                downloader._save_download_state()
        
        # 合并ts片段为视频文件
        if downloader.merge_segments(output_dir=args.output_dir):
            # 只有在合并成功后才根据参数决定是否清理临时文件
            if args.keep_segments:
                print("已保留原始视频切片文件")
            else:
                downloader.cleanup()
            
            print(f"\n视频下载完成，保存在: {args.output_dir}")
        else:
            print("视频合并失败，保留切片文件供下次使用")
    except KeyboardInterrupt:
        print("\n程序被用户中断，保留切片文件供下次使用")
    except Exception as e:
        print(f"程序运行出错: {e}")
        print("保留切片文件供下次使用")

def batch_download(args):
    """批量下载"""
    print("=== 批量下载模式 ===")
    
    json_file = args.batch
    if not json_file:
        json_file = input("请输入Chrome扩展导出的JSON文件路径: ").strip()
    
    if not json_file:
        print("错误：JSON文件路径不能为空")
        return
    
    print(f"JSON文件: {json_file}")
    print(f"最大并发视频数: {args.max_concurrent}")
    print(f"每个视频最大线程数: {args.max_workers}")
    print(f"最大重试次数: {args.max_retries}")
    print(f"重试间隔: {args.retry_delay}秒")
    
    if args.keep_segments:
        print("注意：将保留原始视频切片文件")
    if args.abort_on_error:
        print("注意：当有片段下载失败时将终止程序")
    
    # 创建自定义请求头
    custom_headers = {}
    if args.user_agent:
        custom_headers['User-Agent'] = args.user_agent
    if args.referer:
        custom_headers['Referer'] = args.referer
    
    # 创建批量下载器
    batch_downloader = BatchM3U8Downloader(
        json_file_path=json_file,
        max_concurrent_videos=args.max_concurrent,
        max_workers_per_video=args.max_workers,
        output_base_dir=args.output_dir,
        custom_headers=custom_headers
    )
    
    try:
        # 加载JSON文件
        if not batch_downloader.load_json_file():
            return
        
        # 开始批量下载
        batch_downloader.start_batch_download()
        
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"批量下载出错: {e}")

def main():
    print("欢迎使用M3U8视频下载器")
    print("支持单个视频下载和Chrome扩展JSON文件批量下载")
    print("注意：本程序需要ffmpeg支持，请确保已安装并添加到环境变量")
    
    # 解析命令行参数
    args = parse_args()
    
    # 批量下载模式
    if args.batch:
        batch_download(args)
    else:
        # 单个视频下载模式（保留原有逻辑）
        single_download(args)

if __name__ == "__main__":
    main()