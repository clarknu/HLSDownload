"""
工具函数模块
"""
import os
import hashlib
import json
import time
from urllib.parse import urlparse, urljoin
from datetime import datetime

def create_temp_dir(m3u8_url):
    """创建临时目录"""
    url_hash = hashlib.md5(m3u8_url.encode()).hexdigest()
    temp_dir = os.path.join(os.getcwd(), url_hash)
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    return temp_dir

def get_base_url(m3u8_url):
    """获取基础URL"""
    parsed_url = urlparse(m3u8_url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    path_parts = parsed_url.path.split('/')[:-1]
    if path_parts:
        base_url += '/'.join(path_parts) + '/'
    else:
        base_url += '/'
    return base_url

def ensure_complete_url(segment_url, m3u8_url, base_url):
    """确保URL是完整的"""
    if not segment_url.startswith('http'):
        if segment_url.startswith('/'):
            parsed_url = urlparse(m3u8_url)
            segment_url = f"{parsed_url.scheme}://{parsed_url.netloc}{segment_url}"
        else:
            segment_url = f"{base_url}{segment_url}"
    return segment_url

def generate_output_filename(m3u8_url):
    """生成输出文件名"""
    parsed_url = urlparse(m3u8_url)
    domain = parsed_url.netloc.replace('.', '_')  # 将域名中的点替换为下划线
    timestamp = time.strftime('%Y%m%d_%H%M%S')  # 添加时间戳
    random_str = hashlib.md5(m3u8_url.encode()).hexdigest()[:8]  # 基于URL生成随机字符串
    return f"{domain}_{timestamp}_{random_str}.mp4"

def save_download_state(state_file, downloaded_segments, failed_segments):
    """保存下载状态"""
    try:
        state = {
            'downloaded_segments': list(downloaded_segments),
            'failed_segments': list(failed_segments),
            'last_update_time': time.time()
        }
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存下载状态失败: {e}")

def load_download_state(state_file, temp_dir):
    """加载下载状态"""
    downloaded_segments = set()
    failed_segments = set()
    
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
                downloaded_segments = set(state.get('downloaded_segments', []))
                failed_segments = set(state.get('failed_segments', []))
                
                # 检查哪些已下载的文件可能丢失了
                current_downloaded = set()
                for i in downloaded_segments:
                    segment_path = os.path.join(temp_dir, f"segment_{i:05d}.ts")
                    if os.path.exists(segment_path) and os.path.getsize(segment_path) > 0:
                        current_downloaded.add(i)
                    else:
                        # 文件已丢失，需要重新下载
                        failed_segments.add(i)
                
                downloaded_segments = current_downloaded
                print(f"加载下载状态成功: 已下载 {len(downloaded_segments)} 个片段，失败 {len(failed_segments)} 个片段")
        except Exception as e:
            print(f"加载下载状态失败: {e}")
    
    return downloaded_segments, failed_segments

def save_download_report(output_base_dir, report_data):
    """保存下载报告"""
    try:
        report_file = os.path.join(output_base_dir, f'download_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
        print(f"\n下载报告已保存: {report_file}")
        return report_file
    except Exception as e:
        print(f"保存下载报告失败: {e}")
        return None