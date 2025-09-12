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

class M3U8Downloader:
    def __init__(self, m3u8_url, max_workers=10, max_retries=3, retry_delay=2, test_mode=False):
        self.m3u8_url = m3u8_url
        self.max_workers = max_workers
        self.max_retries = max_retries  # 最大重试次数
        self.retry_delay = retry_delay  # 重试间隔（秒）
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
        self.state_file = os.path.join(self.temp_dir, 'download_state.json')
        self.downloaded_segments = set()  # 已成功下载的片段索引
        self.failed_segments = set()     # 下载失败的片段索引
        self._load_download_state()

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
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'Referer': self.base_url,
            }
            
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
                    key_headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36',
                        'Accept': '*/*',
                        'Accept-Language': 'zh-CN,zh;q=0.9',
                        'Referer': self.base_url,
                    }
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
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': self.base_url,
        }
        
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

    def merge_segments(self, output_filename=None):
        # 默认输出文件名，生成更具唯一性的文件名
        if not output_filename:
            parsed_url = urlparse(self.m3u8_url)
            domain = parsed_url.netloc.replace('.', '_')  # 将域名中的点替换为下划线
            timestamp = time.strftime('%Y%m%d_%H%M%S')  # 添加时间戳
            random_str = hashlib.md5(self.m3u8_url.encode()).hexdigest()[:8]  # 基于URL生成随机字符串
            output_filename = f"{domain}_{timestamp}_{random_str}.mp4"
        
        output_path = os.path.join(self.temp_dir, output_filename)
        
        # 优先检查预设的ffmpeg路径
        ffmpeg_path = None
        potential_paths = [
            r"C:\Soft\ffmpeg\ffmpeg.exe",  # 用户指定的路径
            "ffmpeg",  # 系统PATH中的ffmpeg
        ]
        
        for path in potential_paths:
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
                print(f"3. 运行命令: ffmpeg -f concat -safe 0 -i file_list.txt -c copy {output_filename}")
                return False
        
        # 创建文件列表
        file_list_path = os.path.join(self.temp_dir, "file_list.txt")
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
            
            file_list_path = os.path.join(self.temp_dir, "file_list.txt")
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
    
    def __init__(self, json_file_path, max_concurrent_videos=3, max_workers_per_video=10, output_base_dir=None):
        """
        初始化批量下载器
        
        Args:
            json_file_path: Chrome扩展导出的JSON文件路径
            max_concurrent_videos: 同时下载的视频数量
            max_workers_per_video: 每个视频的最大线程数
            output_base_dir: 输出目录，默认为当前目录下的downloads文件夹
        """
        self.json_file_path = json_file_path
        self.max_concurrent_videos = max_concurrent_videos
        self.max_workers_per_video = max_workers_per_video
        self.video_list = []
        self.download_results = []
        self.start_time = None
        self.lock = threading.Lock()
        
        # 设置输出目录
        if output_base_dir is None:
            self.output_base_dir = os.path.join(os.getcwd(), 'downloads')
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
            
            # 创建下载器实例
            downloader = M3U8Downloader(
                m3u8_url=m3u8_url,
                max_workers=self.max_workers_per_video,
                max_retries=3,
                retry_delay=2
            )
            
            # 应用Chrome扩展收集的请求头信息
            if 'headers' in video_info:
                headers = video_info['headers']
                enhanced_headers = {
                    'User-Agent': headers.get('userAgent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36'),
                    'Accept': '*/*',
                    'Accept-Language': 'zh-CN,zh;q=0.9',
                    'Referer': headers.get('referer', ''),
                }
                
                # 添加Origin头
                if headers.get('origin'):
                    enhanced_headers['Origin'] = headers['origin']
                
                # 添加Cookie（如果有）
                if headers.get('cookie'):
                    enhanced_headers['Cookie'] = headers['cookie']
                
                # 添加现代浏览器安全头
                if 'securityHeaders' in video_info:
                    sec_headers = video_info['securityHeaders']
                    enhanced_headers.update({
                        'Sec-Fetch-Site': sec_headers.get('secFetchSite', 'same-origin'),
                        'Sec-Fetch-Mode': sec_headers.get('secFetchMode', 'cors'),
                        'Sec-Fetch-Dest': sec_headers.get('secFetchDest', 'empty')
                    })
                
                # 覆盖下载器的默认请求头方法
                original_download_m3u8 = downloader._download_m3u8
                original_download_segment = downloader._download_segment
                
                def enhanced_download_m3u8():
                    # 使用增强的请求头下载M3U8
                    try:
                        response = requests.get(downloader.m3u8_url, headers=enhanced_headers, timeout=30)
                        response.raise_for_status()
                        m3u8_content = response.text
                        
                        # 检查是否为加密的m3u8文件 - 复用原逻辑
                        if '#EXT-X-KEY' in m3u8_content:
                            downloader.is_encrypted = True
                            print("检测到加密的m3u8文件，正在解析密钥信息...")
                            
                            key_match = re.search(r'#EXT-X-KEY:METHOD=AES-128,URI="(.*?)"', m3u8_content)
                            if key_match:
                                downloader.key_url = key_match.group(1)
                                if not downloader.key_url.startswith('http'):
                                    downloader.key_url = urljoin(downloader.m3u8_url, downloader.key_url)
                                
                                print(f"正在下载密钥: {downloader.key_url}")
                                key_response = requests.get(downloader.key_url, headers=enhanced_headers, timeout=30)
                                key_response.raise_for_status()
                                downloader.key = key_response.content
                                
                                iv_match = re.search(r'IV=(.*?)(?:,|\r|\n)', m3u8_content)
                                if iv_match:
                                    iv_hex = iv_match.group(1)
                                    if iv_hex.startswith('0x'):
                                        iv_hex = iv_hex[2:]
                                    downloader.iv = bytes.fromhex(iv_hex)
                                else:
                                    downloader.iv = None
                                
                                print("密钥解析成功")
                            else:
                                print("无法解析密钥信息")
                                return False
                        
                        # 解析ts片段
                        ts_pattern = re.compile(r'^(?!#)[^\n]*\.ts\s*$', re.MULTILINE)
                        downloader.segments = ts_pattern.findall(m3u8_content)
                        downloader.segments = [segment.strip().replace('\n', '').replace('\r', '') for segment in downloader.segments]
                        
                        if not downloader.segments:
                            print("未找到ts片段")
                            return False
                        
                        print(f"找到 {len(downloader.segments)} 个ts片段")
                        return True
                        
                    except Exception as e:
                        print(f"下载m3u8文件失败: {e}")
                        return False
                
                def enhanced_download_segment(segment_url, index):
                    # 使用增强的请求头下载片段
                    return original_download_segment(segment_url, index)
                
                # 更新下载器方法
                downloader._download_m3u8 = enhanced_download_m3u8
                
            return downloader
        else:
            # 简单字符串URL
            return M3U8Downloader(
                m3u8_url=str(video_info),
                max_workers=self.max_workers_per_video
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

def main():
    print("欢迎使用M3U8视频下载器")
    print("支持单个视频下载和Chrome扩展JSON文件批量下载")
    print("注意：本程序需要ffmpeg支持，请确保已安装并添加到环境变量")
    
    # 解析命令行参数
    m3u8_url = None
    json_file = None
    keep_segments = False
    abort_on_error = False
    test_mode = False
    max_concurrent_videos = 3
    max_workers_per_video = 10
    
    # 检查帮助参数
    if '--help' in sys.argv or '-h' in sys.argv:
        print("")
        print("使用方法：")
        print("  单个视频下载:")
        print("    python m3u8_downloader.py [M3U8_URL] [OPTIONS]")
        print("")
        print("  批量下载 (从Chrome扩展JSON文件):")
        print("    python m3u8_downloader.py --batch [JSON_FILE] [OPTIONS]")
        print("")
        print("参数：")
        print("  M3U8_URL                      M3U8文件的网址")
        print("  JSON_FILE                     Chrome扩展导出的JSON文件路径")
        print("")
        print("选项：")
        print("  -h, --help                    显示帮助信息")
        print("  --batch                       启用批量下载模式")
        print("  -k, --keep-segments           保留原始视频切片文件")
        print("  -a, --abort-on-error          当有片段下载失败时终止程序")
        print("  --test-mode                   启用测试模式（模拟部分片段下载失败）")
        print("  --max-concurrent N            同时下载的视频数量 (默认: 3)")
        print("  --max-workers N               每个视频的最大线程数 (默认: 10)")
        print("")
        print("示例：")
        print("  # 单个视频下载")
        print("  python m3u8_downloader.py https://example.com/video.m3u8")
        print("  python m3u8_downloader.py https://example.com/video.m3u8 --keep-segments")
        print("")
        print("  # 批量下载")
        print("  python m3u8_downloader.py --batch m3u8_links_20231201_143022.json")
        print("  python m3u8_downloader.py --batch m3u8_links.json --max-concurrent 5 --max-workers 8")
        return
    
    # 处理命令行参数
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        
        if arg == '--batch':
            if i + 1 < len(args):
                json_file = args[i + 1]
                i += 1
            else:
                print("错误: --batch 参数后需要指定JSON文件路径")
                return
        elif arg in ['--keep-segments', '-k']:
            keep_segments = True
        elif arg in ['--abort-on-error', '-a']:
            abort_on_error = True
        elif arg == '--test-mode':
            test_mode = True
            print("注意：已启用测试模式，将模拟部分片段下载失败")
        elif arg == '--max-concurrent':
            if i + 1 < len(args):
                try:
                    max_concurrent_videos = int(args[i + 1])
                    if max_concurrent_videos < 1:
                        max_concurrent_videos = 1
                    i += 1
                except ValueError:
                    print("错误: --max-concurrent 参数值必须是正整数")
                    return
            else:
                print("错误: --max-concurrent 参数后需要指定数值")
                return
        elif arg == '--max-workers':
            if i + 1 < len(args):
                try:
                    max_workers_per_video = int(args[i + 1])
                    if max_workers_per_video < 1:
                        max_workers_per_video = 1
                    i += 1
                except ValueError:
                    print("错误: --max-workers 参数值必须是正整数")
                    return
            else:
                print("错误: --max-workers 参数后需要指定数值")
                return
        elif not arg.startswith('-') and not m3u8_url and not json_file:
            # 这可能是M3U8 URL
            m3u8_url = arg
        
        i += 1
    
    # 批量下载模式
    if json_file or '--batch' in sys.argv:
        if not json_file:
            json_file = input("请输入Chrome扩展导出的JSON文件路径: ").strip()
        
        if not json_file:
            print("错误：JSON文件路径不能为空")
            return
        
        print(f"\n=== 批量下载模式 ===")
        print(f"JSON文件: {json_file}")
        print(f"最大并发视频数: {max_concurrent_videos}")
        print(f"每个视频最大线程数: {max_workers_per_video}")
        
        if keep_segments:
            print("注意：将保留原始视频切片文件")
        if abort_on_error:
            print("注意：当有片段下载失败时将终止程序")
        
        # 创建批量下载器
        batch_downloader = BatchM3U8Downloader(
            json_file_path=json_file,
            max_concurrent_videos=max_concurrent_videos,
            max_workers_per_video=max_workers_per_video
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
        
        return
    
    # 单个视频下载模式（保留原有逻辑）
    print(f"\n=== 单个视频下载模式 ===")
    
    # 如果命令行没有提供网址，则询问用户输入
    if not m3u8_url:
        m3u8_url = input("请输入m3u8文件的网址: ").strip()
    
    if not m3u8_url:
        print("网址不能为空")
        return
    
    # 显示当前的设置
    if keep_segments:
        print("注意：将保留原始视频切片文件")
    else:
        print("注意：将自动清理临时视频切片文件")
    
    if abort_on_error:
        print("注意：当有片段下载失败时将终止程序，不进行合并")
    else:
        print("注意：当有片段下载失败时将自动排除失败片段，继续合并")
    
    # 创建下载器实例
    downloader = M3U8Downloader(m3u8_url, max_workers=max_workers_per_video, test_mode=test_mode)
    
    try:
        # 下载m3u8文件并解析
        if not downloader._download_m3u8():
            return
        
        # 下载所有ts片段
        all_segments_successful = downloader.download_all_segments()
        
        # 如果有片段下载失败
        if not all_segments_successful:
            if abort_on_error:
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
        if downloader.merge_segments():
            # 根据命令行参数决定是否清理临时文件
            if keep_segments:
                print("已保留原始视频切片文件")
            else:
                downloader.cleanup()
            
            print(f"\n视频下载完成，保存在: {downloader.temp_dir}")
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"程序运行出错: {e}")

if __name__ == "__main__":
    main()