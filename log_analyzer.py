# -*- coding: utf-8 -*-
"""
日志分析模块
功能：解析日志文件，统计推理耗时，生成可视化图表
"""

import re
import csv
import numpy as np
from collections import deque
from collections import defaultdict


class LogAnalyzer:
    """日志分析器"""
    
    def __init__(self):
        self.data = {}
        
    def parse_log(self, log_file):
        """解析日志文件"""
        self.data = {}
        
        number_pattern = r"\d+(?:\.\d+)?"
        infer_pattern = re.compile(
            rf"infer spend time:\s*(?P<time>{number_pattern})\s*ms",
            re.IGNORECASE,
        )
        post_process_pattern = re.compile(
            rf"yolov5 post_process took ({number_pattern})\s*ms",
            re.IGNORECASE,
        )
        detect_pattern = re.compile(
            rf"Detection time for model (?P<model_id>\d+):\s*"
            rf"(?P<time>{number_pattern})\s*ms",
            re.IGNORECASE,
        )
        model_pattern = re.compile(
            r"(?:Loading model from:|init ok:)\s*(\S+)",
            re.IGNORECASE,
        )
        timestamp_pattern = re.compile(
            r"(?P<hour>\d{2}):(?P<minute>\d{2}):"
            r"(?P<second>\d{2})(?:\.(?P<fraction>\d+))?"
        )
        
        pending_infers = deque()
        known_models = []
        last_clock_seconds = None
        day_offset = 0.0
        
        def init_model(name):
            if name not in self.data:
                self.data[name] = {"infer": [], "total": [], "infer_timestamps": []}

        def remember_model(path):
            name = path.replace("\\", "/").rsplit("/", 1)[-1]
            if name and name not in known_models:
                known_models.append(name)

        def parse_timestamp(match):
            nonlocal last_clock_seconds, day_offset
            fraction = match.group("fraction") or ""
            fraction_seconds = float(f"0.{fraction}") if fraction else 0.0
            clock_seconds = (
                int(match.group("hour")) * 3600
                + int(match.group("minute")) * 60
                + int(match.group("second"))
                + fraction_seconds
            )
            if last_clock_seconds is not None and clock_seconds < last_clock_seconds - 43200:
                day_offset += 86400.0
            last_clock_seconds = clock_seconds
            return day_offset + clock_seconds
                
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    # 模型名 - 匹配初始化行
                    model_match = model_pattern.search(line)
                    if model_match:
                        remember_model(model_match.group(1))
                        
                    # infer 与后续 Detection 行配对，不依赖模型文件后缀。
                    infer_match = infer_pattern.search(line)
                    if infer_match:
                        timestamp_matches = list(timestamp_pattern.finditer(line, 0, infer_match.start()))
                        infer_timestamp = (
                            parse_timestamp(timestamp_matches[-1])
                            if timestamp_matches else None
                        )
                        pending_infers.append(
                            (float(infer_match.group("time")), infer_timestamp)
                        )
                        
                    # Detection 行携带模型序号，用它完成配对并进行分组。
                    if pending_infers:
                        m = detect_pattern.search(line)
                        if m:
                            current_infer, current_infer_timestamp = pending_infers.popleft()
                            model_id = int(m.group("model_id"))
                            model_name = (
                                known_models[model_id]
                                if model_id < len(known_models)
                                else f"model_{model_id}"
                            )
                            init_model(model_name)
                            self.data[model_name]["infer"].append(current_infer)
                            self.data[model_name]["total"].append(float(m.group("time")))
                            if current_infer_timestamp is not None:
                                self.data[model_name]["infer_timestamps"].append(current_infer_timestamp)
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
            timestamps = d.get("infer_timestamps", [])
            measured_fps = None
            if len(timestamps) >= 2:
                elapsed = timestamps[-1] - timestamps[0]
                if elapsed > 0:
                    measured_fps = (len(timestamps) - 1) / elapsed
            
            results[model] = {
                'infer_avg': float(np.mean(infer)),
                'total_avg': float(np.mean(total)),
                'total_max': float(np.max(total)),
                'infer_std': float(np.std(infer)),
                'total_std': float(np.std(total)),
                'frame_count': len(infer),
                'measured_fps': measured_fps,
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
            writer.writerow([
                "model", "infer_avg", "total_avg", "total_max", "infer_std",
                "total_std", "frame_count", "measured_infer_fps"
            ])
            
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
                    len(infer),
                    self._calculate_measured_fps(d)
                ])
                
    def get_plot_data(self):
        """获取用于绘图的数据"""
        return self.data.copy()

    @staticmethod
    def _calculate_measured_fps(model_data):
        timestamps = model_data.get("infer_timestamps", [])
        if len(timestamps) < 2:
            return ""
        elapsed = timestamps[-1] - timestamps[0]
        return round((len(timestamps) - 1) / elapsed, 3) if elapsed > 0 else ""
        
    def reset(self):
        """重置数据"""
        self.data = {}
