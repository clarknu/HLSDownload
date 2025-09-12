#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M3U8视频下载器主程序
支持单个视频下载和批量下载
"""

import os
import sys
import argparse
from config import DEFAULT_DOWNLOAD_CONFIG, DEFAULT_HEADERS, FFMPEG_PATHS, DEFAULT_OUTPUT_DIR, load_config

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='M3U8视频下载器')
    parser.add_argument('url', nargs='?', help='M3U8文件的网址')
    parser.add_argument('--batch', help='批量下载模式，指定JSON文件路径')
    parser.add_argument('--keep-segments', action='store_true', default=DEFAULT_DOWNLOAD_CONFIG.get('keep_segments', False), 
                        help='保留原始视频切片文件')
    parser.add_argument('--abort-on-error', action='store_true', default=DEFAULT_DOWNLOAD_CONFIG.get('abort_on_error', False), 
                        help='当有片段下载失败时终止程序')
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
    parser.add_argument('--config', type=str, help='指定配置文件路径')
    
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
    
    # 创建下载器实例，传入output_dir参数
    from segment_downloader import SegmentDownloader
    downloader = SegmentDownloader(
        m3u8_url, 
        max_workers=args.max_workers, 
        max_retries=args.max_retries,
        retry_delay=args.retry_delay,
        test_mode=args.test_mode,
        custom_headers=custom_headers,
        output_dir=args.output_dir  # 传入output_dir参数
    )
    
    try:
        # 下载m3u8文件并解析
        if not downloader.download_m3u8():
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
        from video_merger import VideoMerger
        merger = VideoMerger(downloader.temp_dir, downloader.segments, args.output_dir)
        if merger.merge_segments():
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
        json_file = input("请输入JSON文件路径: ").strip()
    
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
    
    # 创建批量下载器
    from batch_downloader import BatchDownloader
    batch_downloader = BatchDownloader(
        json_file_path=json_file,
        max_concurrent_videos=args.max_concurrent,
        max_workers_per_video=args.max_workers,
        output_base_dir=args.output_dir
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
    """主函数"""
    print("欢迎使用M3U8视频下载器")
    print("支持单个视频下载和JSON文件批量下载")
    print("注意：本程序需要ffmpeg支持，请确保已安装并添加到环境变量")
    
    args = parse_args()
    
    # 如果指定了配置文件，重新加载配置
    if args.config:
        try:
            import config
            config.CONFIG = config.load_config(args.config)
            config.DEFAULT_DOWNLOAD_CONFIG = config.CONFIG['download_config']
            config.DEFAULT_HEADERS = config.CONFIG['default_headers']
            config.FFMPEG_PATHS = config.CONFIG['ffmpeg_paths']
            config.DEFAULT_OUTPUT_DIR = config.CONFIG['output_dir']
            
            # 更新参数的默认值
            args.keep_segments = args.keep_segments or config.DEFAULT_DOWNLOAD_CONFIG.get('keep_segments', False)
            args.abort_on_error = args.abort_on_error or config.DEFAULT_DOWNLOAD_CONFIG.get('abort_on_error', False)
            args.max_concurrent = config.DEFAULT_DOWNLOAD_CONFIG.get('max_concurrent_videos', args.max_concurrent)
            args.max_workers = config.DEFAULT_DOWNLOAD_CONFIG.get('max_workers_per_video', args.max_workers)
            args.max_retries = config.DEFAULT_DOWNLOAD_CONFIG.get('max_retries', args.max_retries)
            args.retry_delay = config.DEFAULT_DOWNLOAD_CONFIG.get('retry_delay', args.retry_delay)
            args.user_agent = args.user_agent or config.DEFAULT_HEADERS.get('User-Agent', args.user_agent)
            args.output_dir = args.output_dir or config.DEFAULT_OUTPUT_DIR
            
            print(f"已加载配置文件: {args.config}")
        except Exception as e:
            print(f"加载配置文件失败: {e}")
            return
    
    # 批量下载模式
    if args.batch:
        batch_download(args)
    else:
        # 单个视频下载模式
        single_download(args)

if __name__ == "__main__":
    main()