#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M3U8批量下载器使用示例
这个脚本展示了如何使用扩展的m3u8_downloader.py进行批量下载
"""

import os
import sys

def main():
    print("=== M3U8批量下载器使用示例 ===")
    print()
    
    print("1. 单个视频下载 (保留原有功能):")
    print("   python m3u8_downloader.py https://example.com/video.m3u8")
    print("   python m3u8_downloader.py https://example.com/video.m3u8 --keep-segments")
    print()
    
    print("2. 批量下载 (新功能):")
    print("   python m3u8_downloader.py --batch m3u8_links_20231201_143022.json")
    print("   python m3u8_downloader.py --batch test_m3u8_batch.json --max-concurrent 5")
    print()
    
    print("3. 高级配置选项:")
    print("   --max-concurrent N    # 同时下载的视频数量 (默认: 3)")
    print("   --max-workers N       # 每个视频的最大线程数 (默认: 10)")
    print("   --keep-segments       # 保留原始视频切片文件")
    print("   --abort-on-error      # 当有片段下载失败时终止程序")
    print()
    
    print("4. 使用流程:")
    print("   a) 使用Chrome扩展监控并导出M3U8链接为JSON文件")
    print("   b) 运行批量下载: python m3u8_downloader.py --batch exported_file.json")
    print("   c) 程序会自动创建downloads文件夹，并在其中创建基于URL哈希的子文件夹")
    print("   d) 下载完成后会生成详细的下载报告")
    print()
    
    print("5. JSON文件格式 (Chrome扩展导出格式):")
    print("""   {
     "timestamp": "2025-01-05T10:30:00.000Z",
     "count": 2,
     "links": [
       {
         "url": "https://example.com/video.m3u8",
         "domain": "example.com",
         "headers": {
           "userAgent": "Mozilla/5.0...",
           "referer": "https://example.com/page",
           "origin": "https://example.com"
         }
       }
     ]
   }""")
    print()
    
    print("6. 特性优势:")
    print("   ✅ 支持并行下载多个视频，提高效率")
    print("   ✅ 自动应用Chrome扩展收集的请求头，提高成功率")
    print("   ✅ 智能断点续传，支持中断后恢复下载")
    print("   ✅ 详细的进度显示和错误报告")
    print("   ✅ 自动处理加密视频(AES-128)")
    print("   ✅ 生成详细的下载报告JSON文件")
    print()
    
    # 检查是否有测试文件
    test_file = "test_m3u8_batch.json"
    if os.path.exists(test_file):
        print(f"7. 测试批量下载功能:")
        print(f"   发现测试文件: {test_file}")
        choice = input("   是否要运行测试批量下载? (y/n): ").lower().strip()
        if choice == 'y':
            print(f"   正在执行: python m3u8_downloader.py --batch {test_file} --max-concurrent 2")
            os.system(f'python m3u8_downloader.py --batch {test_file} --max-concurrent 2')
    
    print()
    print("如需更多帮助，请运行: python m3u8_downloader.py --help")

if __name__ == "__main__":
    main()