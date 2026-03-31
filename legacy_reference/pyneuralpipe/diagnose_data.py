"""
数据诊断脚本 - 用于检查 MonkeyLogic 数据解析后的格式是否正确

使用方法：
    from diagnose_data import diagnose_monkeylogic_data
    diagnose_monkeylogic_data(data_loader.get_monkeylogic_data())
"""

import numpy as np
from typing import Dict, Any


def diagnose_monkeylogic_data(monkeylogic_data: Dict[str, Any], verbose: bool = True) -> Dict[str, Any]:
    """
    诊断 MonkeyLogic 数据的格式和类型
    
    Args:
        monkeylogic_data: DataLoader.get_monkeylogic_data() 返回的数据
        verbose: 是否打印详细信息
    
    Returns:
        诊断报告字典
    """
    report = {
        'status': 'OK',
        'issues': [],
        'warnings': [],
        'summary': {}
    }
    
    if not monkeylogic_data:
        report['status'] = 'ERROR'
        report['issues'].append("monkeylogic_data 为空")
        return report
    
    num_trials = monkeylogic_data.get('num_trials', 0)
    report['summary']['num_trials'] = num_trials
    
    if verbose:
        print(f"=" * 60)
        print(f"MonkeyLogic 数据诊断报告")
        print(f"=" * 60)
        print(f"总试次数: {num_trials}")
    
    # 检查 BehavioralCodes
    bc = monkeylogic_data.get('BehavioralCodes', {})
    code_times = bc.get('CodeTimes', [])
    code_numbers = bc.get('CodeNumbers', [])
    
    if verbose:
        print(f"\n--- BehavioralCodes ---")
        print(f"CodeTimes 长度: {len(code_times)}")
        print(f"CodeNumbers 长度: {len(code_numbers)}")
    
    # 检查每个试次的数据类型
    issues_by_trial = []
    for i in range(min(num_trials, len(code_numbers))):
        cn = code_numbers[i]
        ct = code_times[i]
        
        cn_type = type(cn).__name__
        ct_type = type(ct).__name__
        
        # 检查是否是正确的格式
        cn_ok = isinstance(cn, (list, np.ndarray))
        ct_ok = isinstance(ct, (list, np.ndarray))
        
        # 检查 numpy 数组的维度
        if isinstance(cn, np.ndarray):
            if cn.ndim == 0:
                cn_ok = False
                issues_by_trial.append(f"Trial {i}: CodeNumbers 是 0d 数组")
        if isinstance(ct, np.ndarray):
            if ct.ndim == 0:
                ct_ok = False
                issues_by_trial.append(f"Trial {i}: CodeTimes 是 0d 数组")
        
        if not cn_ok or not ct_ok:
            if i < 5:  # 只打印前5个问题
                if verbose:
                    print(f"  Trial {i}:")
                    print(f"    CodeNumbers: type={cn_type}, shape={getattr(cn, 'shape', 'N/A')}, ndim={getattr(cn, 'ndim', 'N/A')}")
                    print(f"    CodeTimes: type={ct_type}, shape={getattr(ct, 'shape', 'N/A')}, ndim={getattr(ct, 'ndim', 'N/A')}")
    
    if issues_by_trial:
        report['status'] = 'ERROR'
        report['issues'].extend(issues_by_trial)
        if verbose:
            print(f"\n⚠️ 发现 {len(issues_by_trial)} 个格式问题!")
    else:
        if verbose:
            print(f"  ✓ 所有试次的 CodeNumbers 和 CodeTimes 格式正确")
    
    # 检查第一个试次的详细信息
    if num_trials > 0 and len(code_numbers) > 0:
        first_cn = code_numbers[0]
        if verbose:
            print(f"\n--- 第一个试次详细信息 ---")
            print(f"  CodeNumbers[0]: type={type(first_cn).__name__}")
            if isinstance(first_cn, (list, np.ndarray)):
                arr = np.asarray(first_cn)
                print(f"    shape: {arr.shape}")
                print(f"    dtype: {arr.dtype}")
                print(f"    前5个值: {arr[:5].tolist() if len(arr) >= 5 else arr.tolist()}")
            else:
                print(f"    值: {first_cn}")
    
    # 检查 VariableChanges
    vc = monkeylogic_data.get('VariableChanges', {})
    if verbose:
        print(f"\n--- VariableChanges ---")
        print(f"  可用字段: {list(vc.keys())}")
    
    onset_time = vc.get('onset_time', [])
    if onset_time:
        sample_values = onset_time[:5]
        sample_types = [type(v).__name__ for v in sample_values]
        if verbose:
            print(f"  onset_time 前5个值: {sample_values}")
            print(f"  onset_time 类型: {sample_types}")
        
        # 检查是否有 float 但应该是 int 的情况
        for i, v in enumerate(sample_values):
            if isinstance(v, float) and v == int(v):
                report['warnings'].append(f"onset_time[{i}] 是 float ({v}) 但应该是 int")
    
    # 检查 UserVars
    uv = monkeylogic_data.get('UserVars', {})
    if verbose:
        print(f"\n--- UserVars ---")
        print(f"  可用字段: {list(uv.keys())}")
    
    # 检查 AnalogData
    ad = monkeylogic_data.get('AnalogData', {})
    if verbose:
        print(f"\n--- AnalogData ---")
        print(f"  可用字段: {list(ad.keys())}")
    
    # 检查 Eye 数据的形状
    eye_data_list = ad.get('Eye', [])
    if eye_data_list:
        if verbose:
            print(f"  Eye 数据试次数: {len(eye_data_list)}")
        
        # 检查前几个试次的 Eye 数据形状
        eye_shapes = []
        eye_issues = []
        for i, eye in enumerate(eye_data_list[:10]):
            if eye is None:
                eye_shapes.append(None)
            elif isinstance(eye, np.ndarray):
                eye_shapes.append(eye.shape)
                # 检查形状是否正确 (应该是 (num_samples, 2))
                if len(eye.shape) != 2:
                    eye_issues.append(f"Trial {i}: Eye 维度错误 {eye.shape}")
                elif eye.shape[1] != 2:
                    eye_issues.append(f"Trial {i}: Eye 列数应为2，实际为 {eye.shape[1]}")
            else:
                eye_shapes.append(f"类型错误: {type(eye).__name__}")
        
        if verbose:
            print(f"  前10个试次 Eye 形状: {eye_shapes}")
        
        if eye_issues:
            report['status'] = 'ERROR'
            report['issues'].extend(eye_issues)
            if verbose:
                print(f"  ⚠️ Eye 数据问题:")
                for issue in eye_issues:
                    print(f"    - {issue}")
        else:
            if verbose:
                print(f"  ✓ Eye 数据形状正确")
    
    # 总结
    if verbose:
        print(f"\n" + "=" * 60)
        print(f"诊断结果: {report['status']}")
        if report['issues']:
            print(f"问题数: {len(report['issues'])}")
            for issue in report['issues'][:10]:
                print(f"  - {issue}")
        if report['warnings']:
            print(f"警告数: {len(report['warnings'])}")
            for warning in report['warnings'][:10]:
                print(f"  - {warning}")
        print(f"=" * 60)
    
    return report


def check_array_compatibility(val: Any, name: str = "value") -> bool:
    """
    检查值是否可以安全用于 np.where 操作
    """
    if val is None:
        print(f"{name}: None")
        return False
    
    if isinstance(val, np.ndarray):
        if val.ndim == 0:
            print(f"{name}: 0d numpy 数组 (标量), 值={val.item()}")
            return False
        print(f"{name}: numpy 数组, shape={val.shape}, dtype={val.dtype}")
        return True
    
    if isinstance(val, list):
        print(f"{name}: 列表, 长度={len(val)}")
        return True
    
    if isinstance(val, (int, float, np.integer, np.floating)):
        print(f"{name}: 标量, 类型={type(val).__name__}, 值={val}")
        return False
    
    print(f"{name}: 未知类型 {type(val).__name__}")
    return False


if __name__ == "__main__":
    # 示例用法
    print("使用方法:")
    print("  from diagnose_data import diagnose_monkeylogic_data")
    print("  diagnose_monkeylogic_data(data_loader.get_monkeylogic_data())")
