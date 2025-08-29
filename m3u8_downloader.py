import os
import re
import sys
import hashlib
import requests
import time
import subprocess
import shutil
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urljoin
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

class M3U8Downloader:
    def __init__(self, m3u8_url, max_workers=10):
        self.m3u8_url = m3u8_url
        self.max_workers = max_workers
        self.temp_dir = self._create_temp_dir()
        self.segments = []
        self.total_size = 0
        self.success_count = 0
        self.fail_count = 0
        self.start_time = None
        self.base_url = self._get_base_url()
        # 解密相关属性
        self.is_encrypted = False
        self.key_url = None
        self.key = None
        self.iv = None

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
                    
                    # 下载密钥
                    print(f"正在下载密钥: {self.key_url}")
                    key_response = requests.get(self.key_url, timeout=30)
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
            ts_pattern = re.compile(r'[^#][^\n]*\.ts')
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
        try:
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
            
            # 显示下载进度
            elapsed_time = time.time() - self.start_time
            speed = self.total_size / elapsed_time if elapsed_time > 0 else 0
            progress = (self.success_count + self.fail_count) / len(self.segments) * 100
            
            sys.stdout.write(f"\r下载进度: {progress:.2f}% | 成功: {self.success_count} | 失败: {self.fail_count} | 速度: {speed/1024/1024:.2f} MB/s")
            sys.stdout.flush()
            
        except Exception as e:
            self.fail_count += 1
            print(f"\n下载片段 {index} 失败: {e}")

    def download_all_segments(self):
        print(f"开始下载 {len(self.segments)} 个ts片段到 {self.temp_dir}")
        self.start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for i, segment in enumerate(self.segments):
                executor.submit(self._download_segment, segment, i)
        
        print("\n所有片段下载完成")
        
        if self.fail_count > 0:
            print(f"注意: 有 {self.fail_count} 个片段下载失败")
        
        return self.fail_count == 0

    def merge_segments(self, output_filename=None):
        # 默认输出文件名
        if not output_filename:
            parsed_url = urlparse(self.m3u8_url)
            domain = parsed_url.netloc.split('.')[-2]
            output_filename = f"{domain}_video.mp4"
        
        output_path = os.path.join(self.temp_dir, output_filename)
        
        # 检查是否有ffmpeg
        ffmpeg_path = shutil.which('ffmpeg')
        
        if not ffmpeg_path:
            print("未找到ffmpeg，请先安装ffmpeg")
            print("Windows用户可以从https://ffmpeg.org/download.html下载，并将bin目录添加到环境变量")
            
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
            subprocess.run(
                [ffmpeg_path, '-f', 'concat', '-safe', '0', '-i', file_list_path, '-c', 'copy', output_path],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            print("视频合并成功")
            return True
        except subprocess.CalledProcessError as e:
            print(f"视频合并失败: {e}")
            print(e.stderr.decode())
            return False

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
            
            print("临时文件清理完成")
        except Exception as e:
            print(f"清理临时文件失败: {e}")

def main():
    print("欢迎使用m3u8视频下载器")
    print("注意：本程序需要ffmpeg支持，请确保已安装并添加到环境变量")
    
    # 获取m3u8网址（优先从命令行参数获取）
    m3u8_url = None
    if len(sys.argv) > 1:
        m3u8_url = sys.argv[1].strip()
    
    # 如果命令行没有提供网址，则询问用户输入
    if not m3u8_url:
        m3u8_url = input("请输入m3u8文件的网址: ").strip()
    
    if not m3u8_url:
        print("网址不能为空")
        return
    
    # 创建下载器实例
    downloader = M3U8Downloader(m3u8_url)
    
    try:
        # 下载m3u8文件并解析
        if not downloader._download_m3u8():
            return
        
        # 下载所有ts片段
        if not downloader.download_all_segments():
            # 如果有片段下载失败，可以选择继续合并或退出
            choice = input("有片段下载失败，是否继续合并？(y/n): ").lower()
            if choice != 'y':
                return
        
        # 合并ts片段为视频文件
        if downloader.merge_segments():
            # 询问是否清理临时文件
            choice = input("是否清理临时ts片段文件？(y/n): ").lower()
            if choice == 'y':
                downloader.cleanup()
            
            print(f"\n视频下载完成，保存在: {downloader.temp_dir}")
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"程序运行出错: {e}")

if __name__ == "__main__":
    main()