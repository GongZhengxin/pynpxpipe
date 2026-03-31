"""
数据处理脚本
由 GUI 调用，用于执行完整的数据处理流程
"""
import sys
import os
from pathlib import Path
import time
import traceback
import base64
import webbrowser

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

print("=" * 60)
print("PyNeuralPipe Session Processing Script")
print("=" * 60)


def save_visualizations(visualizations, session_path, prefix):
    """
    保存可视化图表到文件
    
    Args:
        visualizations: 包含base64编码图片的字典
        session_path: session路径
        prefix: 文件名前缀
    """
    fig_dir = session_path / "processed" / "figures"
    fig_dir.mkdir(exist_ok=True, parents=True)
    
    saved_files = []
    for name, img_base64 in visualizations.items():
        try:
            # 解码base64图片
            img_data = base64.b64decode(img_base64)
            
            # 保存到文件
            fig_path = fig_dir / f"{prefix}_{name}.png"
            fig_path.write_bytes(img_data)
            
            print(f"  ✓ {fig_path}")
            saved_files.append(fig_path)
            
        except Exception as e:
            print(f"  ⚠ Failed to save {name}: {str(e)}")
    
    return saved_files


def save_bombcell_figures(figures, session_path):
    """
    保存Bombcell生成的matplotlib图表
    
    Args:
        figures: matplotlib figure对象列表
        session_path: session路径
    """
    import matplotlib.pyplot as plt
    
    fig_dir = session_path / "processed" / "figures" / "bombcell"
    fig_dir.mkdir(exist_ok=True, parents=True)
    
    saved_files = []
    for i, fig in enumerate(figures):
        try:
            fig_path = fig_dir / f"bombcell_qc_{i+1}.png"
            fig.savefig(fig_path, dpi=150, bbox_inches='tight')
            print(f"  ✓ {fig_path}")
            saved_files.append(fig_path)
            plt.close(fig)
        except Exception as e:
            print(f"  ⚠ Failed to save figure {i+1}: {str(e)}")
    
    return saved_files


def generate_html_report(session_path, processing_results):
    """
    生成HTML处理报告
    
    Args:
        session_path: session路径
        processing_results: 处理结果字典
    """
    report_path = session_path / "processed" / "processing_report.html"
    
    # 收集所有图片
    fig_dir = session_path / "processed" / "figures"
    
    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Processing Report - {session_path.name}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #555;
            margin-top: 30px;
            border-bottom: 2px solid #ddd;
            padding-bottom: 5px;
        }}
        .summary {{
            background: white;
            padding: 20px;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin: 20px 0;
        }}
        .metric {{
            display: inline-block;
            margin: 10px 20px 10px 0;
        }}
        .metric-label {{
            font-weight: bold;
            color: #666;
        }}
        .metric-value {{
            color: #4CAF50;
            font-size: 1.2em;
        }}
        .figure {{
            background: white;
            padding: 20px;
            margin: 20px 0;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .figure img {{
            max-width: 100%;
            height: auto;
        }}
        .status {{
            display: inline-block;
            padding: 5px 10px;
            border-radius: 3px;
            font-weight: bold;
        }}
        .status-success {{
            background-color: #d4edda;
            color: #155724;
        }}
        .status-warning {{
            background-color: #fff3cd;
            color: #856404;
        }}
        .footer {{
            margin-top: 50px;
            text-align: center;
            color: #999;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <h1>🧠 PyNeuralPipe Processing Report</h1>
    
    <div class="summary">
        <h2>Session Information</h2>
        <div class="metric">
            <span class="metric-label">Session:</span>
            <span class="metric-value">{session_path.name}</span>
        </div>
        <div class="metric">
            <span class="metric-label">Processed:</span>
            <span class="metric-value">{processing_results.get('timestamp', 'N/A')}</span>
        </div>
        <div class="metric">
            <span class="metric-label">Status:</span>
            <span class="status status-success">✓ Completed</span>
        </div>
    </div>
    
    <div class="summary">
        <h2>📊 Processing Summary</h2>
        <div class="metric">
            <span class="metric-label">Total Trials:</span>
            <span class="metric-value">{processing_results.get('total_trials', 'N/A')}</span>
        </div>
        <div class="metric">
            <span class="metric-label">Valid Onsets:</span>
            <span class="metric-value">{processing_results.get('valid_onsets', 'N/A')}</span>
        </div>
        <div class="metric">
            <span class="metric-label">Unique Stimuli:</span>
            <span class="metric-value">{processing_results.get('unique_stimuli', 'N/A')}</span>
        </div>
"""
    
    # 添加 Kilosort 结果（如果有）
    if processing_results.get('kilosort_completed'):
        html_content += f"""
        <div class="metric">
            <span class="metric-label">Total Units:</span>
            <span class="metric-value">{processing_results.get('total_units', 'N/A')}</span>
        </div>
"""
    
    # 添加 Quality Control 结果（如果有）
    if processing_results.get('qc_completed'):
        html_content += f"""
        <div class="metric">
            <span class="metric-label">Good Units:</span>
            <span class="metric-value">{processing_results.get('good_units', 'N/A')}</span>
        </div>
"""
    
    html_content += """
    </div>
"""
    
    # 添加同步可视化
    if fig_dir.exists():
        sync_figs = list(fig_dir.glob("sync_*.png"))
        if sync_figs:
            html_content += """
    <h2>🔄 Synchronization Check</h2>
"""
            for fig_path in sorted(sync_figs):
                rel_path = fig_path.relative_to(session_path / "processed")
                html_content += f"""
    <div class="figure">
        <h3>{fig_path.stem.replace('_', ' ').title()}</h3>
        <img src="{rel_path}" alt="{fig_path.stem}">
    </div>
"""
        
        # 添加 Bombcell 可视化
        bc_fig_dir = fig_dir / "bombcell"
        if bc_fig_dir.exists():
            bc_figs = list(bc_fig_dir.glob("bombcell_*.png"))
            if bc_figs:
                html_content += """
    <h2>✅ Quality Control (Bombcell)</h2>
"""
                for fig_path in sorted(bc_figs):
                    rel_path = fig_path.relative_to(session_path / "processed")
                    html_content += f"""
    <div class="figure">
        <h3>{fig_path.stem.replace('_', ' ').title()}</h3>
        <img src="{rel_path}" alt="{fig_path.stem}">
    </div>
"""
    
    html_content += f"""
    <div class="footer">
        <p>Generated by PyNeuralPipe | {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
</body>
</html>
"""
    
    # 保存HTML文件
    report_path.write_text(html_content, encoding='utf-8')
    print(f"📄 HTML report generated: {report_path}")
    
    return report_path


def main():
    if len(sys.argv) < 2:
        print("❌ Error: No session path provided!")
        print("Usage: python process_session.py <session_path>")
        sys.exit(1)
    
    session_path = Path(sys.argv[1])
    
    if not session_path.exists():
        print(f"❌ Error: Session path does not exist: {session_path}")
        sys.exit(1)
    
    print(f"📁 Session Path: {session_path}")
    print()
    
    try:
        # 导入所需模块
        print("📦 Importing modules...")
        from core.data_loader import DataLoader
        from core.synchronizer import DataSynchronizer
        from core.spike_sorter import SpikeSorter
        from core.quality_controller import QualityController
        from core.data_integrator import DataIntegrator
        print("✓ Modules imported successfully\n")
        
        # Step 0: 检查 session 结构
        print("=" * 60)
        print("STEP 0: Checking Session Structure")
        print("=" * 60)
        
        # 查找 NPX 文件夹
        npx_folders = list(session_path.glob("NPX_*_g*"))
        if not npx_folders:
            print("❌ No NPX folder found! Looking for folders with .bin files...")
            for folder in session_path.iterdir():
                if folder.is_dir():
                    bin_files = list(folder.glob("*.bin"))
                    if bin_files:
                        npx_folders = [folder]
                        break
        
        if not npx_folders:
            print("❌ Error: No SpikeGLX data folder found!")
            sys.exit(1)
        
        spikeglx_folder = npx_folders[0]
        print(f"✓ Found SpikeGLX folder: {spikeglx_folder.name}")
        
        # 查找 bhv2 文件
        bhv2_files = list(session_path.glob("*.bhv2"))
        if bhv2_files:
            print(f"✓ Found MonkeyLogic file: {bhv2_files[0].name}")
        else:
            print("⚠ Warning: No .bhv2 file found")
        
        # 检查是否有 processed 文件夹
        processed_path = session_path / "processed"
        if processed_path.exists():
            print(f"✓ Found processed folder")
            
            # 检查 Kilosort 结果
            ks_path = processed_path / "SI" / "KS4" / "sorter_output"
            if ks_path.exists():
                print(f"  ✓ Kilosort results exist")
            else:
                print(f"  ⚠ Kilosort results not found")
            
            # 检查 Bombcell 结果
            bc_path = processed_path / "SI" / "bombcell"
            if bc_path.exists():
                print(f"  ✓ Bombcell results exist")
            else:
                print(f"  ⚠ Bombcell results not found")
            
            # 检查 META 文件
            meta_files = list(processed_path.glob("META_*.h5"))
            if meta_files:
                print(f"  ✓ META file exists: {meta_files[0].name}")
            else:
                print(f"  ⚠ META file not found")
        else:
            print("⚠ No processed folder found - will create during processing")
        
        print()
        
        # Step 1: 数据加载
        print("=" * 60)
        print("STEP 1: Loading Data")
        print("=" * 60)
        
        data_loader = DataLoader(session_path)
        
        print("Loading SpikeGLX data...")
        data_loader.load_spikeglx()
        neural_data = data_loader.get_spikeglx_data()
        print("✓ SpikeGLX data loaded")
        
        print("Loading MonkeyLogic data...")
        data_loader.load_monkeylogic()
        monkeylogic_data = data_loader.get_monkeylogic_data()
        print("✓ MonkeyLogic data loaded")
        
        sync_data = data_loader.get_sync_data()
        metadata = data_loader.get_metadata()
        print(f"✓ Data loaded: {len(sync_data)} sync channels, {len(metadata)} metadata fields\n")
        
        # Step 2: 数据同步
        print("=" * 60)
        print("STEP 2: Data Synchronization")
        print("=" * 60)
        
        synchronizer = DataSynchronizer(data_loader)
        synchronizer.process_full_synchronization()
        export_data = synchronizer.get_export_data()
        print(f"✓ Synchronization complete: {len(export_data)} data fields exported")
        
        # 保存可视化图表
        sync_visualizations = synchronizer.get_visualizations()
        if sync_visualizations:
            print("📊 Saving synchronization visualizations...")
            save_visualizations(sync_visualizations, session_path, "sync")
        print()
        
        # Step 3: Spike Sorting (如果还没有运行过)
        print("=" * 60)
        print("STEP 3: Spike Sorting (Optional)")
        print("=" * 60)
        
        ks_output_path = processed_path / "SI" / "KS4" / "sorter_output"
        if ks_output_path.exists():
            print("✓ Kilosort results already exist, skipping spike sorting")
        else:
            print("⚠ Kilosort results not found")
            print("ℹ You can run spike sorting now (time-consuming, requires GPU)")
            print("  Or skip and run it manually later")
            
            # 询问是否运行 Kilosort（通过环境变量控制）
            run_kilosort = os.environ.get('RUN_KILOSORT', 'no').lower() in ['yes', 'y', '1', 'true']
            
            if run_kilosort:
                print("\n🚀 Starting Kilosort spike sorting...")
                try:
                    from core.spike_sorter import SpikeSorter
                    
                    # 使用已加载的 neural_data
                    spike_sorter = SpikeSorter.from_recording(neural_data)
                    
                    # 运行完整的 spike sorting pipeline
                    output_folder = processed_path / "SI" / "KS4"
                    spike_sorter.run_full_pipeline(output_folder=str(output_folder))
                    
                    print(f"✓ Kilosort completed: {output_folder}")
                    
                    # 获取排序摘要
                    summary = spike_sorter.get_summary_stats()
                    print(f"  Total units: {summary.get('num_units', 'N/A')}")
                    print(f"  Total spikes: {summary.get('total_spikes', 'N/A')}")
                    
                except Exception as e:
                    print(f"⚠ Kilosort failed: {str(e)}")
                    print("  Continuing with remaining steps...")
                    traceback.print_exc()
            else:
                print("  Skipping Kilosort (set RUN_KILOSORT=yes to enable)")
        print()
        
        # Step 4: 质量控制
        print("=" * 60)
        print("STEP 4: Quality Control")
        print("=" * 60)
        
        if ks_output_path.exists():
            imec_path = spikeglx_folder / f"{spikeglx_folder.name}_imec0"
            
            quality_controller = QualityController(
                kilosort_output_path=ks_output_path,
                imec_data_path=imec_path
            )
            
            bc_params = quality_controller.setup_bombcell_params()
            print("✓ Bombcell parameters set up")
            
            bombcell_results = quality_controller.run_quality_control()
            print(f"✓ Quality control complete")
            print(f"  Total units: {bombcell_results.get('total_units', 'N/A')}")
            print(f"  Good units: {bombcell_results.get('good_units', 'N/A')}")
            
            # 保存 Bombcell 可视化图表
            bc_figures = quality_controller.get_bombcell_figures()
            if bc_figures:
                print("📊 Saving quality control visualizations...")
                save_bombcell_figures(bc_figures, session_path)
        else:
            print("⚠ Skipping quality control (no Kilosort results)")
        print()
        
        # Step 5: NWB 数据整合
        print("=" * 60)
        print("STEP 5: NWB Data Integration")
        print("=" * 60)
        
        # 检查是否有 nwbsession_template.yaml
        session_config = session_path / "nwbsession_template.yaml"
        if not session_config.exists():
            print(f"⚠ Warning: {session_config} not found")
            print("  Using default template from config directory")
            session_config = None
        else:
            print(f"✓ Using session config: {session_config}")
        
        # 查找 subject config（假设在 config 目录下）
        config_dir = Path(__file__).parent / "config"
        subject_configs = list(config_dir.glob("*.yaml"))
        # 过滤掉非 subject 配置文件
        subject_configs = [f for f in subject_configs if f.stem not in [
            "nwbsession_template", "nwb_template", "app", "ui",
            "data_loader", "synchronizer", "spike_sorter",
            "quality_controller", "data_integrator"
        ]]
        
        if subject_configs:
            subject_config = subject_configs[0].stem
            print(f"✓ Using subject config: {subject_config}.yaml")
        else:
            print("⚠ No subject config found, using default")
            subject_config = None
        
        # 运行数据整合
        try:
            from core.data_integrator import integrate_data
            
            output_file = integrate_data(
                data_path=str(session_path),
                subject_config=subject_config,
                electrode_location=None  # 可以从配置中读取
            )
            
            print(f"✓ NWB file created: {output_file}")
        except Exception as e:
            print(f"⚠ Data integration encountered an error: {str(e)}")
            print("  This might be expected if some data is missing")
            traceback.print_exc()
        
        print()
        
        # 完成 - 生成HTML报告
        print("=" * 60)
        print("✓✓✓ ALL STEPS COMPLETED ✓✓✓")
        print("=" * 60)
        print(f"Session: {session_path.name}")
        print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # 收集处理结果
        processing_results = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'total_trials': monkeylogic_data.get('num_trials', 'N/A'),
            'valid_onsets': export_data.get('trial_validation', {}).get('valid_trial_count', 'N/A'),
            'unique_stimuli': export_data.get('session_info', {}).get('imgset_size', 'N/A'),
            'kilosort_completed': ks_output_path.exists(),
            'qc_completed': False,
        }
        
        # 如果运行了 Kilosort 和 QC，添加结果
        if ks_output_path.exists():
            try:
                cluster_info = ks_output_path / 'cluster_info.tsv'
                if cluster_info.exists():
                    import pandas as pd
                    df = pd.read_csv(cluster_info, sep='\t')
                    processing_results['total_units'] = len(df)
                    
                    # 检查是否有 Bombcell 结果
                    bc_results_file = processed_path / "SI" / "bombcell" / "bombcell_results.json"
                    if bc_results_file.exists():
                        import json
                        with open(bc_results_file, 'r') as f:
                            bc_data = json.load(f)
                            processing_results['good_units'] = bc_data.get('good_units', 'N/A')
                            processing_results['qc_completed'] = True
            except Exception as e:
                print(f"⚠ Warning: Could not load unit statistics: {e}")
        
        # 生成HTML报告
        print()
        print("=" * 60)
        print("Generating HTML Report")
        print("=" * 60)
        
        try:
            report_path = generate_html_report(session_path, processing_results)
            
            # 自动在浏览器打开报告
            print(f"🌐 Opening report in browser...")
            webbrowser.open(f"file:///{report_path}")
            
        except Exception as e:
            print(f"⚠ Warning: Failed to generate HTML report: {e}")
            traceback.print_exc()
        
        print()
        sys.exit(0)
        
    except Exception as e:
        print()
        print("=" * 60)
        print("❌❌❌ ERROR OCCURRED ❌❌❌")
        print("=" * 60)
        print(f"Error: {str(e)}")
        print()
        print("Traceback:")
        traceback.print_exc()
        print()
        sys.exit(1)


if __name__ == "__main__":
    main()

