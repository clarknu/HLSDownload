#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cleanup script for test directories
"""

import os
import shutil
import hashlib

def is_test_directory(dirname):
    """Check if directory is a test directory (MD5 hash format)"""
    if len(dirname) == 32:
        try:
            # Check if it's a valid hex string (MD5 hash)
            int(dirname, 16)
            return True
        except ValueError:
            return False
    return False

def cleanup_test_directories():
    """Clean up test directories created during testing"""
    current_dir = os.getcwd()
    print(f"Cleaning up test directories in: {current_dir}")
    
    removed_count = 0
    
    for item in os.listdir(current_dir):
        item_path = os.path.join(current_dir, item)
        
        if os.path.isdir(item_path) and is_test_directory(item):
            try:
                # Check if directory is empty or contains only test files
                dir_contents = os.listdir(item_path)
                
                print(f"Removing test directory: {item}")
                shutil.rmtree(item_path)
                removed_count += 1
                
            except Exception as e:
                print(f"Failed to remove {item}: {e}")
    
    print(f"Cleanup complete. Removed {removed_count} test directories.")

if __name__ == "__main__":
    cleanup_test_directories()