"""
批量下载器模块
"""
import os
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from config import DEFAULT_DOWNLOAD_CONFIG, DEFAULT_OUTPUT_DIR
from models import DownloadResult, VideoInfo
from segment_downloader import SegmentDownloader
from utils import save_download_report

class BatchDownloader:
    """批量下载器类"""
    
    def __init__(self, json_file_path, max_concurrent_videos=None, max_workers_per_video=None, output_base_dir=None):
        # 配置参数
        self.json_file_path = json_file_path
        self.max_concurrent_videos = max_concurrent_videos or DEFAULT_DOWNLOAD_CONFIG['max_concurrent_videos']
        self.max_workers_per_video = max_workers_per_video or DEFAULT_DOWNLOAD_CONFIG['max_workers_per_video']
        self.output_base_dir = output_base_dir or DEFAULT_OUTPUT_DIR
        
        # 确保输出目录存在
        if not os.path.exists(self.output_base_dir):
            os.makedirs(self.output_base_dir)
        
        # 数据结构
        self.video_list = []
        self.download_results = []
        self.lock = threading.Lock()
        
        # 统计信息
        self.total_videos = 0
        self.completed_videos = 0
        self.failed_videos = 0
        self.skipped_videos = 0
        self.start_time = None
        
        print(f"批量下载器初始化完成")
        print(f"输出目录: {self.output_base_dir}")
        print(f"最大并发视频数: {self.max_concurrent_videos}")
        print(f"每个视频的最大线程数: {self.max_workers_per_video}")
    
    def load_json_file(self):
        """加载JSON文件"""
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
    
    def _create_downloader(self, video_info):
        """创建下载器实例"""
        if isinstance(video_info, dict):
            m3u8_url = video_info.get('url', '')
        else:
            m3u8_url = str(video_info)
        
        return SegmentDownloader(
            m3u8_url=m3u8_url,
            max_workers=self.max_workers_per_video,
            max_retries=3,
            retry_delay=2
        )
    
    def _download_single_video(self, video_info, index):
        """下载单个视频"""
        url = video_info.get('url', '') if isinstance(video_info, dict) else str(video_info)
        domain = video_info.get('domain', 'Unknown') if isinstance(video_info, dict) else urlparse(url).netloc
        
        result = DownloadResult(
            index=index,
            url=url,
            domain=domain,
            status='pending'
        )
        
        try:
            result.start_time = time.time()
            
            with self.lock:
                print(f"\n[{index+1}/{self.total_videos}] 开始下载: {domain}")
                print(f"URL: {url[:80]}...")
            
            # 创建下载器
            downloader = self._create_downloader(video_info)
            
            # 下载M3U8文件并解析
            if not downloader.download_m3u8():
                result.status = 'failed'
                result.error = 'M3U8文件下载或解析失败'
                return result
            
            # 下载所有片段
            success = downloader.download_all_segments()
            
            if success:
                # 合并视频片段
                from video_merger import VideoMerger
                merger = VideoMerger(downloader.temp_dir, downloader.segments)
                if merger.merge_segments():
                    result.status = 'completed'
                    result.output_dir = downloader.temp_dir
                    
                    with self.lock:
                        self.completed_videos += 1
                        print(f"\n✅ [{index+1}/{self.total_videos}] 下载完成: {domain}")
                        print(f"输出目录: {downloader.temp_dir}")
                else:
                    result.status = 'failed'
                    result.error = '视频合并失败'
            else:
                result.status = 'failed'
                result.error = f'片段下载失败 ({downloader.fail_count}/{len(downloader.segments)} 个片段失败)'
            
        except Exception as e:
            result.status = 'failed'
            result.error = str(e)
            
            with self.lock:
                self.failed_videos += 1
                print(f"\n❌ [{index+1}/{self.total_videos}] 下载失败: {domain}")
                print(f"错误: {result.error}")
        
        finally:
            result.end_time = time.time()
            result.duration = result.end_time - result.start_time if result.start_time else 0
        
        return result
    
    def start_batch_download(self):
        """开始批量下载"""
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
                    completed = len([r for r in self.download_results if r.status in ['completed', 'failed']])
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
        """显示最终下载结果统计"""
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
        failed_results = [r for r in self.download_results if r.status == 'failed']
        if failed_results:
            print(f"\n失败的视频详情:")
            for result in failed_results:
                print(f"  ❌ {result.domain}: {result.error}")
        
        # 显示成功的视频路径
        success_results = [r for r in self.download_results if r.status == 'completed']
        if success_results:
            print(f"\n成功下载的视频:")
            for result in success_results:
                print(f"  ✅ {result.domain}: {result.output_dir}")
        
        # 保存下载报告
        self._save_download_report(total_duration)
    
    def _save_download_report(self, total_duration):
        """保存下载报告"""
        report_data = {
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
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
            'results': [
                {
                    'index': r.index,
                    'url': r.url,
                    'domain': r.domain,
                    'status': r.status,
                    'error': r.error,
                    'output_dir': r.output_dir,
                    'start_time': r.start_time,
                    'end_time': r.end_time,
                    'duration': r.duration
                }
                for r in self.download_results
            ]
        }
        
        save_download_report(self.output_base_dir, report_data)