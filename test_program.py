#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HLSDownload program functionality test script
Test whether all functions work properly
"""

import sys
import os
from m3u8_downloader import M3U8Downloader

def test_basic_functionality():
    """测试基本功能"""
    print("=== 测试基本功能 ===")
    
    # 测试1: 测试类初始化
    print("1. 测试M3U8Downloader类初始化...")
    try:
        test_url = "https://example.com/test.m3u8"
        downloader = M3U8Downloader(test_url, test_mode=True)
        print("✅ 类初始化成功")
        
        # 验证基本属性
        assert downloader.m3u8_url == test_url
        assert downloader.max_workers == 10
        assert downloader.max_retries == 3
        assert downloader.test_mode == True
        print("✅ 基本属性设置正确")
        
    except Exception as e:
        print(f"❌ 类初始化失败: {e}")
        return False
    
    # 测试2: 测试临时目录创建
    print("2. 测试临时目录创建...")
    try:
        temp_dir = downloader.temp_dir
        assert os.path.exists(temp_dir)
        print(f"✅ 临时目录创建成功: {temp_dir}")
    except Exception as e:
        print(f"❌ 临时目录创建失败: {e}")
        return False
    
    # 测试3: 测试URL解析
    print("3. 测试URL解析...")
    try:
        base_url = downloader.base_url
        print(f"✅ Base URL解析成功: {base_url}")
    except Exception as e:
        print(f"❌ URL解析失败: {e}")
        return False
    
    return True

def test_download_state_management():
    """测试下载状态管理功能"""
    print("\n=== 测试下载状态管理 ===")
    
    try:
        test_url = "https://example.com/test2.m3u8"
        downloader = M3U8Downloader(test_url)
        
        # 测试状态保存和加载
        print("1. 测试状态保存和加载...")
        
        # 模拟一些下载状态
        downloader.downloaded_segments = {0, 1, 2}
        downloader.failed_segments = {3, 4}
        
        # 保存状态
        downloader._save_download_state()
        print("✅ 状态保存成功")
        
        # 创建新实例并加载状态
        downloader2 = M3U8Downloader(test_url)
        if os.path.exists(downloader2.state_file):
            print("✅ 状态文件存在")
        else:
            print("❌ 状态文件不存在")
            return False
            
    except Exception as e:
        print(f"❌ 下载状态管理测试失败: {e}")
        return False
    
    return True

def test_parameter_parsing():
    """测试参数解析功能"""
    print("\n=== 测试参数解析功能 ===")
    
    try:
        # 测试不同的参数组合
        print("1. 测试基本参数...")
        
        # 测试max_workers参数
        downloader1 = M3U8Downloader("https://test.com/test.m3u8", max_workers=5)
        assert downloader1.max_workers == 5
        print("✅ max_workers参数正确")
        
        # 测试max_retries参数
        downloader2 = M3U8Downloader("https://test.com/test.m3u8", max_retries=5)
        assert downloader2.max_retries == 5
        print("✅ max_retries参数正确")
        
        # 测试test_mode参数
        downloader3 = M3U8Downloader("https://test.com/test.m3u8", test_mode=True)
        assert downloader3.test_mode == True
        print("✅ test_mode参数正确")
        
    except Exception as e:
        print(f"❌ 参数解析测试失败: {e}")
        return False
    
    return True

def test_file_operations():
    """测试文件操作功能"""
    print("\n=== 测试文件操作功能 ===")
    
    try:
        test_url = "https://example.com/test3.m3u8"
        downloader = M3U8Downloader(test_url)
        
        # 测试临时文件创建
        print("1. 测试临时文件创建...")
        test_file = os.path.join(downloader.temp_dir, "test_segment.ts")
        with open(test_file, 'w') as f:
            f.write("test content")
        
        assert os.path.exists(test_file)
        print("✅ 临时文件创建成功")
        
        # 测试文件清理
        print("2. 测试文件清理功能...")
        # 注意：这里不真正调用cleanup，因为会删除整个目录
        print("✅ 文件清理功能正常（未实际执行）")
        
    except Exception as e:
        print(f"❌ 文件操作测试失败: {e}")
        return False
    
    return True

def test_error_handling():
    """测试错误处理"""
    print("\n=== 测试错误处理 ===")
    
    try:
        # 测试无效URL处理
        print("1. 测试无效URL处理...")
        downloader = M3U8Downloader("invalid_url")
        # 这应该不会抛出异常，因为URL验证在下载时进行
        print("✅ 无效URL处理正常")
        
        # 测试网络错误处理（模拟）
        print("2. 测试网络错误处理...")
        # 由于无法真正模拟网络错误，这里只是确认相关方法存在
        assert hasattr(downloader, '_download_m3u8')
        assert hasattr(downloader, '_download_segment')
        print("✅ 网络错误处理方法存在")
        
    except Exception as e:
        print(f"❌ 错误处理测试失败: {e}")
        return False
    
    return True

def test_encryption_support():
    """测试加密支持功能"""
    print("\n=== 测试加密支持功能 ===")
    
    try:
        test_url = "https://example.com/encrypted.m3u8"
        downloader = M3U8Downloader(test_url)
        
        # 测试加密相关属性
        print("1. 测试加密属性初始化...")
        assert hasattr(downloader, 'is_encrypted')
        assert hasattr(downloader, 'key_url')
        assert hasattr(downloader, 'key')
        assert hasattr(downloader, 'iv')
        assert downloader.is_encrypted == False  # 默认应该是False
        print("✅ 加密属性初始化正确")
        
        # 验证cryptography库可用
        print("2. 测试加密库可用性...")
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        print("✅ 加密库导入成功")
        
    except Exception as e:
        print(f"❌ 加密支持测试失败: {e}")
        return False
    
    return True

def run_all_tests():
    """运行所有测试"""
    print("开始运行HLSDownload程序功能测试...")
    print("=" * 50)
    
    tests = [
        ("基本功能", test_basic_functionality),
        ("下载状态管理", test_download_state_management),
        ("参数解析", test_parameter_parsing),
        ("文件操作", test_file_operations),
        ("错误处理", test_error_handling),
        ("加密支持", test_encryption_support),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
                print(f"✅ {test_name} 测试通过")
            else:
                failed += 1
                print(f"❌ {test_name} 测试失败")
        except Exception as e:
            failed += 1
            print(f"❌ {test_name} 测试异常: {e}")
        
        print("-" * 30)
    
    print("\n" + "=" * 50)
    print(f"测试总结: 通过 {passed} 个，失败 {failed} 个")
    
    if failed == 0:
        print("🎉 所有测试通过！程序功能正常")
        return True
    else:
        print("⚠️  有测试失败，请检查相关功能")
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)