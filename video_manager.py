# -*- coding: utf-8 -*-
"""
视频管理模块
功能：RTSP流连接、本地视频管理
"""

import cv2
import threading


class VideoManager:
    """视频管理器"""
    
    def __init__(self):
        self.rtsp_streams = {}
        self.captures = {}
        
    def connect_rtsp(self, rtsp_urls):
        """连接RTSP流"""
        for url in rtsp_urls:
            try:
                cap = cv2.VideoCapture(url)
                if cap.isOpened():
                    self.captures[url] = cap
                    self.rtsp_streams[url] = {
                        'status': 'connected',
                        'fps': cap.get(cv2.CAP_PROP_FPS),
                        'width': int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                        'height': int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    }
                else:
                    self.rtsp_streams[url] = {
                        'status': 'failed',
                        'error': '无法打开RTSP流'
                    }
            except Exception as e:
                self.rtsp_streams[url] = {
                    'status': 'error',
                    'error': str(e)
                }
                
        return self.rtsp_streams
        
    def disconnect_rtsp(self, rtsp_url=None):
        """断开RTSP流"""
        if rtsp_url and rtsp_url in self.captures:
            self.captures[rtsp_url].release()
            del self.captures[rtsp_url]
            if rtsp_url in self.rtsp_streams:
                del self.rtsp_streams[rtsp_url]
        elif rtsp_url is None:
            # 断开所有
            for url, cap in self.captures.items():
                cap.release()
            self.captures.clear()
            self.rtsp_streams.clear()
            
    def get_stream_status(self):
        """获取流状态"""
        return self.rtsp_streams.copy()
        
    def read_frame(self, rtsp_url):
        """读取一帧"""
        if rtsp_url in self.captures:
            ret, frame = self.captures[rtsp_url].read()
            if ret:
                return True, frame
            else:
                return False, None
        return False, None
        
    def upload_local_video(self, video_file, device_ip):
        """上传本地视频到设备"""
        # 这个功能在device_manager中实现
        pass
        
    def switch_video_source(self, device_ip, source_type='local'):
        """切换视频源（local或rtsp）"""
        # 这个功能在device_manager中实现
        pass
