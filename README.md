# 智能口腔电子内窥镜客户端

**GitHub:** [OralEndoscopeClientPython](https://github.com/aiwang23/OralEndoscopeClientPython)  

检测服务器 👉 [OralEndoscopeDetectionServer](https://github.com/aiwang23/OralEndoscopeDetectionServer)  
摄像头 👉 [usb_webcam](https://github.com/aiwang23/usb_webcam)  
配置服务器 👉 [ConfigServer](https://github.com/aiwang23/ConfigServer.git)

---

## 项目概述

本项目基于嵌入式硬件 + WebRTC + YOLOv11，实现端到端的**实时口腔 AI 辅助检测系统**，完整闭环流程为：

**图像采集 → 低延迟传输 → AI 推理 → 结果可视化**

系统已支持稳定多设备接入，适用于便携式口腔医疗设备场景，极大提升医生的诊断效率。

---

## 核心功能

- **分布式架构设计**  
  - ESP32-S3 → RK3399 → NVIDIA PC，解决嵌入式端算力不足问题，实现实时 AI 辅助检测。  
  - 向 FastAPI 配置服务器获取 ICE 配置，完成 WebRTC 信令初始化。

- **实时音视频传输**  
  - 使用 MQTT 完成 WebRTC 信令交换 + aiortc 推拉流。  
  - **端到端延迟控制在 150-200ms 内**（从采集到渲染）。

- **高性能视频采集与渲染**  
  - ESP32-S3 通过 UVC + MJPEG 输出高清实时视频。  
  - RK3399 端使用 Qt6 + QOpenGL 预览与 WebRTC 推流同步。  
  - **检测框/标签叠加使用硬件加速**，主线程 CPU 占用 <10%，支持 30fps 稳定渲染。

- **实时 AI 推理**  
  - NVIDIA PC 端部署 YOLOv11 模型，实现龋齿 / 牙结石 / 牙龈炎三类检测。  
  - **平均推理速度 60-80 FPS（1080p 输入，RTX 系列 GPU）**。  
  - **检测准确率约 75%**。  
  - 通过 WebRTC DataChannel 回传结构化结果（坐标 / 标签 / 置信度 >0.5），RK3399 端异步解析并渲染。

- **模块化与可扩展性**  
  - 系统前后端完全解耦，推理服务可独立升级或热更新模型。  
  - 支持未来扩展多类别检测或云端推理。

---

## 项目成果

- 实现闭环实时辅助诊断，延迟远低于传统方案（500ms+）。  
- 显著提升医生诊断效率，适用于便携式口腔医疗设备场景。  
- 支持多设备稳定接入，具备较高的可靠性与可扩展性。

---

## 项目链接

- **客户端:** [OralEndoscopeClientPython](https://github.com/aiwang23/OralEndoscopeClientPython)  
- **检测服务器:** [OralEndoscopeDetectionServer](https://github.com/aiwang23/OralEndoscopeDetectionServer)  
- **摄像头:** [usb_webcam](https://github.com/aiwang23/usb_webcam)  
- **配置服务器:** [ConfigServer](https://github.com/aiwang23/ConfigServer.git)

---

## 技术栈

- **硬件:** ESP32-S3, RK3399, NVIDIA GPU  
- **前端:** Qt6, QOpenGL  
- **后端:** FastAPI, aiortc  
- **模型:** YOLOv11  
- **传输协议:** WebRTC, MQTT  
- **视频格式:** UVC + MJPEG  

---

## 使用说明

```bash
git clone https://github.com/aiwang23/OralEndoscopeClientPython.git
cd OralEndoscopeClientPython

python -m venv venv
source venv/bin/activate
pip install PySide6 qt-material qasync aiortc av numpy opencv-python httpx aiomqtt cv2-enumerate-cameras
```