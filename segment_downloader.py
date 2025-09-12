"""
片段下载器模块
"""
import os
import re
import sys
import time
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from config import DEFAULT_HEADERS, DEFAULT_OUTPUT_DIR
from utils import ensure_complete_url, save_download_state

class SegmentDownloader:
    """片段下载器类"""
    
    def __init__(self, m3u8_url, max_workers=10, max_retries=3, retry_delay=2, test_mode=False, custom_headers=None, output_dir=None):
        self.m3u8_url = m3u8_url
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.test_mode = test_mode
        self.custom_headers = custom_headers or {}
        self.output_dir = output_dir or DEFAULT_OUTPUT_DIR  # 添加output_dir参数
        
        # 解析URL信息
        from utils import create_temp_dir, get_base_url
        self.temp_dir = create_temp_dir(m3u8_url, self.output_dir)  # 传入output_dir参数
        self.base_url = get_base_url(m3u8_url)
        
        # 初始化状态
        self.segments = []
        self.total_size = 0
        self.success_count = 0
        self.fail_count = 0
        self.retry_count = 0
        self.start_time = None
        
        # 解密相关属性
        self.is_encrypted = False
        self.key_url = None
        self.key = None
        self.iv = None
        
        # 断点续传相关
        from config import STATE_FILE_NAME
        self.state_file = os.path.join(self.temp_dir, STATE_FILE_NAME)
        self.downloaded_segments = set()
        self.failed_segments = set()
        self._load_download_state()
    
    def _load_download_state(self):
        """加载下载状态"""
        from utils import load_download_state
        self.downloaded_segments, self.failed_segments = load_download_state(self.state_file, self.temp_dir)
    
    def _save_download_state(self):
        """保存下载状态"""
        save_download_state(self.state_file, self.downloaded_segments, self.failed_segments)
    
    def _get_headers(self):
        """获取请求头"""
        headers = DEFAULT_HEADERS.copy()
        headers.update(self.custom_headers)
        headers['Referer'] = self.base_url
        return headers
    
    def download_m3u8(self):
        """下载并解析M3U8文件"""
        try:
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
                    
                    # 下载密钥
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
            
            # 解析m3u8文件，获取所有视频片段的URL
            # 改进正则表达式，匹配更多类型的视频片段文件
            # 使用捕获组来获取完整的URL而不是仅扩展名
            segment_pattern = re.compile(r'^(?!#)([^\n]*\.(?:ts|m4s|mp4|aac|m4a|mp3|wav|webm|ogg))\s*$', re.MULTILINE | re.IGNORECASE)
            self.segments = segment_pattern.findall(m3u8_content)
            
            # 如果没有找到上述扩展名的文件，尝试更通用的模式
            if not self.segments:
                # 匹配不以#开头且包含点号的行（可能是文件名）
                general_pattern = re.compile(r'^(?!#)([^\n]*\.[a-zA-Z0-9]+)\s*$', re.MULTILINE)
                self.segments = general_pattern.findall(m3u8_content)
            
            # 清理URL中的换行符和空白字符
            self.segments = [segment.strip().replace('\n', '').replace('\r', '') for segment in self.segments]
            
            if not self.segments:
                print("未找到视频片段")
                return False
            
            print(f"找到 {len(self.segments)} 个视频片段")
            return True
        except Exception as e:
            print(f"下载m3u8文件失败: {e}")
            return False
    
    def _download_segment(self, segment_url, index):
        """下载单个片段"""
        retries = 0
        success = False
        last_error = None
        
        # 确定片段文件的扩展名
        segment_extension = self._get_segment_extension(segment_url)
        
        # 检查文件是否已存在且完整
        segment_path = os.path.join(self.temp_dir, f"segment_{index:05d}.{segment_extension}")
        if os.path.exists(segment_path) and os.path.getsize(segment_path) > 0:
            print(f"\n片段 {index} 已存在且完整，跳过下载")
            self.downloaded_segments.add(index)
            self.success_count += 1
            return
        
        # 测试模式：模拟部分片段下载失败
        if self.test_mode and (index % 5 == 2 or index % 5 == 4):
            self.fail_count += 1
            self.failed_segments.add(index)
            # 清理失败片段的本地文件
            if os.path.exists(segment_path):
                os.remove(segment_path)
            print(f"\n测试模式: 模拟片段 {index} 下载失败")
            self._save_download_state()
            return
        
        # 确保URL是完整的
        segment_url = ensure_complete_url(segment_url, self.m3u8_url, self.base_url)
        
        # 添加请求头
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
                
                # 下载片段
                response = requests.get(segment_url, headers=headers, stream=True, timeout=60)
                response.raise_for_status()
                
                # 保存文件
                file_path = os.path.join(self.temp_dir, f"segment_{index:05d}.{segment_extension}")
                
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
            if os.path.exists(segment_path):
                os.remove(segment_path)
            print(f"\n下载片段 {index} 失败 (已尝试{retries-1}次): {last_error}")
            
        # 保存下载状态
        self._save_download_state()
    
    def _get_segment_extension(self, segment_url):
        """获取片段文件的扩展名"""
        # 常见的视频/音频文件扩展名
        common_extensions = ['ts', 'm4s', 'mp4', 'aac', 'm4a', 'mp3', 'wav', 'webm', 'ogg']
        
        # 从URL中提取文件名
        filename = os.path.basename(segment_url.split('?')[0])  # 移除查询参数
        
        # 获取文件扩展名
        if '.' in filename:
            extension = filename.split('.')[-1].lower()
            # 如果是常见扩展名，直接返回
            if extension in common_extensions:
                return extension
        
        # 默认返回ts扩展名
        return 'ts'
    
    def download_all_segments(self):
        """下载所有片段"""
        # 重新初始化计数器，确保准确
        self.success_count = 0
        self.fail_count = 0
        self.retry_count = 0
        
        # 计算需要下载的片段数量
        segments_to_download = []
        for i, segment in enumerate(self.segments):
            # 确定片段文件的扩展名
            segment_extension = self._get_segment_extension(segment)
            segment_path = os.path.join(self.temp_dir, f"segment_{i:05d}.{segment_extension}")
            if not os.path.exists(segment_path) or os.path.getsize(segment_path) == 0 or i in self.failed_segments:
                segments_to_download.append((segment, i))
            else:
                # 文件存在且不为空，视为下载成功
                self.success_count += 1
        
        # 如果所有片段都已下载完成且没有失败片段
        if not segments_to_download and self.fail_count == 0:
            print(f"所有 {len(self.segments)} 个视频片段已下载完成，无需重新下载")
            return True
        
        # 显示需要下载的片段信息
        print(f"开始下载 {len(segments_to_download)} 个视频片段到 {self.temp_dir}")
        if len(self.segments) > len(segments_to_download):
            print(f"跳过 {len(self.segments) - len(segments_to_download)} 个已成功下载的片段")
        
        # 如果有失败片段，显示相关信息
        if self.failed_segments:
            print(f"发现 {len(self.failed_segments)} 个标记为失败的片段，将重新下载")
            # 清理失败片段的本地文件
            for i in self.failed_segments:
                # 确定片段文件的扩展名
                if i < len(self.segments):
                    segment_extension = self._get_segment_extension(self.segments[i])
                else:
                    segment_extension = 'ts'  # 默认扩展名
                    
                segment_path = os.path.join(self.temp_dir, f"segment_{i:05d}.{segment_extension}")
                if os.path.exists(segment_path):
                    os.remove(segment_path)
                    print(f"已删除失败片段文件: segment_{i:05d}.{segment_extension}")
        
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
    
    def cleanup(self):
        """清理临时文件"""
        try:
            for i in range(len(self.segments)):
                # 确定片段文件的扩展名
                segment_extension = self._get_segment_extension(self.segments[i])
                segment_path = os.path.join(self.temp_dir, f"segment_{i:05d}.{segment_extension}")
                if os.path.exists(segment_path):
                    os.remove(segment_path)
            
            from config import FILE_LIST_NAME
            file_list_path = os.path.join(self.temp_dir, FILE_LIST_NAME)
            if os.path.exists(file_list_path):
                os.remove(file_list_path)
            
            # 清理下载状态文件
            if os.path.exists(self.state_file):
                os.remove(self.state_file)
            
            print("临时文件清理完成")
        except Exception as e:
            print(f"清理临时文件失败: {e}")