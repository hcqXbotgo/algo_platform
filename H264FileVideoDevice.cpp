#include "H264FileVideoDevice.hpp"

#include <chrono>
#include <cstring>
#include <filesystem>

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/imgutils.h>
#include <libswscale/swscale.h>
}

// RGA hardware color conversion (used by RGA_CSC mode)
#include <im2d.h>
#include <rga.h>

#include "xbot_log.h"
#include "cJSON.h"

// ─── MPP bridge API (implemented in MppDecoder.cpp, isolated from Rk_MPI) ────
extern "C" {
void* mpp_decoder_create(const char* videoPath, int outW, int outH, uint8_t* outBuf);
void  mpp_decoder_destroy(void* handle);
void  mpp_decoder_reset(void* handle);
int   mpp_decoder_get_frame(void* handle, int64_t* outPts);
}

// ─── Decode mode from environment ───────────────────────────────────────────
static DecodeMode detectDecodeMode() {
    const char* env = getenv("DECODE_MODE");
    if (!env) return DecodeMode::SOFTWARE;
    std::string s(env);
    if (s == "rga" || s == "RGA" || s == "rga_csc" || s == "RGA_CSC") return DecodeMode::RGA_CSC;
    if (s == "mpp" || s == "MPP" || s == "mpp_vdec" || s == "MPP_VDEC") return DecodeMode::MPP_VDEC;
    return DecodeMode::SOFTWARE;
}

// ─── Constructor & Destructor ───────────────────────────────────────────────

H264FileVideoDevice::H264FileVideoDevice(const std::string& videoDir)
    : decodeMode(detectDecodeMode())
{
    frame.vir_addr = nullptr;
    frame.phy_addr = 0;
    frame.size = 0;
    frame.pts = 0;
    frame.pri_info = nullptr;

    findVideoFile(videoDir);

    ops.frame_get = [](vpss_obj_t* o, vpss_frame_t** outFrame) {
        return reinterpret_cast<H264FileVideoDevice*>(o)->onFrameGet(o, outFrame);
    };
    ops.frame_put = [](vpss_obj_t* o, vpss_frame_t* f) {
        return reinterpret_cast<H264FileVideoDevice*>(o)->onFramePut(o, f);
    };
    ops.init = [](vpss_obj_t* o, vpss_user_param_t* param) {
        return reinterpret_cast<H264FileVideoDevice*>(o)->onInit(o, param);
    };
    ops.deinit = [](vpss_obj_t* o) {
        return reinterpret_cast<H264FileVideoDevice*>(o)->onDeinit(o);
    };
    ops.start = [](vpss_obj_t* o) {
        return reinterpret_cast<H264FileVideoDevice*>(o)->onStart(o);
    };
    ops.stop = [](vpss_obj_t* o) {
        return reinterpret_cast<H264FileVideoDevice*>(o)->onStop(o);
    };
    ops.focus = [](int /*vpssGrp*/, int /*x*/, int /*y*/, unsigned int /*w*/, unsigned int /*h*/) {
        return 0;
    };

    obj.ops = &ops;
}

H264FileVideoDevice::~H264FileVideoDevice() {
    if (isRunning) {
        isRunning = false;
        frameCv.notify_all();
        decodeCv.notify_all();
        if (decodeThread.joinable()) {
            decodeThread.join();
        }
    }
    if (decodeMode == DecodeMode::MPP_VDEC) {
        if (mppHandle) {
            mpp_decoder_destroy(mppHandle);
            mppHandle = nullptr;
        }
    } else {
        closeVideo();
    }
}

// ─── File discovery ─────────────────────────────────────────────────────────

void H264FileVideoDevice::findVideoFile(const std::string& dir) {
    const char* envPath = getenv("H264_VIDEO_PATH");
    if (envPath && envPath[0] != '\0') {
        videoPath = envPath;
        log_info("Using video file from env: %s\n", videoPath.c_str());
        return;
    }

    try {
        for (const auto& entry : std::filesystem::directory_iterator(dir)) {
            if (entry.is_regular_file()) {
                auto ext = entry.path().extension().string();
                if (ext == ".h264" || ext == ".264" || ext == ".h265" || ext == ".265" ||
                    ext == ".hevc" || ext == ".mp4" || ext == ".ts") {
                    videoPath = entry.path().string();
                    log_info("Found video file: %s\n", videoPath.c_str());
                    return;
                }
            }
        }
    } catch (const std::exception& e) {
        log_error("Failed to scan directory %s: %s\n", dir.c_str(), e.what());
    }

    log_error("No video file found in %s\n", dir.c_str());
}

// ─── FFmpeg open/close (SOFTWARE and RGA_CSC modes) ─────────────────────────

bool H264FileVideoDevice::openVideo() {
    if (videoPath.empty()) {
        log_error("No video file path configured\n");
        return false;
    }

    if (avformat_open_input(&fmtCtx, videoPath.c_str(), nullptr, nullptr) < 0) {
        log_error("Failed to open video: %s\n", videoPath.c_str());
        return false;
    }

    if (avformat_find_stream_info(fmtCtx, nullptr) < 0) {
        log_error("Failed to find stream info\n");
        closeVideo();
        return false;
    }

    videoStreamIdx = -1;
    for (unsigned int i = 0; i < fmtCtx->nb_streams; i++) {
        if (fmtCtx->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO) {
            videoStreamIdx = i;
            break;
        }
    }
    if (videoStreamIdx < 0) {
        log_error("No video stream found\n");
        closeVideo();
        return false;
    }

    AVCodecParameters* codecPar = fmtCtx->streams[videoStreamIdx]->codecpar;
    const AVCodec* codec = avcodec_find_decoder(codecPar->codec_id);
    if (!codec) {
        log_error("Decoder not found for codec_id: %d\n", codecPar->codec_id);
        closeVideo();
        return false;
    }

    codecCtx = avcodec_alloc_context3(codec);
    if (!codecCtx) {
        log_error("Failed to allocate codec context\n");
        closeVideo();
        return false;
    }

    if (avcodec_parameters_to_context(codecCtx, codecPar) < 0) {
        log_error("Failed to copy codec params\n");
        closeVideo();
        return false;
    }

    if (avcodec_open2(codecCtx, codec, nullptr) < 0) {
        log_error("Failed to open codec\n");
        closeVideo();
        return false;
    }

    avFrame = av_frame_alloc();
    rgbFrame = av_frame_alloc();
    pkt = av_packet_alloc();

    if (!avFrame || !rgbFrame || !pkt) {
        log_error("Failed to allocate frames/packet\n");
        closeVideo();
        return false;
    }

    return true;
}

void H264FileVideoDevice::closeVideo() {
    if (swsCtx) {
        sws_freeContext(swsCtx);
        swsCtx = nullptr;
    }
    if (rgbFrame) {
        av_frame_free(&rgbFrame);
        rgbFrame = nullptr;
    }
    if (avFrame) {
        av_frame_free(&avFrame);
        avFrame = nullptr;
    }
    if (pkt) {
        av_packet_free(&pkt);
        pkt = nullptr;
    }
    if (codecCtx) {
        avcodec_free_context(&codecCtx);
        codecCtx = nullptr;
    }
    if (fmtCtx) {
        avformat_close_input(&fmtCtx);
        fmtCtx = nullptr;
    }
    videoStreamIdx = -1;
    nv12Buffer.clear();
}

// ─── Decode: Software path (FFmpeg + sws_scale) ─────────────────────────────

bool H264FileVideoDevice::decodeNextFrameSoftware() {
    int dstW = (int)targetSize.first;
    int dstH = (int)targetSize.second;

    while (true) {
        int ret = av_read_frame(fmtCtx, pkt);
        if (ret < 0) {
            if (ret == AVERROR_EOF) {
                log_info("Video EOF, reopening\n");
                std::string path = videoPath;
                closeVideo();
                if (!openVideo()) {
                    log_error("Failed to reopen video on EOF\n");
                    return false;
                }
                continue;
            }
            log_error("av_read_frame error: %d\n", ret);
            return false;
        }

        if (pkt->stream_index != videoStreamIdx) {
            av_packet_unref(pkt);
            continue;
        }

        ret = avcodec_send_packet(codecCtx, pkt);
        av_packet_unref(pkt);
        if (ret < 0) {
            log_error("avcodec_send_packet error: %d\n", ret);
            continue;
        }

        ret = avcodec_receive_frame(codecCtx, avFrame);
        if (ret == 0) {
            if (!swsCtx) {
                swsCtx = sws_getContext(
                    codecCtx->width, codecCtx->height, codecCtx->pix_fmt,
                    dstW, dstH, AV_PIX_FMT_RGB24,
                    SWS_BILINEAR, nullptr, nullptr, nullptr);
                if (!swsCtx) {
                    log_error("Failed to create sws context\n");
                    return false;
                }
            }

            uint8_t* dstData[1] = { frameBuffer.data() };
            int dstLinesize[1] = { dstW * 3 };

            sws_scale(swsCtx,
                      avFrame->data, avFrame->linesize, 0, codecCtx->height,
                      dstData, dstLinesize);

            frame.vir_addr = frameBuffer.data();
            frame.size = (unsigned int)frameBuffer.size();
            frame.pts = avFrame->pts;
            return true;
        } else if (ret != AVERROR(EAGAIN)) {
            log_error("avcodec_receive_frame error: %d\n", ret);
        }
    }
}

// ─── Decode: RGA CSC path (FFmpeg + RGA hardware color conversion) ──────────

bool H264FileVideoDevice::convertYuvToRgbRga(AVFrame* yuvFrame, int dstW, int dstH) {
    int srcW = codecCtx->width;
    int srcH = codecCtx->height;

    int ySize = srcW * srcH;
    int uvSize = ySize / 2;
    if (nv12Buffer.size() != (size_t)(ySize + uvSize)) {
        nv12Buffer.resize(ySize + uvSize);
    }

    // Copy Y plane
    uint8_t* dst = nv12Buffer.data();
    for (int i = 0; i < srcH; i++) {
        memcpy(dst + i * srcW, yuvFrame->data[0] + i * yuvFrame->linesize[0], srcW);
    }

    // Interleave U and V → NV12 UV plane
    uint8_t* uvDst = dst + ySize;
    for (int i = 0; i < srcH / 2; i++) {
        for (int j = 0; j < srcW / 2; j++) {
            uvDst[i * srcW + j * 2]     = yuvFrame->data[1][i * yuvFrame->linesize[1] + j];
            uvDst[i * srcW + j * 2 + 1] = yuvFrame->data[2][i * yuvFrame->linesize[2] + j];
        }
    }

    rga_buffer_t srcBuf = wrapbuffer_virtualaddr(nv12Buffer.data(), srcW, srcH, RK_FORMAT_YCbCr_420_SP);
    rga_buffer_t dstBuf = wrapbuffer_virtualaddr(frameBuffer.data(), dstW, dstH, RK_FORMAT_RGB_888);
    IM_STATUS stat = imcvtcolor(srcBuf, dstBuf, RK_FORMAT_YCbCr_420_SP, RK_FORMAT_RGB_888);
    if (stat != IM_STATUS_SUCCESS) {
        log_error("RGA imcvtcolor failed: %d\n", stat);
        return false;
    }
    return true;
}

bool H264FileVideoDevice::decodeNextFrameRga() {
    int dstW = (int)targetSize.first;
    int dstH = (int)targetSize.second;

    while (true) {
        int ret = av_read_frame(fmtCtx, pkt);
        if (ret < 0) {
            if (ret == AVERROR_EOF) {
                log_info("Video EOF, reopening\n");
                std::string path = videoPath;
                closeVideo();
                if (!openVideo()) {
                    log_error("Failed to reopen video on EOF\n");
                    return false;
                }
                continue;
            }
            log_error("av_read_frame error: %d\n", ret);
            return false;
        }

        if (pkt->stream_index != videoStreamIdx) {
            av_packet_unref(pkt);
            continue;
        }

        ret = avcodec_send_packet(codecCtx, pkt);
        av_packet_unref(pkt);
        if (ret < 0) {
            log_error("avcodec_send_packet error: %d\n", ret);
            continue;
        }

        ret = avcodec_receive_frame(codecCtx, avFrame);
        if (ret == 0) {
            if (!convertYuvToRgbRga(avFrame, dstW, dstH)) {
                log_error("RGA YUV→RGB conversion failed\n");
                return false;
            }

            frame.vir_addr = frameBuffer.data();
            frame.size = (unsigned int)frameBuffer.size();
            frame.pts = avFrame->pts;
            return true;
        } else if (ret != AVERROR(EAGAIN)) {
            log_error("avcodec_receive_frame error: %d\n", ret);
        }
    }
}

// ─── Decode: MPP VDEC path (via isolated bridge) ────────────────────────────

bool H264FileVideoDevice::decodeNextFrameMpp() {
    if (!mppHandle) return false;

    int64_t pts = 0;
    int ret = mpp_decoder_get_frame(mppHandle, &pts);
    if (ret == 0) {
        // No frame ready yet — caller polls again
        return false;
    }
    if (ret < 0) {
        log_error("MPP decode error\n");
        return false;
    }

    frame.vir_addr = frameBuffer.data();
    frame.size = (unsigned int)frameBuffer.size();
    frame.pts = pts;
    return true;
}

// ─── Dispatcher ─────────────────────────────────────────────────────────────

bool H264FileVideoDevice::decodeNextFrame() {
    switch (decodeMode) {
        case DecodeMode::RGA_CSC:
            return decodeNextFrameRga();
        case DecodeMode::MPP_VDEC:
            return decodeNextFrameMpp();
        case DecodeMode::SOFTWARE:
        default:
            return decodeNextFrameSoftware();
    }
}

// ─── Frame rate control ─────────────────────────────────────────────────────

void H264FileVideoDevice::throttleFrameRate() {
    if (targetFps == 0 || frameInterval.count() == 0) return;

    auto now = std::chrono::steady_clock::now();
    auto elapsed = now - lastFrameTime;
    auto remaining = frameInterval - std::chrono::duration_cast<std::chrono::microseconds>(elapsed);

    if (remaining > std::chrono::microseconds(0)) {
        std::this_thread::sleep_for(remaining);
    }
    lastFrameTime = std::chrono::steady_clock::now();
}

// ─── Decode loop ────────────────────────────────────────────────────────────

void H264FileVideoDevice::decodeLoop() {
    using namespace std::chrono;
    auto fpsReportTime = steady_clock::now();
    int frameCount = 0;

    while (isRunning) {
        {
            std::unique_lock<std::mutex> lock(frameMutex);
            decodeCv.wait(lock, [this] {
                return frameConsumed.load() || !isRunning.load();
            });
        }
        if (!isRunning) break;

        if (!decodeNextFrame()) {
            if (decodeMode == DecodeMode::MPP_VDEC) {
                std::this_thread::sleep_for(milliseconds(1));
                continue;
            }
            log_error("decodeNextFrame failed\n");
            break;
        }

        throttleFrameRate();

        // Set frame PTS BEFORE incrementing so onFrameGet reads the 0-based index
        frame.pts = decodedFrameIdx;

        {
            std::lock_guard<std::mutex> lock(frameMutex);
            frameReady = true;
            frameConsumed = false;
        }
        frameCv.notify_all();

        decodedFrameIdx++;
        frameCv.notify_all();

        frameCount++;
        auto now = steady_clock::now();
        auto elapsed = duration_cast<milliseconds>(now - fpsReportTime).count();
        if (elapsed >= 2000) {
            float fps = frameCount * 1000.0f / elapsed;
            const char* modeStr = "SOFT";
            if (decodeMode == DecodeMode::RGA_CSC) modeStr = "RGA";
            else if (decodeMode == DecodeMode::MPP_VDEC) modeStr = "MPP";
            log_info("H264 decode FPS: %.1f [%s]\n", fps, modeStr);
            fpsReportTime = now;
            frameCount = 0;
        }
    }
}

// ─── JSON detection log ─────────────────────────────────────────────────────

void H264FileVideoDevice::onDetectionResult(const detect_result_group_t& group) {
    if (jsonPath.empty()) return;

    std::lock_guard<std::mutex> lock(jsonMutex);

    int frameIdx = (int)group.sharedFrame->frame.pts;

    cJSON* root = cJSON_CreateObject();
    cJSON_AddNumberToObject(root, "frame", frameIdx);
    cJSON* arr = cJSON_AddArrayToObject(root, "boxes");

    // Post-processor scales box coords from model space to detection frame space.
    // Scale back to model space (targetSize) for consistent JSON output.
    float sx = (float)targetSize.first / (float)detectionFrameW;
    float sy = (float)targetSize.second / (float)detectionFrameH;

    for (const auto& classResults : group.results) {
        for (const auto& det : classResults) {
            cJSON* bo = cJSON_CreateObject();
            cJSON_AddNumberToObject(bo, "x", (float)det.box.left * sx);
            cJSON_AddNumberToObject(bo, "y", (float)det.box.top * sy);
            cJSON_AddNumberToObject(bo, "w", (float)(det.box.right - det.box.left) * sx);
            cJSON_AddNumberToObject(bo, "h", (float)(det.box.bottom - det.box.top) * sy);
            cJSON_AddNumberToObject(bo, "conf", det.prop);
            cJSON_AddNumberToObject(bo, "cls", det.id);
            cJSON_AddItemToArray(arr, bo);
        }
    }

    char fname[256];
    snprintf(fname, sizeof(fname), "%s.json", jsonPath.c_str());
    char* str = cJSON_PrintUnformatted(root);
    if (str) {
        FILE* fp = fopen(fname, "a");
        if (fp) { fprintf(fp, "%s\n", str); fclose(fp); }
        free(str);
    }
    cJSON_Delete(root);
}

// ─── vpss_ops_t callbacks ──────────────────────────────────────────────────

int H264FileVideoDevice::onFrameGet(vpss_obj_t* /*obj*/, vpss_frame_t** outFrame) {
    std::unique_lock<std::mutex> lock(frameMutex);
    frameCv.wait(lock, [this] {
        return frameReady.load() || !isRunning.load();
    });

    if (!isRunning && !frameReady) {
        return -1;
    }

    loanedBuffer = frameBuffer;
    frame.vir_addr = loanedBuffer.data();
    *outFrame = &frame;
    frameReady = false;
    frameConsumed = true;
    decodeCv.notify_one();
    return 0;
}

int H264FileVideoDevice::onFramePut(vpss_obj_t* /*obj*/, vpss_frame_t* /*f*/) {
    std::lock_guard<std::mutex> lock(frameMutex);
    frameReady = false;
    frameConsumed = true;
    decodeCv.notify_one();
    return 0;
}

int H264FileVideoDevice::onInit(vpss_obj_t* /*obj*/, vpss_user_param_t* param) {
    if (!param) return -1;

    targetSize = { param->width, param->height };
    targetFps = param->fps;
    frameBuffer.assign(param->width * param->height * 3, 0);
    frame.vir_addr = frameBuffer.data();
    frame.phy_addr = 0;
    frame.size = (unsigned int)frameBuffer.size();
    frame.pts = 0;

    if (targetFps > 0) {
        frameInterval = std::chrono::microseconds(1000000 / targetFps);
    }
    lastFrameTime = std::chrono::steady_clock::now();

    if (decodeMode == DecodeMode::MPP_VDEC) {
        if (mppHandle) {
            mpp_decoder_destroy(mppHandle);
        }
        mppHandle = mpp_decoder_create(videoPath.c_str(),
                                       (int)param->width, (int)param->height,
                                       frameBuffer.data());
        if (!mppHandle) {
            log_error("Failed to create MPP decoder\n");
            return -1;
        }
    } else {
        if (!openVideo()) {
            log_error("Failed to open video file\n");
            return -1;
        }
    }

    const char* modeStr = "SOFTWARE";
    if (decodeMode == DecodeMode::RGA_CSC) modeStr = "RGA_CSC";
    else if (decodeMode == DecodeMode::MPP_VDEC) modeStr = "MPP_VDEC";
    log_info("H264FileVideoDevice init: %ux%u, fps=%u, mode=%s, video: %s\n",
             param->width, param->height, param->fps, modeStr, videoPath.c_str());
    return 0;
}

int H264FileVideoDevice::onDeinit(vpss_obj_t* /*obj*/) {
    if (isRunning) {
        isRunning = false;
        frameCv.notify_all();
        decodeCv.notify_all();
        if (decodeThread.joinable()) {
            decodeThread.join();
        }
    }
    if (decodeMode == DecodeMode::MPP_VDEC) {
        if (mppHandle) {
            mpp_decoder_destroy(mppHandle);
            mppHandle = nullptr;
        }
    } else {
        closeVideo();
    }
    frameBuffer.clear();
    frame.vir_addr = nullptr;
    frame.size = 0;
    return 0;
}

int H264FileVideoDevice::onStart(vpss_obj_t* /*obj*/) {
    if (isRunning) return 0;
    isRunning = true;
    frameReady = false;
    frameConsumed = true;

    // JSON name from video file: /userdata/soccer2.h265 → /userdata/soccer2_detections.json
    {
        std::string base = videoPath;
        size_t slash = base.find_last_of("/\\");
        size_t dot = base.find_last_of('.');
        std::string stem = (dot != std::string::npos && (slash == std::string::npos || dot > slash))
                           ? base.substr(0, dot) : base;
        jsonPath = stem + "_detections";
    }
    log_info("Detection log: %s.json\n", jsonPath.c_str());

    decodeThread = std::thread(&H264FileVideoDevice::decodeLoop, this);
    return 0;
}

int H264FileVideoDevice::onStop(vpss_obj_t* /*obj*/) {
    isRunning = false;
    frameCv.notify_all();
    decodeCv.notify_all();
    if (decodeThread.joinable()) {
        decodeThread.join();
    }

    log_info("Detection dir: %s\n", jsonPath.c_str());

    if (decodeMode == DecodeMode::MPP_VDEC) {
        if (mppHandle) {
            mpp_decoder_reset(mppHandle);
        }
    } else {
        if (fmtCtx && videoStreamIdx >= 0) {
            av_seek_frame(fmtCtx, videoStreamIdx, 0, AVSEEK_FLAG_BACKWARD);
            if (codecCtx) {
                avcodec_flush_buffers(codecCtx);
            }
        }
    }
    return 0;
}
