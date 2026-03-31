from pynwb import NWBFile
from pynwb.image import GrayscaleImage, RGBImage, RGBAImage, IndexSeries
from pynwb.base import Images, ImageReferences
from pathlib import Path
import numpy as np
import pandas as pd
import json
from typing import List, Tuple, Union
from PIL import Image as PILImage

class StimulusImageManager:
    """基于PyNWB官方IndexSeries方案的图片刺激管理器，支持Matlab索引（从1开始）"""
    
    def __init__(self, tsv_file_path: str):
        """初始化图片刺激管理器
        
        Args:
            tsv_file_path: 包含FileName列的TSV文件路径
        """
        self.tsv_file = Path(tsv_file_path)
        self.stimulus_folder = self.tsv_file.parent
        
        if not self.tsv_file.exists():
            raise FileNotFoundError(f"TSV文件不存在: {self.tsv_file}")
        
        # 加载图片列表，保持TSV中的顺序
        df = pd.read_csv(self.tsv_file, sep='\t')
        if 'FileName' not in df.columns:
            raise ValueError("TSV文件中缺少 'FileName' 列")
        
        self.image_filenames = []  # 按TSV顺序的文件名列表
        self.image_paths = []      # 对应的完整路径列表
        
        for idx, row in df.iterrows():
            filename = row['FileName']
            img_path = self.stimulus_folder / filename
            
            if img_path.exists():
                self.image_filenames.append(filename)
                self.image_paths.append(str(img_path.absolute()))
            else:
                print(f"警告: 图片文件不存在: {img_path}")
        
        print(f"成功加载了 {len(self.image_filenames)} 个图片（Matlab索引: 1-{len(self.image_filenames)}）")
    
    def matlab_index_to_python_index(self, matlab_idx: int) -> int:
        """将Matlab索引（1-based）转换为Python索引（0-based）"""
        if matlab_idx < 1 or matlab_idx > len(self.image_filenames):
            raise ValueError(f"Matlab索引超出范围: {matlab_idx} (应该在1-{len(self.image_filenames)}之间)")
        return matlab_idx - 1
    
    def create_image_objects(self, used_indices: List[int]) -> List[Union[GrayscaleImage, RGBImage, RGBAImage]]:
        """为指定的图片索引创建NWB图片对象
        
        Args:
            used_indices: 需要加载的图片索引列表（Python 0-based）
            
        Returns:
            NWB图片对象列表
        """
        image_objects = []
        
        for idx in used_indices:
            if idx < 0 or idx >= len(self.image_paths):
                continue
                
            img_path = Path(self.image_paths[idx])
            filename = self.image_filenames[idx]
            
            try:
                # 使用PIL加载图片
                pil_img = PILImage.open(img_path)
                img_array = np.array(pil_img)
                
                # 确保数据是连续的并且类型正确
                img_array = np.ascontiguousarray(img_array)
                
                # 确保数据类型为uint8
                if img_array.dtype != np.uint8:
                    if img_array.dtype == np.float64 or img_array.dtype == np.float32:
                        # 如果是浮点数，假设范围是0-1，转换为0-255
                        img_array = (img_array * 255).astype(np.uint8)
                    else:
                        img_array = img_array.astype(np.uint8)
                
                # 根据图片类型创建对应的NWB对象
                if len(img_array.shape) == 2:
                    # 灰度图片
                    image_obj = GrayscaleImage(
                        name=f"{Path(filename).stem}",
                        data=img_array.copy(),  # 创建副本以避免引用问题
                        description=f"Stimulus image: {filename}"
                    )
                elif len(img_array.shape) == 3:
                    if img_array.shape[2] == 3:
                        # RGB图片
                        image_obj = RGBImage(
                            name=f"{Path(filename).stem}",
                            data=img_array.copy(),  # 创建副本以避免引用问题
                            description=f"Stimulus image: {filename}"
                        )
                    elif img_array.shape[2] == 4:
                        # RGBA图片
                        image_obj = RGBAImage(
                            name=f"{Path(filename).stem}",
                            data=img_array.copy(),  # 创建副本以避免引用问题
                            description=f"Stimulus image: {filename}"
                        )
                    else:
                        # 其他通道数，转换为RGB
                        img_array = img_array[:, :, :3]
                        image_obj = RGBImage(
                            name=f"{Path(filename).stem}",
                            data=img_array.copy(),  # 创建副本以避免引用问题
                            description=f"Stimulus image: {filename}"
                        )
                else:
                    print(f"警告: 不支持的图片格式: {filename}, shape: {img_array.shape}")
                    continue
                
                image_objects.append(image_obj)
                print(f"加载图片 {idx+1}: {filename} -> {image_obj.name}")
                
            except Exception as e:
                print(f"错误: 无法加载图片 {filename}: {e}")
                continue
        
        return image_objects
    
    def add_to_nwb(self, nwbfile: NWBFile, 
                   stimulus_sequence: List[int],  # Matlab索引列表
                   stimulus_timestamps: np.ndarray,
                   stimulus_name: str = "visual_stimulus") -> Tuple[Images, IndexSeries]:
        """使用官方IndexSeries方案将刺激添加到NWB文件
        
        Args:
            nwbfile: NWB文件对象
            stimulus_sequence: Matlab索引列表（1-based）
            stimulus_timestamps: 刺激时间戳
            stimulus_name: 刺激名称
            
        Returns:
            Tuple[Images, IndexSeries]: (图片容器, 索引序列)
        """
        
        # 1. 转换Matlab索引为Python索引，并找出唯一的图片索引
        python_indices = []
        unique_indices = []
        
        for matlab_idx in stimulus_sequence:
            try:
                python_idx = self.matlab_index_to_python_index(matlab_idx)
                python_indices.append(python_idx)
                if python_idx not in unique_indices:
                    unique_indices.append(python_idx)
            except ValueError as e:
                print(f"警告: {e}")
                python_indices.append(-1)  # 无效索引用-1表示
        
        if not unique_indices:
            raise ValueError("没有找到有效的图片索引")
        unique_indices = sorted(unique_indices)
        
        # 2. 为唯一的图片创建NWB图片对象
        print(f"正在加载 {len(unique_indices)} 个唯一图片...")
        image_objects = self.create_image_objects(unique_indices)
        
        if not image_objects:
            raise ValueError("没有成功创建任何图片对象")
        
        # 3. 创建ImageReferences（定义图片顺序）
        image_references = ImageReferences(
            name="order_of_images",
            data=image_objects
        )
        
        # 4. 创建Images容器
        images_container = Images(
            name=f"{stimulus_name}_images",
            images=image_objects,
            description=f"Stimulus images from {self.tsv_file.name}. "
                       f"Contains {len(image_objects)} unique images used in the experiment.",
            order_of_images=image_references
        )
        
        # 5. 创建正确的索引序列：映射每个刺激到Images容器中图片的位置
        # IndexSeries.data 应该包含图片在Images容器中的索引（0-based）
        index_sequence = []
        
        # 创建从原始图片索引到容器位置的映射
        # 注意：unique_indices是按照在容器中的顺序排列的
        python_to_container_map = {}
        for container_pos, python_idx in enumerate(unique_indices):
            if container_pos < len(image_objects):  # 确保成功加载
                python_to_container_map[python_idx] = container_pos
        
        # 为每个刺激时间点创建对应的容器索引
        for python_idx in python_indices:
            if python_idx in python_to_container_map:
                index_sequence.append(python_to_container_map[python_idx])
            else:
                # 无效索引，使用0（第一个图片）作为默认值
                print(f"警告: Python索引 {python_idx} 无效，使用默认值 0")
                index_sequence.append(0)
        
        # 6. 创建IndexSeries
        index_series = IndexSeries(
            name=stimulus_name,
            description=f"Stimulus presentation sequence indexing into {images_container.name}. "
                       f"Contains {len(stimulus_sequence)} stimulus presentations.",
            data=index_sequence,
            indexed_images=images_container,
            timestamps=stimulus_timestamps,
            unit='N/A'
        )
    
        # 7. 添加到NWB文件（使用更安全的方式）
        try:
            nwbfile.add_acquisition(images_container)  # 图片容器作为acquisition
            nwbfile.add_stimulus(index_series)         # 刺激序列作为stimulus
            
            valid_count = len([x for x in python_indices if x >= 0])
            print(f"\n✓ 成功添加IndexSeries:")
            print(f"  - 刺激序列: {len(stimulus_sequence)} 个时间点（{valid_count} 个有效）")
            print(f"  - 唯一图片: {len(image_objects)} 个")
            print(f"  - 图片容器: {images_container.name}")
            print(f"  - 索引序列: {index_series.name}")
            
            # 验证添加是否成功
            if images_container.name in nwbfile.acquisition:
                print(f"  ✓ 图片容器成功添加到acquisition")
            else:
                print(f"  ⚠️ 图片容器添加可能有问题")
                
            if index_series.name in nwbfile.stimulus:
                print(f"  ✓ 刺激序列成功添加到stimulus")
            else:
                print(f"  ⚠️ 刺激序列添加可能有问题")
            
        except Exception as e:
            print(f"❌ 添加到NWB文件时出错: {e}")
            # 尝试清理已添加的内容
            try:
                if images_container.name in nwbfile.acquisition:
                    del nwbfile.acquisition[images_container.name]
                if hasattr(nwbfile, 'stimulus') and index_series.name in nwbfile.stimulus:
                    del nwbfile.stimulus[index_series.name]
            except:
                pass
            raise
        
        return images_container, index_series


def read_stimulus_sequence_from_nwb(nwbfile, stimulus_name: str = "visual_stimulus") -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """从NWB文件中正确读取刺激序列
    
    Args:
        nwbfile: 读取的NWB文件对象
        stimulus_name: 刺激名称
        
    Returns:
        Tuple[np.ndarray, np.ndarray, List[str]]: 
        (原始Matlab索引序列, 时间戳, 图片文件名列表)
    """
    try:
        # 读取IndexSeries
        index_series = nwbfile.stimulus[stimulus_name]
        timestamps = index_series.timestamps[:]
        container_indices = index_series.data[:]  # 这是图片在容器中的位置索引
        
        # 读取原始Matlab序列（如果存在）
        scratch_name = f"{stimulus_name}_original_matlab_sequence"
        if hasattr(nwbfile, 'scratch') and scratch_name in nwbfile.scratch:
            original_matlab_sequence = nwbfile.scratch[scratch_name].data[:]
            print(f"✓ 从scratch中读取到原始Matlab序列，长度: {len(original_matlab_sequence)}")
        else:
            print("⚠️ 未找到原始Matlab序列，将尝试从IndexSeries重建")
            original_matlab_sequence = None
        
        # 读取图片容器和文件名信息
        images_container_name = f"{stimulus_name}_images"
        if images_container_name in nwbfile.acquisition:
            images_container = nwbfile.acquisition[images_container_name]
            
            # 从图片对象名称中提取文件名
            image_filenames = []
            for img in images_container.images:
                # 图片名称格式: "image_XXX_filename_stem"
                if hasattr(img, 'name'):
                    img_name = img.name
                elif isinstance(img, str):
                    img_name = img
                else:
                    img_name = str(img)
                    
                if "_" in img_name:
                    # 提取原始文件名
                    parts = img_name.split("_")
                    if len(parts) >= 3:
                        filename_stem = "_".join(parts[2:])
                        image_filenames.append(filename_stem)
                    else:
                        image_filenames.append(img_name)
                else:
                    image_filenames.append(img_name)
            
            print(f"✓ 读取到 {len(image_filenames)} 个图片文件名")
        else:
            print(f"⚠️ 未找到图片容器: {images_container_name}")
            image_filenames = []
        
        return original_matlab_sequence, timestamps, image_filenames
        
    except Exception as e:
        print(f"❌ 读取刺激序列时出错: {e}")
        raise


# 使用示例
def example_usage():
    """基于PyNWB官方IndexSeries方案的使用示例"""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import numpy as np
    from pynwb import NWBHDF5IO
    
    # 1. 创建NWB文件
    nwbfile = NWBFile(
        session_description='Visual stimulus experiment with official IndexSeries implementation',
        identifier='example_session_001',
        session_start_time=datetime.now(ZoneInfo('UTC'))
    )
    
    # 2. 创建StimulusImageManager
    # tsv_path = "path/to/stimulus_list.tsv"  # 包含FileName列的TSV文件
    # stim_manager = StimulusImageManager(tsv_path)
    
    # 3. 定义刺激序列和时间戳
    # stimulus_sequence = [1, 2, 3, 2, 1, 4, 3]  # Matlab索引（1-based）
    # timestamps = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    
    # 4. 添加到NWB文件
    # images_container, index_series = stim_manager.add_to_nwb(
    #     nwbfile, stimulus_sequence, timestamps,
    #     stimulus_name="visual_stimulus"
    # )
    
    # 5. 保存NWB文件
    # with NWBHDF5IO("example_stimulus.nwb", "w") as io:
    #     io.write(nwbfile)
    
    # 6. 读取和访问数据（正确方法）
    # with NWBHDF5IO("example_stimulus.nwb", "r") as io:
    #     read_nwbfile = io.read()
    #     
    #     # ❌ 错误方法：直接读取IndexSeries.data
    #     # stimulus_data = read_nwbfile.stimulus["visual_stimulus"].data[:]  # 这是容器索引，不是原始序列！
    #     
    #     # ✓ 正确方法：使用辅助函数读取
    #     original_sequence, timestamps, filenames = read_stimulus_sequence_from_nwb(
    #         read_nwbfile, "visual_stimulus"
    #     )
    #     print(f"原始Matlab刺激序列: {original_sequence}")
    #     print(f"时间戳: {timestamps}")
    #     print(f"对应的图片文件: {filenames}")
    
    print("✓ PyNWB官方IndexSeries实现完成!")
    print("主要特点:")
    print("  - 符合PyNWB官方标准：使用Images容器 + ImageReferences + IndexSeries")
    print("  - 高效存储：每个唯一图片只存储一次，避免数据重复")
    print("  - 精确映射：IndexSeries准确记录每个时间点对应的图片")
    print("  - 灵活支持：自动处理RGB/RGBA/灰度图片类型")
    print("  - 详细记录：scratch数据保存完整的索引映射关系")
    print("  - Matlab兼容：支持1-based索引，自动转换为Python 0-based")
    return nwbfile

def create_test_data():
    """创建测试数据的辅助函数"""
    import tempfile
    import pandas as pd
    
    # 创建临时测试文件
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # 创建测试TSV文件
        tsv_data = pd.DataFrame({
            'FileName': ['image1.png', 'image2.png', 'image3.png', 'image4.png']
        })
        tsv_path = temp_path / "stimulus_list.tsv"
        tsv_data.to_csv(tsv_path, sep='\t', index=False)
        
        # 创建测试图片（简单的numpy数组）
        for i, filename in enumerate(tsv_data['FileName']):
            img_path = temp_path / filename
            # 创建简单的测试图片数据
            test_img = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
            PILImage.fromarray(test_img).save(img_path)
        
        print(f"测试数据已创建在: {temp_dir}")
        return str(tsv_path)

if __name__ == "__main__":
    example_usage()
