#!/usr/bin/env python3
"""Merge detection JSON with a source video and generate an annotated video.

The script is Windows-first for the upper-computer app:
- It does not require a system ffmpeg executable.
- It uses OpenCV VideoCapture/VideoWriter by default.
- If ffmpeg is available later, it can still be used for hardware encoding.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

import numpy as np

MODEL_W, MODEL_H = 2560, 1440

NAME_COLORS_RGB = {
    "person": (0, 255, 0),
    "ball": (255, 0, 0),
    "soccer": (255, 0, 0),
    "goal": (0, 128, 255),
    "cc": (255, 255, 0),
    "centercircle": (255, 255, 0),
}

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


def load_labels(config_path=None):
    if config_path:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for mode in cfg.get("modes", []):
                for model in mode.get("models", []):
                    labels = model.get("labels")
                    if labels:
                        return labels
        except Exception:
            pass
    return ["person", "soccer", "goal", "cc"]


def get_color_rgb(cls, labels):
    name = labels[cls] if 0 <= cls < len(labels) else "?"
    return NAME_COLORS_RGB.get(name, (128, 128, 128))


def get_color_bgr(cls, labels):
    r, g, b = get_color_rgb(cls, labels)
    return b, g, r


def get_label(cls, conf, labels):
    name = labels[cls] if 0 <= cls < len(labels) else "?"
    return f"{name} {conf:.0%}"


def load_detections(json_path, total_frames=None):
    detections = {}
    max_frame = 0
    with open(json_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            boxes = obj.get("boxes", [])
            if not boxes:
                continue
            frame = int(obj["frame"])
            max_frame = max(max_frame, frame)
            detections[frame] = boxes

    if total_frames and max_frame >= total_frames:
        merged = {}
        for frame, boxes in detections.items():
            mapped = frame % total_frames
            merged.setdefault(mapped, boxes)
        print(f"Loaded {len(detections)} detection frames, mapped to {len(merged)} source frames")
        return merged

    print(f"Loaded {len(detections)} frames with detections")
    return detections


def smooth_boxes(prev_boxes, new_boxes, alpha=0.35):
    if not prev_boxes:
        return new_boxes

    result = []
    used = set()
    for nb in new_boxes:
        best_i, best_dist = -1, 100000
        for i, pb in enumerate(prev_boxes):
            if i in used or pb.get("cls") != nb.get("cls"):
                continue
            dx = (pb["x"] + pb["w"] / 2) - (nb["x"] + nb["w"] / 2)
            dy = (pb["y"] + pb["h"] / 2) - (nb["y"] + nb["h"] / 2)
            dist = dx * dx + dy * dy
            if dist < best_dist:
                best_dist = dist
                best_i = i

        if best_i >= 0 and best_dist < 200 * 200:
            used.add(best_i)
            pb = prev_boxes[best_i]
            smoothed = dict(nb)
            for key in ("x", "y", "w", "h"):
                smoothed[key] = pb[key] * alpha + nb[key] * (1 - alpha)
            smoothed["conf"] = pb.get("conf", 0) * alpha + nb.get("conf", 0) * (1 - alpha)
            result.append(smoothed)
        else:
            result.append(nb)
    return result


def draw_boxes_cv2(frame_bgr, boxes, src_w, src_h, labels):
    sx, sy = src_w / MODEL_W, src_h / MODEL_H
    for box in boxes:
        cls = int(box.get("cls", -1))
        color = get_color_bgr(cls, labels)

        x = int(box["x"] * sx)
        y = int(box["y"] * sy)
        w = int(box["w"] * sx)
        h = int(box["h"] * sy)
        x, y = max(0, x), max(0, y)
        w, h = min(w, src_w - x), min(h, src_h - y)
        if w <= 0 or h <= 0:
            continue

        x2, y2 = x + w - 1, y + h - 1
        cv2.rectangle(frame_bgr, (x, y), (x2, y2), color, 2, lineType=cv2.LINE_8)

        label = get_label(cls, float(box.get("conf", 0)), labels)
        font_scale = max(0.5, min(src_w, src_h) / 1200.0)
        thickness = 2
        (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
        ty = y - th - baseline - 4
        if ty < 0:
            ty = min(src_h - th - baseline - 3, y + h + 3)

        cv2.rectangle(
            frame_bgr,
            (x, ty),
            (min(src_w - 1, x + tw + 6), min(src_h - 1, ty + th + baseline + 5)),
            (0, 0, 0),
            -1,
        )
        cv2.putText(
            frame_bgr,
            label,
            (x + 3, ty + th + 1),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            color,
            thickness,
            lineType=cv2.LINE_8,
        )


def configure_opencv_acceleration():
    if not HAS_CV2:
        return
    try:
        cv2.setUseOptimized(True)
    except Exception:
        pass
    try:
        cv2.ocl.setUseOpenCL(True)
        print(f"OpenCV OpenCL: {cv2.ocl.useOpenCL()}")
    except Exception:
        pass


def open_capture(video_path, hwdecode="auto"):
    if not HAS_CV2:
        raise RuntimeError("缺少 opencv-python，无法在无 FFmpeg 环境下合成视频")

    configure_opencv_acceleration()
    cap = None
    if hwdecode != "none" and hasattr(cv2, "CAP_PROP_HW_ACCELERATION"):
        try:
            cap = cv2.VideoCapture(video_path, cv2.CAP_ANY, [
                cv2.CAP_PROP_HW_ACCELERATION,
                getattr(cv2, "VIDEO_ACCELERATION_ANY", 1),
            ])
        except Exception:
            cap = None
    if cap is None or not cap.isOpened():
        cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {video_path}")
    return cap


def get_video_info_opencv(video_path, hwdecode="auto"):
    cap = open_capture(video_path, hwdecode=hwdecode)
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        if fps <= 0:
            fps = 30.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) or None
        return width, height, fps, total
    finally:
        cap.release()


def create_video_writer(output_path, fps, size):
    candidates = []
    ext = os.path.splitext(output_path)[1].lower()
    if ext == ".avi":
        candidates.extend(["XVID", "MJPG"])
    else:
        candidates.extend(["mp4v", "avc1", "H264", "XVID"])

    for codec in candidates:
        writer = cv2.VideoWriter(output_path, cv2.VideoWriter_fourcc(*codec), fps, size)
        if writer.isOpened():
            print(f"OpenCV writer codec: {codec}")
            return writer
        writer.release()
    raise RuntimeError("无法创建输出视频，OpenCV 当前环境不支持可用编码器")


def merge_with_opencv(args, labels):
    src_w, src_h, fps, total_frames = get_video_info_opencv(args.video, hwdecode=args.hwdecode)
    print(f"Source: {src_w}x{src_h} @ {fps:.3f}fps")
    print(f"Total frames: {total_frames or 'unknown'}")
    print("Pipeline: OpenCV VideoCapture/VideoWriter")

    detections = load_detections(args.json, total_frames)
    cap = open_capture(args.video, hwdecode=args.hwdecode)
    writer = create_video_writer(args.output, fps, (src_w, src_h))

    frame_idx = 0
    frames_with_boxes = 0
    display_boxes = None
    last_raw = None
    held_count = 999

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            if frame_idx in detections:
                raw_boxes = detections[frame_idx]
                display_boxes = smooth_boxes(last_raw, raw_boxes)
                last_raw = raw_boxes
                held_count = 0

            if display_boxes is not None and held_count <= args.hold:
                draw_boxes_cv2(frame, display_boxes, src_w, src_h, labels)
                frames_with_boxes += 1
                held_count += 1

            writer.write(frame)
            frame_idx += 1
            if frame_idx % 100 == 0:
                print(f"\r{frame_idx} frames, {frames_with_boxes} with overlay", end="", flush=True)
    finally:
        cap.release()
        writer.release()

    print(f"\rDone: {frame_idx} frames, {frames_with_boxes} with overlay -> {args.output}")


def ffmpeg_available():
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def get_ffmpeg_encoders():
    try:
        probe = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        return probe.stdout or ""
    except Exception:
        return ""


def choose_ffmpeg_encoder(requested):
    encoders = get_ffmpeg_encoders()
    if requested and requested != "auto":
        return requested if requested in encoders or requested == "libx264" else "libx264"
    candidates = ["h264_nvenc", "h264_qsv", "h264_amf", "libx264"] if os.name == "nt" else ["h264_nvenc", "h264_qsv", "h264_vaapi", "libx264"]
    for codec in candidates:
        if codec == "libx264" or codec in encoders:
            return codec
    return "libx264"


def build_ffmpeg_encode_cmd(codec, src_w, src_h, fps, output):
    base = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{src_w}x{src_h}", "-r", str(fps),
        "-i", "pipe:0",
    ]
    if codec == "h264_nvenc":
        return base + ["-c:v", "h264_nvenc", "-preset", "p1", "-cq", "23", "-pix_fmt", "yuv420p", output]
    if codec == "h264_qsv":
        return base + ["-c:v", "h264_qsv", "-global_quality", "23", "-pix_fmt", "yuv420p", output]
    if codec == "h264_amf":
        return base + ["-c:v", "h264_amf", "-quality", "speed", "-qp_i", "23", "-qp_p", "23", "-pix_fmt", "yuv420p", output]
    return base + ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p", output]


def merge_with_opencv_decode_ffmpeg_encode(args, labels):
    src_w, src_h, fps, total_frames = get_video_info_opencv(args.video, hwdecode=args.hwdecode)
    detections = load_detections(args.json, total_frames)
    cap = open_capture(args.video, hwdecode=args.hwdecode)
    codec = choose_ffmpeg_encoder(args.encoder)
    print(f"Pipeline: OpenCV draw + FFmpeg encode")
    print(f"Encoder: {codec}")
    process = subprocess.Popen(
        build_ffmpeg_encode_cmd(codec, src_w, src_h, fps, args.output),
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    frame_idx = 0
    frames_with_boxes = 0
    display_boxes = None
    last_raw = None
    held_count = 999

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_idx in detections:
                raw_boxes = detections[frame_idx]
                display_boxes = smooth_boxes(last_raw, raw_boxes)
                last_raw = raw_boxes
                held_count = 0
            if display_boxes is not None and held_count <= args.hold:
                draw_boxes_cv2(frame, display_boxes, src_w, src_h, labels)
                frames_with_boxes += 1
                held_count += 1
            try:
                process.stdin.write(frame.tobytes())
            except BrokenPipeError:
                break
            frame_idx += 1
            if frame_idx % 100 == 0:
                print(f"\r{frame_idx} frames, {frames_with_boxes} with overlay", end="", flush=True)
    finally:
        cap.release()
        try:
            process.stdin.close()
        except Exception:
            pass

    rc = process.wait()
    err = process.stderr.read().decode(errors="ignore") if process.stderr else ""
    if rc != 0:
        raise RuntimeError(f"FFmpeg encoder failed with code {rc}\n{err}")
    print(f"\rDone: {frame_idx} frames, {frames_with_boxes} with overlay -> {args.output}")


def parse_args():
    parser = argparse.ArgumentParser(description="Merge detection JSON with video")
    parser.add_argument("json", help="Detection JSON file")
    parser.add_argument("video", help="Source video file")
    parser.add_argument("output", help="Output video file")
    parser.add_argument("--config", default=None, help="model_config.json with labels")
    parser.add_argument("--hold", type=int, default=10, help="Hold last boxes for N frames")
    parser.add_argument("--hwa", action="store_true", help="Use FFmpeg hardware encoder when ffmpeg is available")
    parser.add_argument("--encoder", default="auto", choices=["auto", "libx264", "h264_nvenc", "h264_qsv", "h264_amf"], help="FFmpeg encoder")
    parser.add_argument("--draw-backend", default="opencv", choices=["auto", "opencv"], help="Drawing backend")
    parser.add_argument("--hwdecode", default="auto", choices=["auto", "none"], help="Best-effort OpenCV hardware decode")
    return parser.parse_args()


def main():
    args = parse_args()
    if not HAS_CV2:
        print("ERROR: 缺少 opencv-python，Windows 无 FFmpeg 环境必须依赖 OpenCV")
        sys.exit(1)

    labels = load_labels(args.config)
    print(f"Labels: {labels}")
    print(f"Hold: {args.hold} frames")
    print(f"JSON: {args.json}")

    try:
        if args.hwa and ffmpeg_available():
            merge_with_opencv_decode_ffmpeg_encode(args, labels)
        else:
            if args.hwa and not ffmpeg_available():
                print("FFmpeg not found, using OpenCV fallback without external hardware encoder")
            merge_with_opencv(args, labels)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
