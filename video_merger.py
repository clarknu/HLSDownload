"""
视频合并模块
"""
import os
import subprocess
import shutil
from config import FFMPEG_PATHS, FILE_LIST_NAME
from utils import generate_output_filename

class VideoMerger:
    """视频合并器类"""
    
    def __init__(self, temp_dir, segments, output_dir=None):
        self.temp_dir = temp_dir
        self.segments = segments
        self.output_dir = output_dir or temp_dir  # 如果没有指定输出目录，则使用临时目录
    
    def merge_segments(self, output_filename=None):
        """合并视频片段"""
        # 默认输出文件名
        if not output_filename:
            # 使用第一个片段的URL生成文件名（这里需要获取原始URL，简化处理）
            output_filename = generate_output_filename("default_url")
        
        # 确定输出路径
        output_path = os.path.join(self.output_dir, output_filename)
        
        # 确保输出目录存在
        os.makedirs(self.output_dir, exist_ok=True)
        
        # 查找ffmpeg路径
        ffmpeg_path = self._find_ffmpeg()
        if not ffmpeg_path:
            return False
        
        # 创建文件列表
        file_list_path = os.path.join(self.temp_dir, FILE_LIST_NAME)
        with open(file_list_path, 'w', encoding='utf-8') as f:
            for i, segment in enumerate(self.segments):
                # 确定片段文件的扩展名
                segment_extension = self._get_segment_extension(segment)
                segment_path = os.path.join(self.temp_dir, f"segment_{i:05d}.{segment_extension}")
                if os.path.exists(segment_path):
                    f.write(f"file '{segment_path}'\n")
        
        print(f"开始合并视频片段到 {output_path}")
        
        # 使用ffmpeg合并视频
        try:
            # 添加-y参数自动覆盖已存在的文件，无需用户确认
            subprocess.run(
                [ffmpeg_path, '-y', '-f', 'concat', '-safe', '0', '-i', file_list_path, '-c', 'copy', output_path],
                check=True
            )
            print("视频合并成功")
            return True
        except subprocess.CalledProcessError:
            print("视频合并失败")
            return False
    
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
    
    def _find_ffmpeg(self):
        """查找ffmpeg路径"""
        ffmpeg_path = None
        
        for path in FFMPEG_PATHS:
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
                    return None
            else:
                # 如果用户不想指定ffmpeg路径，提供手动合并的方法
                print("\n您可以稍后手动合并视频片段。合并方法：")
                print(f"1. 安装ffmpeg")
                print(f"2. 打开命令行，切换到目录: {self.temp_dir}")
                print(f"3. 运行命令: ffmpeg -f concat -safe 0 -i {FILE_LIST_NAME} -c copy output.mp4")
                return None
        
        return ffmpeg_path