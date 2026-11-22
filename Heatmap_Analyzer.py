import os
import sys
import time
import numpy as np
import cv2
from PIL import Image, ImageGrab
import win32gui
import win32process
import psutil
import pygetwindow as gw
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QComboBox, QWidget, 
                             QMessageBox, QDialog, QListWidget, QDialogButtonBox
                             , QSlider, QCheckBox, QGroupBox, QColorDialog)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap, QColor, QIcon
from mss import mss
from mss.base import MSSBase
from mss.screenshot import ScreenShot
import matplotlib.cm as cm
from win32api import GetSystemMetrics

class ProjectInfo:
    """项目信息元数据（集中管理所有项目相关信息）"""
    VERSION = "3.13.0"
    BUILD_DATE = "2025-05-15"
    AUTHOR = "杜玛"
    LICENSE = "MIT"
    COPYRIGHT = "© 永久 杜玛"
    URL = "https://github.com/duma520"
    MAINTAINER_EMAIL = "不提供"
    NAME = "进程热力图分析工具"
    DESCRIPTION = "一个用于分析进程热力图的工具，支持多种捕获方式和热力图类型。"


    @classmethod
    def get_metadata(cls) -> dict:
        """获取主要元数据字典"""
        return {
            'version': cls.VERSION,
            'author': cls.AUTHOR,
            'license': cls.LICENSE,
            'url': cls.URL
        }


    @classmethod
    def get_header(cls) -> str:
        """生成标准化的项目头信息"""
        return f"{cls.NAME} {cls.VERSION} | {cls.LICENSE} License | {cls.URL}"

# 马卡龙色系定义
class MacaronColors:
    # 粉色系
    SAKURA_PINK = QColor(255, 183, 206)  # 樱花粉
    ROSE_PINK = QColor(255, 154, 162)    # 玫瑰粉
    
    # 蓝色系
    SKY_BLUE = QColor(162, 225, 246)    # 天空蓝
    LILAC_MIST = QColor(230, 230, 250)   # 淡丁香
    
    # 绿色系
    MINT_GREEN = QColor(181, 234, 215)   # 薄荷绿
    APPLE_GREEN = QColor(212, 241, 199)  # 苹果绿
    
    # 黄色/橙色系
    LEMON_YELLOW = QColor(255, 234, 165) # 柠檬黄
    BUTTER_CREAM = QColor(255, 248, 184) # 奶油黄
    PEACH_ORANGE = QColor(255, 218, 193) # 蜜桃橙
    
    # 紫色系
    LAVENDER = QColor(199, 206, 234)     # 薰衣草紫
    TARO_PURPLE = QColor(216, 191, 216)  # 香芋紫
    
    # 中性色
    CARAMEL_CREAM = QColor(240, 230, 221) # 焦糖奶霜

    # 其他 统一
    DEFAULT_COLOR = QColor(170, 255, 0) # 天蓝色 (RGB格式)
    DEFAULT_COLOR_BGR = (170, 255, 0)   # 天蓝色 (BGR格式)


class ProcessSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择目标进程")
        self.setFixedSize(400, 500)
        
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        
        self.process_list = QListWidget()
        self.layout.addWidget(self.process_list)
        
        self.refresh_button = QPushButton("刷新列表")
        self.refresh_button.clicked.connect(self.populate_process_list)
        self.layout.addWidget(self.refresh_button)
        
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)
        
        self.selected_pid = None
        self.selected_title = None
        self.selected_hwnd = None
        
        self.populate_process_list()
    
    def populate_process_list(self):
        self.process_list.clear()
        
        # 获取所有窗口和进程
        processes = {}
        for proc in psutil.process_iter(['pid', 'name']):
            processes[proc.info['pid']] = proc.info['name']
        
        windows = []
        for window in gw.getAllWindows():
            try:
                # 修改这里：将 isVisible 改为 visible，并添加防御性检查
                if window.title.strip() and getattr(window, 'visible', False):
                    try:
                        pid = window._hWnd
                        _, found_pid = win32process.GetWindowThreadProcessId(pid)
                        exe_name = processes.get(found_pid, "未知进程")
                        window_info = f"{window.title} (PID: {found_pid}, 进程: {exe_name})"
                        windows.append((window.title, found_pid, window_info, window._hWnd))
                    except:
                        continue
            except:
                continue
        
        # 按窗口标题排序
        windows.sort(key=lambda x: x[0].lower())
        
        for title, pid, info, hwnd in windows:
            self.process_list.addItem(info)
            self.process_list.item(self.process_list.count()-1).setData(Qt.UserRole, (pid, title, hwnd))
    
    def get_selected_process(self):
        selected_items = self.process_list.selectedItems()
        if selected_items:
            pid, title, hwnd = selected_items[0].data(Qt.UserRole)
            return pid, title, hwnd
        return None, None, None

class CaptureThread(QThread):
    frame_captured = pyqtSignal(np.ndarray)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, capture_method, hwnd=None, monitor=None):
        super().__init__()
        self.capture_method = capture_method
        self.hwnd = hwnd
        self.monitor = monitor
        self.running = False
        self.mss_instance = mss() if capture_method == "MSS" else None
        
    
    def run(self):
        self.running = True
        frame_counter = 0
        while self.running:
            try:
                frame = self.capture_frame()
                if frame is not None:
                    # 每2帧处理一次(降低到25FPS)
                    if frame_counter % 2 == 0:
                        self.frame_captured.emit(frame)
                    frame_counter += 1
            except Exception as e:
                self.error_occurred.emit(str(e))
            time.sleep(0.02)  # 保持原始延迟

    
    def stop(self):
        self.running = False
        if self.mss_instance:
            self.mss_instance.close()
    
    def capture_frame(self):
        if self.capture_method == "MSS":
            return self.capture_with_mss()
        elif self.capture_method == "Magnification API":
            return self.capture_with_mag()
        elif self.capture_method == "OpenCV截图":
            return self.capture_with_opencv()
        elif self.capture_method == "PIL截图":
            return self.capture_with_pil()
        return None
    
    def capture_with_mss(self):
        if not self.hwnd and not self.monitor:
            #print("错误：既没有提供窗口句柄也没有提供显示器信息")
            return None
            
        if self.hwnd:
            try:
                rect = win32gui.GetWindowRect(self.hwnd)
                #print(f"窗口矩形坐标: {rect}")  # 调试输出

                if rect[0] < 0 and rect[1] < 0 and rect[2] < 0 and rect[3] < 0:
                    #print("错误：窗口矩形坐标全为负值")
                    return None
                
                # 检查窗口尺寸是否合理
                width = rect[2] - rect[0]
                height = rect[3] - rect[1]
                if width <= 0 or height <= 0:
                    #print(f"错误：无效的窗口尺寸 {width}x{height}")
                    return None

                monitor = {
                    "left": rect[0],
                    "top": rect[1],
                    "width": rect[2] - rect[0],
                    "height": rect[3] - rect[1],
                    "mon": 0
                }
                #print(f"监控区域设置: {monitor}")  # 调试输出
            except Exception as e:
                #print(f"获取窗口矩形失败: {str(e)}")
                return None
        else:
            monitor = self.monitor
        
        try:
            # 每次创建新的 MSS 实例
            with mss() as sct:
                sct_img = sct.grab(monitor)
                img = np.array(sct_img)
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            return img
        except Exception as e:
            #print(f"MSS捕获失败: {str(e)}")
            return None
    
    def capture_with_mag(self):
        # 这里应该实现Magnification API捕获，但需要额外的库
        # 由于复杂性，我们暂时用MSS代替
        return self.capture_with_mss()
    
    def capture_with_opencv(self):
        if not self.hwnd:
            return None
            
        try:
            rect = win32gui.GetWindowRect(self.hwnd)
            if rect[0] < 0 and rect[1] < 0 and rect[2] < 0 and rect[3] < 0:
                return None
            
            img = np.array(ImageGrab.grab(bbox=rect))
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            return img
        except:
            return None
    
    def capture_with_pil(self):
        if not self.hwnd:
            return None
            
        try:
            rect = win32gui.GetWindowRect(self.hwnd)
            if rect[0] < 0 and rect[1] < 0 and rect[2] < 0 and rect[3] < 0:
                return None
            
            img = ImageGrab.grab(bbox=rect)
            img = np.array(img)
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            return img
        except:
            return None

class HeatmapGenerator:
    def __init__(self):
        self.prev_frame = None
        self.heatmap = None
        self.motion_history = None
        self.accumulated_heat = None
        self.frame_count = 0
        self.last_activity_time = 0  # 记录最后活动时间
        self.fade_rate = 1.0         # 默认不衰减

        self.use_custom_color = False
        self.opacity = 0.7  # 默认透明度
        self.persistent_color = MacaronColors.DEFAULT_COLOR_BGR  # 默认颜色(天蓝色)
    
    def set_persistent_color(self, color):
        """设置持久颜色"""
        self.persistent_color = color

    def generate_activity_heatmap(self, current_frame):
        if self.prev_frame is None:
            self.prev_frame = current_frame
            self.accumulated_heat = np.zeros(current_frame.shape[:2], dtype=np.float32)
            return None
        
        # 转换为灰度图
        prev_gray = cv2.cvtColor(self.prev_frame, cv2.COLOR_BGR2GRAY)
        curr_gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)
        
        # 计算帧间差异
        frame_diff = cv2.absdiff(prev_gray, curr_gray)
        _, threshold_diff = cv2.threshold(frame_diff, 25, 255, cv2.THRESH_BINARY)
        
        if self.fade_rate == 0:  # 从不消失模式
            # 完全保留所有活动，新活动权重设为1.0
            self.accumulated_heat = np.maximum(self.accumulated_heat, threshold_diff.astype(np.float32))
            
            if self.use_custom_color:
                # 创建单色热力图
                heatmap_color = np.zeros_like(current_frame)
                heatmap_color[:] = self.persistent_color
                # 应用热度遮罩
                mask = cv2.cvtColor(self.accumulated_heat.astype(np.uint8), cv2.COLOR_GRAY2BGR) / 255.0
                heatmap_color = (heatmap_color * mask).astype(np.uint8)
                # 混合原始帧
                heatmap_color = cv2.addWeighted(
                    heatmap_color, self.opacity,
                    current_frame, 1 - self.opacity, 0
                )
            else:
                # 使用标准颜色映射
                normalized_heat = cv2.normalize(self.accumulated_heat, None, 0, 255, cv2.NORM_MINMAX)
                heatmap_color = cv2.applyColorMap(normalized_heat.astype(np.uint8), cv2.COLORMAP_JET)
        else:
            # 正常模式(会消失)
            decay_factor = 0.95 * (1.0 - self.fade_rate)
            # 更新累积热度
            self.accumulated_heat = cv2.addWeighted(
                self.accumulated_heat, decay_factor, 
                threshold_diff.astype(np.float32), 0.05, 0
            )
            # 归一化并应用颜色映射
            normalized_heat = cv2.normalize(self.accumulated_heat, None, 0, 255, cv2.NORM_MINMAX)
            heatmap_color = cv2.applyColorMap(normalized_heat.astype(np.uint8), cv2.COLORMAP_JET)
        
        self.prev_frame = current_frame.copy()
        return heatmap_color

    def generate_motion_heatmap(self, current_frame):
        if self.prev_frame is None:
            self.prev_frame = current_frame
            self.motion_history = np.zeros(current_frame.shape[:2], dtype=np.float32)
            return None
        
        # 降低分辨率处理
        scale_percent = 50  # 缩小到50%
        width = int(current_frame.shape[1] * scale_percent / 100)
        height = int(current_frame.shape[0] * scale_percent / 100)
        dim = (width, height)
        
        # 缩小图像
        resized_prev = cv2.resize(self.prev_frame, dim, interpolation=cv2.INTER_AREA)
        resized_curr = cv2.resize(current_frame, dim, interpolation=cv2.INTER_AREA)
        
        # 转换为灰度图
        prev_gray = cv2.cvtColor(resized_prev, cv2.COLOR_BGR2GRAY)
        curr_gray = cv2.cvtColor(resized_curr, cv2.COLOR_BGR2GRAY)
        
        # 计算光流
        flow = cv2.calcOpticalFlowFarneback(
            prev_gray, curr_gray, None, 
            pyr_scale=0.5, levels=2,
            winsize=7, iterations=1,
            poly_n=3, poly_sigma=1.1,
            flags=0
        )

        # 计算运动幅度
        magnitude, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
        
        # 放大回原尺寸
        magnitude = cv2.resize(magnitude, (current_frame.shape[1], current_frame.shape[0]))
        
        if self.fade_rate == 0:  # 从不消失模式
            # 完全保留所有运动，新运动权重设为1.0
            self.motion_history = np.maximum(self.motion_history, magnitude)
        else:
            # 正常模式(会消失)
            decay_factor = 0.95 * (1.0 - self.fade_rate)
            self.motion_history = cv2.addWeighted(
                self.motion_history, decay_factor, 
                magnitude, 0.05, 0
            )
        
        # 归一化并应用颜色映射
        normalized_motion = cv2.normalize(self.motion_history, None, 0, 255, cv2.NORM_MINMAX)
        
        if self.use_custom_color and self.fade_rate == 0:
            # 自定义颜色模式
            heatmap_color = np.zeros_like(current_frame)
            heatmap_color[:] = self.persistent_color
            # 应用热度遮罩
            mask = cv2.cvtColor(normalized_motion.astype(np.uint8), cv2.COLOR_GRAY2BGR) / 255.0
            heatmap_color = (heatmap_color * mask).astype(np.uint8)
            # 混合原始帧
            heatmap_color = cv2.addWeighted(
                heatmap_color, self.opacity,
                current_frame, 1 - self.opacity, 0
            )
        else:
            # 标准颜色映射
            heatmap_color = cv2.applyColorMap(normalized_motion.astype(np.uint8), cv2.COLORMAP_HOT)
        
        self.prev_frame = current_frame.copy()
        return heatmap_color

    
    def set_fade_duration(self, duration_seconds):
        # 0表示从不消失，计算衰减率
        self.fade_rate = 0 if duration_seconds == 0 else 1.0 / (duration_seconds * 25)  # 假设25FPS



class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{ProjectInfo.NAME} {ProjectInfo.VERSION}")
        self.setWindowIcon(QIcon("icon.ico"))
        self.setGeometry(100, 100, 1000, 800)
        
        self.capture_thread = None
        self.heatmap_generator = HeatmapGenerator()
        self.current_frame = None
        self.heatmap_type = "活动热力图"  # 或 "运动热力图"
        self.show_heatmap = False
        self.selected_hwnd = None
        self.selected_pid = None
        self.selected_title = None
        self.heatmap_fade_duration = 5  # 新增：默认5秒消失
        
        self.init_ui()
    
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局 - 使用QVBoxLayout作为基础
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # ===== 第一行：进程控制面板 =====
        process_group = QGroupBox("进程控制")
        process_layout = QHBoxLayout(process_group)
        process_layout.setContentsMargins(8, 8, 8, 8)
        
        self.select_process_btn = QPushButton("选择进程")
        self.select_process_btn.setFixedWidth(100)
        self.select_process_btn.clicked.connect(self.select_process)
        process_layout.addWidget(self.select_process_btn)
        
        self.process_label = QLabel("未选择进程")
        self.process_label.setStyleSheet("QLabel { min-width: 200px; }")
        process_layout.addWidget(self.process_label)
        
        self.capture_method_combo = QComboBox()
        self.capture_method_combo.addItems(["MSS", "Magnification API", "OpenCV截图", "PIL截图"])
        self.capture_method_combo.setFixedWidth(120)
        process_layout.addWidget(self.capture_method_combo)
        
        self.start_capture_btn = QPushButton("开始捕获")
        self.start_capture_btn.setFixedWidth(80)
        self.start_capture_btn.setEnabled(False)
        self.start_capture_btn.clicked.connect(self.start_capture)
        process_layout.addWidget(self.start_capture_btn)
        
        self.stop_capture_btn = QPushButton("停止捕获")
        self.stop_capture_btn.setFixedWidth(80)
        self.stop_capture_btn.setEnabled(False)
        self.stop_capture_btn.clicked.connect(self.stop_capture)
        process_layout.addWidget(self.stop_capture_btn)
        
        process_layout.addStretch(1)
        main_layout.addWidget(process_group)
        
        # ===== 第二行：热力图控制面板 =====
        heatmap_group = QGroupBox("热力图控制")
        heatmap_layout = QHBoxLayout(heatmap_group)
        heatmap_layout.setContentsMargins(8, 8, 8, 8)
        
        # 热力图类型选择
        type_widget = QWidget()
        type_layout = QHBoxLayout(type_widget)
        type_layout.setContentsMargins(0, 0, 0, 0)
        type_layout.addWidget(QLabel("类型:"))
        self.heatmap_type_combo = QComboBox()
        self.heatmap_type_combo.addItems(["活动热力图", "运动热力图"])
        self.heatmap_type_combo.setFixedWidth(120)
        self.heatmap_type_combo.currentTextChanged.connect(self.change_heatmap_type)
        type_layout.addWidget(self.heatmap_type_combo)
        heatmap_layout.addWidget(type_widget)
        
        # 显示/隐藏按钮
        self.toggle_heatmap_btn = QPushButton("显示热力图")
        self.toggle_heatmap_btn.setFixedWidth(100)
        self.toggle_heatmap_btn.setEnabled(False)
        self.toggle_heatmap_btn.clicked.connect(self.toggle_heatmap)
        heatmap_layout.addWidget(self.toggle_heatmap_btn)
        
        # 持久颜色控制
        color_widget = QWidget()
        color_layout = QHBoxLayout(color_widget)
        color_layout.setContentsMargins(0, 0, 0, 0)
        
        # 使用自定义颜色复选框
        self.use_custom_color_cb = QCheckBox("自定义颜色")
        self.use_custom_color_cb.stateChanged.connect(self.toggle_custom_color)
        color_layout.addWidget(self.use_custom_color_cb)
        
        # 颜色选择按钮
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(24, 24)
        self.default_color = MacaronColors.DEFAULT_COLOR  # 默认颜色(天蓝色)
        self.color_btn.setStyleSheet(
            f"background-color: {self.default_color.name()};"
            "border: 1px solid #888;"
        )
        self.color_btn.setEnabled(False)
        self.color_btn.clicked.connect(self.select_persistent_color)
        color_layout.addWidget(self.color_btn)
        
        # 透明度滑块
        color_layout.addWidget(QLabel("透明度:"))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.setValue(70)
        self.opacity_slider.setFixedWidth(80)
        self.opacity_slider.setEnabled(False)
        self.opacity_slider.valueChanged.connect(self.update_opacity)
        color_layout.addWidget(self.opacity_slider)
        
        self.opacity_label = QLabel("70%")
        self.opacity_label.setFixedWidth(40)
        color_layout.addWidget(self.opacity_label)
        
        heatmap_layout.addWidget(color_widget)
        
        # 消失时间控制
        fade_widget = QWidget()
        fade_layout = QHBoxLayout(fade_widget)
        fade_layout.setContentsMargins(0, 0, 0, 0)
        fade_layout.addWidget(QLabel("消失时间:"))
        
        self.fade_duration_slider = QSlider(Qt.Horizontal)
        self.fade_duration_slider.setRange(0, 3600)  # 0表示从不消失
        self.fade_duration_slider.setValue(5)
        self.fade_duration_slider.setMinimumWidth(150)
        self.fade_duration_slider.valueChanged.connect(self.update_fade_duration)
        fade_layout.addWidget(self.fade_duration_slider)
        
        self.fade_duration_label = QLabel("5秒")
        self.fade_duration_label.setFixedWidth(40)
        fade_layout.addWidget(self.fade_duration_label)
        
        heatmap_layout.addWidget(fade_widget)
        heatmap_layout.addStretch(1)
        main_layout.addWidget(heatmap_group)
        
        # ===== 图像显示区域 =====
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("""
            background-color: black;
            border: 1px solid #ccc;
        """)
        main_layout.addWidget(self.image_label, stretch=1)
        
        # ===== 状态栏 =====
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("就绪")
        
        # 设置最小尺寸
        self.setMinimumSize(900, 650)



    
    def select_process(self):
        dialog = ProcessSelectionDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            self.selected_pid, self.selected_title, self.selected_hwnd = dialog.get_selected_process()
            if self.selected_pid:
                self.process_label.setText(f"已选择: {self.selected_title} (PID: {self.selected_pid})")
                self.start_capture_btn.setEnabled(True)
                self.status_bar.showMessage(f"已选择进程: {self.selected_title}")
            else:
                self.process_label.setText("未选择进程")
                self.start_capture_btn.setEnabled(False)
                self.status_bar.showMessage("未选择进程")
    
    def start_capture(self):
        if not self.selected_hwnd:
            QMessageBox.warning(self, "警告", "请先选择目标进程")
            return
        
        capture_method = self.capture_method_combo.currentText()
        
        # 停止现有的捕获线程
        if self.capture_thread:
            self.capture_thread.stop()
            self.capture_thread.quit()
            self.capture_thread.wait()
        
        # 创建新的捕获线程
        self.capture_thread = CaptureThread(capture_method, self.selected_hwnd)
        self.capture_thread.frame_captured.connect(self.update_frame)
        self.capture_thread.error_occurred.connect(self.handle_capture_error)
        self.capture_thread.start()
        
        self.start_capture_btn.setEnabled(False)
        self.stop_capture_btn.setEnabled(True)
        self.toggle_heatmap_btn.setEnabled(True)
        self.status_bar.showMessage(f"正在捕获: {self.selected_title} - 方法: {capture_method}")
    
    def stop_capture(self):
        if self.capture_thread:
            self.capture_thread.stop()
            self.capture_thread.quit()
            self.capture_thread.wait()
            self.capture_thread = None
        
        self.start_capture_btn.setEnabled(True)
        self.stop_capture_btn.setEnabled(False)
        self.toggle_heatmap_btn.setEnabled(False)
        self.status_bar.showMessage("捕获已停止")
        
        # 清空显示
        self.image_label.clear()
        self.image_label.setStyleSheet("background-color: black;")
    
    def update_frame(self, frame):
        # 在生成热力图前设置消失时长
        self.heatmap_generator.set_fade_duration(self.heatmap_fade_duration)
        
        self.current_frame = frame

        if self.show_heatmap:
            if self.heatmap_type == "活动热力图":
                heatmap = self.heatmap_generator.generate_activity_heatmap(frame)
            else:
                heatmap = self.heatmap_generator.generate_motion_heatmap(frame)
            
            if heatmap is not None:
                # 将热力图与原始帧混合
                overlay = cv2.addWeighted(frame, 0.7, heatmap, 0.3, 0)
                display_frame = overlay
            else:
                display_frame = frame
        else:
            display_frame = frame
        
        # 转换为QPixmap并显示
        height, width, channel = display_frame.shape
        bytes_per_line = 3 * width
        q_img = QImage(display_frame.data, width, height, bytes_per_line, QImage.Format_RGB888).rgbSwapped()
        pixmap = QPixmap.fromImage(q_img)
        
        # 保持纵横比缩放
        scaled_pixmap = pixmap.scaled(
            self.image_label.size(), 
            Qt.KeepAspectRatio, 
            Qt.SmoothTransformation
        )
        self.image_label.setPixmap(scaled_pixmap)
    
    def toggle_heatmap(self):
        self.show_heatmap = not self.show_heatmap
        if self.show_heatmap:
            self.toggle_heatmap_btn.setText("隐藏热力图")
            self.status_bar.showMessage("热力图已显示")
        else:
            self.toggle_heatmap_btn.setText("显示热力图")
            self.status_bar.showMessage("热力图已隐藏")
        
        # 重置热力图生成器
        self.heatmap_generator = HeatmapGenerator()
    
    def change_heatmap_type(self, heatmap_type):
        self.heatmap_type = heatmap_type
        self.status_bar.showMessage(f"热力图类型已切换为: {heatmap_type}")
        
        # 重置热力图生成器
        self.heatmap_generator = HeatmapGenerator()
    
    def handle_capture_error(self, error_msg):
        QMessageBox.critical(self, "捕获错误", f"捕获过程中发生错误:\n{error_msg}")
        self.stop_capture()


    def update_fade_duration(self, value):
        self.heatmap_fade_duration = value
        self.fade_duration_label.setText(f"{value}秒" if value > 0 else "从不消失")
        # 重置热力图生成器以应用新设置
        self.heatmap_generator = HeatmapGenerator()

    def select_persistent_color(self):
        """选择持久颜色"""
        current_color = QColor(self.color_btn.palette().button().color())
        color = QColorDialog.getColor(initial=current_color, parent=self)
        if color.isValid():
            # 转换为BGR格式
            bgr_color = (color.blue(), color.green(), color.red())
            self.heatmap_generator.set_persistent_color(bgr_color)
            # 更新按钮颜色
            self.color_btn.setStyleSheet(
                f"background-color: {color.name()};"
                "border: 1px solid #888;"
            )
            self.status_bar.showMessage(f"已设置持久颜色: {color.name()}")


    def toggle_custom_color(self, state):
        """切换是否使用自定义颜色"""
        enabled = state == Qt.Checked
        self.color_btn.setEnabled(enabled)
        self.opacity_slider.setEnabled(enabled)
        self.heatmap_generator.use_custom_color = enabled

        # 当启用自定义颜色时，立即应用当前按钮显示的颜色
        if enabled:
            current_color = QColor(self.color_btn.palette().button().color())
            bgr_color = (current_color.blue(), current_color.green(), current_color.red())
            self.heatmap_generator.set_persistent_color(bgr_color)
            self.status_bar.showMessage("已启用自定义颜色")
        else:
            self.status_bar.showMessage("已禁用自定义颜色")



    def update_opacity(self, value):
        """更新透明度设置"""
        self.opacity_label.setText(f"{value}%")
        self.heatmap_generator.opacity = value / 100.0


    def closeEvent(self, event):
        self.stop_capture()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())