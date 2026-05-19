# -*- coding: utf-8 -*-
import re
import csv
import numpy as np
import matplotlib.pyplot as plt

log_file = "multi_media-20260515-122813-redir.log"

# =======================
# 1️ 解析日志
# =======================
data = {}

# 修改：更新正则表达式以匹配实际日志格式
infer_pattern = re.compile(r"infer spend time:(\d+\.\d+)\s*ms")
post_process_pattern = re.compile(r"yolov5 post_process took (\d+\.\d+)\s*ms")
detect_pattern = re.compile(r"Detection time for model \d+:\s*(\d+\.\d+)ms")
model_pattern = re.compile(r"Loading model from:\s*([\w\d\-_\.]+\.rknn)")

current_infer = None
current_model = None

def init_model(name):
    if name not in data:
        data[name] = {"infer": [], "total": []}

with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
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
                data[current_model]["infer"].append(current_infer)
                data[current_model]["total"].append(float(m.group(1)))
                current_infer = None
                continue
            
            # 也尝试匹配 post_process 时间作为备选
            m = post_process_pattern.search(line)
            if m:
                # post_process 时间通常很小，这里可以选择是否记录
                # 如果需要，可以单独存储
                pass

# =======================
# 2️ 保存 CSV（逐帧数据）
# =======================
with open("frame_data.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["model", "frame", "infer_ms", "total_ms"])

    for model, d in data.items():
        length = min(len(d["infer"]), len(d["total"]))
        for i in range(length):
            writer.writerow([
                model,
                i + 1,
                d["infer"][i],
                d["total"][i]
            ])

print("已生成 frame_data.csv")

# =======================
# 3️ 保存 CSV（统计数据）
# =======================
with open("summary.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["model", "infer_avg", "total_avg", "total_max"])

    for model, d in data.items():
        if not d["infer"]:
            continue

        infer = np.array(d["infer"])
        total = np.array(d["total"])

        writer.writerow([
            model,
            round(infer.mean(), 3),
            round(total.mean(), 3),
            round(total.max(), 3)
        ])

print("已生成 summary.csv")

# =======================
# 4️ 画曲线
# =======================
for model, d in data.items():
    if not d["infer"]:
        continue

    length = min(len(d["infer"]), len(d["total"]))
    infer = d["infer"][:length]
    total = d["total"][:length]

    frames = range(1, length + 1)

    plt.figure()
    plt.plot(frames, total, label="total")
    plt.plot(frames, infer, label="infer")
    plt.title(model)
    plt.xlabel("Frame")
    plt.ylabel("Time (ms)")
    plt.legend()
    plt.grid()
    plt.savefig(f"{model}.png", dpi=150, bbox_inches="tight")
    print(f"已生成 {model}.png")

plt.close()
print("所有图表生成完成！")
