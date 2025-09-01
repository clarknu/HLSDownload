import os
import re
import sys
import hashlib
import json
import requests
import time
import subprocess
import shutil
from concurrent.futures import ThreadPoolExecutor
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

def main():
    print("欢迎使用m3u8视频下载器")
    print("注意：本程序需要ffmpeg支持，请确保已安装并添加到环境变量")
    
    # 解析命令行参数
    m3u8_url = None
    keep_segments = False
    abort_on_error = False
    test_mode = False
    
    # 检查帮助参数
    if '--help' in sys.argv or '-h' in sys.argv:
        print("使用方法：")
        print("  python m3u8_downloader.py [M3U8_URL] [OPTIONS]")
        print("")
        print("参数：")
        print("  M3U8_URL                      M3U8文件的网址")
        print("")
        print("选项：")
        print("  -h, --help                    显示帮助信息")
        print("  -k, --keep-segments           保留原始视频切片文件")
        print("  -a, --abort-on-error          当有片段下载失败时终止程序")
        print("  --test-mode                   启用测试模式（模拟部分片段下载失败）")
        print("")
        print("示例：")
        print("  python m3u8_downloader.py https://example.com/video.m3u8")
        print("  python m3u8_downloader.py --keep-segments")
        print("  python m3u8_downloader.py https://example.com/video.m3u8 --abort-on-error")
        return
    
    # 检查是否有--keep-segments或-k参数
    if '--keep-segments' in sys.argv:
        keep_segments = True
        sys.argv.remove('--keep-segments')
    elif '-k' in sys.argv:
        keep_segments = True
        sys.argv.remove('-k')
    
    # 检查是否有--abort-on-error或-a参数
    if '--abort-on-error' in sys.argv:
        abort_on_error = True
        sys.argv.remove('--abort-on-error')
    elif '-a' in sys.argv:
        abort_on_error = True
        sys.argv.remove('-a')
    
    # 检查是否有--test-mode参数（用于测试）
    if '--test-mode' in sys.argv:
        test_mode = True
        sys.argv.remove('--test-mode')
        print("注意：已启用测试模式，将模拟部分片段下载失败")
    
    # 获取m3u8网址（优先从命令行参数获取）
    if len(sys.argv) > 1:
        m3u8_url = sys.argv[1].strip()
    
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
    downloader = M3U8Downloader(m3u8_url, test_mode=test_mode)
    
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