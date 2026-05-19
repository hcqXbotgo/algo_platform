# -*- coding: utf-8 -*-
"""
日志分析模块
功能：解析日志文件，统计推理耗时，生成可视化图表
"""

import re
import csv
import numpy as np
from collections import defaultdict


class LogAnalyzer:
    """日志分析器"""
    
    def __init__(self):
        self.data = {}
        
    def parse_log(self, log_file):
        """解析日志文件（只处理 multi_media 开头的日志行）"""
        self.data = {}
        
        infer_pattern = re.compile(r"infer spend time:(\d+\.\d+)\s*ms")
        post_process_pattern = re.compile(r"yolov5 post_process took (\d+\.\d+)\s*ms")
        detect_pattern = re.compile(r"Detection time for model \d+:\s*(\d+\.\d+)ms")
        model_pattern = re.compile(r"Loading model from:\s*([\w\d\-_\.]+\.rknn)")
        
        current_infer = None
        current_model = None
        
        def init_model(name):
            if name not in self.data:
                self.data[name] = {"infer": [], "total": []}
                
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    # 只处理 multi_media 开头的日志行
                    if not line.strip().startswith('multi_media'):
                        continue
                    
                    # 模型名 - 匹配初始化行
                    model_match = model_pattern.search(line)
                    if model_match:
                        current_model = model_match.group(1)
                        init_model(current_model)
                        continue
                        
                    # infer - 必须在有 current_model 时才记录
                    infer_match = infer_pattern.search(line)
                    if infer_match and current_model:
                        current_infer = float(infer_match.group(1))
                        continue
                        
                    # total（使用 Detection time）- 确保有 current_infer 和 current_model
                    if current_infer is not None and current_model:
                        m = detect_pattern.search(line)
                        if m:
                            self.data[current_model]["infer"].append(current_infer)
                            self.data[current_model]["total"].append(float(m.group(1)))
                            current_infer = None
                            continue
                        
                        # 也尝试匹配 post_process 时间作为备选
                        m = post_process_pattern.search(line)
                        if m:
                            # post_process 时间通常很小，这里可以选择是否记录
                            pass
                            
            return self.data
            
        except Exception as e:
            raise Exception(f"日志解析失败: {str(e)}")
            
    def analyze(self, log_file):
        """分析日志并返回统计结果"""
        self.parse_log(log_file)
        
        results = {}
        for model, d in self.data.items():
            if not d["infer"]:
                continue
                
            infer = np.array(d["infer"])
            total = np.array(d["total"])
            
            results[model] = {
                'infer_avg': float(np.mean(infer)),
                'total_avg': float(np.mean(total)),
                'total_max': float(np.max(total)),
                'infer_std': float(np.std(infer)),
                'total_std': float(np.std(total)),
                'frame_count': len(infer)
            }
            
        return results
        
    def save_csv(self, frame_csv="frame_data.csv", summary_csv="summary.csv"):
        """保存CSV文件"""
        if not self.data:
            raise Exception("没有数据可保存，请先分析日志")
            
        # 保存逐帧数据
        with open(frame_csv, "w", newline="", encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["model", "frame", "infer_ms", "total_ms"])
            
            for model, d in self.data.items():
                length = min(len(d["infer"]), len(d["total"]))
                for i in range(length):
                    writer.writerow([
                        model,
                        i + 1,
                        d["infer"][i],
                        d["total"][i]
                    ])
                    
        # 保存统计数据
        with open(summary_csv, "w", newline="", encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["model", "infer_avg", "total_avg", "total_max", "infer_std", "total_std", "frame_count"])
            
            for model, d in self.data.items():
                if not d["infer"]:
                    continue
                    
                infer = np.array(d["infer"])
                total = np.array(d["total"])
                
                writer.writerow([
                    model,
                    round(float(np.mean(infer)), 3),
                    round(float(np.mean(total)), 3),
                    round(float(np.max(total)), 3),
                    round(float(np.std(infer)), 3),
                    round(float(np.std(total)), 3),
                    len(infer)
                ])
                
    def get_plot_data(self):
        """获取用于绘图的数据"""
        return self.data.copy()
        
    def reset(self):
        """重置数据"""
        self.data = {}
