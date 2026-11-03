import sys
import os
import io
import re
import time
import json
import socket
import subprocess
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

import qrcode
import requests
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont, QPixmap, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QCheckBox, QLineEdit, QComboBox, QFileDialog,
    QMessageBox, QGroupBox, QFormLayout, QTextEdit, QFrame
)

BASE_DIR = Path(__file__).resolve().parent.parent
SERVER_SCRIPT = BASE_DIR / "server" / "server_app.py"
SERVER_URL = "http://127.0.0.1:8000"


def get_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def make_qpixmap_qr(url: str, size: int = 190) -> QPixmap:
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    pix = QPixmap()
    pix.loadFromData(buf.getvalue())
    return pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


class BridgeSignals(QObject):
    tunnel_url_ready = Signal(str)
    log_signal = Signal(str)


class PySide6ControlCenter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PHẦN MỀM MÁY TÍNH PYSIDE6 - BỘ ĐIỀU KHIỂN SERVER, CHIA SẺ & KẾT NỐI ĐA NỀN TẢNG")
        self.resize(1300, 820)

        self.lan_ip = get_lan_ip()
        self.lan_url = f"http://{self.lan_ip}:8000"
        self.public_url = ""
        self.server_running = False
        self.server_process = None
        self.tunnel_process = None
        self.auto_process_enabled = True

        self.signals = BridgeSignals()
        self.signals.tunnel_url_ready.connect(self.on_tunnel_url_found)
        self.signals.log_signal.connect(self.log_msg)

        self.apply_stylesheet()
        self.init_ui()

        # Tự động kiểm tra hoặc bật Server khi mở phần mềm PySide6
        QTimer.singleShot(200, self.ensure_server_started_on_boot)

        # Timer đồng bộ thời gian thực với Server (1.8 giây/lần)
        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self.periodic_sync)
        self.sync_timer.start(1800)

    def apply_stylesheet(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #0f172a;
                color: #f8fafc;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;
            }
            QGroupBox {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 10px;
                margin-top: 12px;
                padding: 14px;
                font-weight: bold;
                color: #38bdf8;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            QTabWidget::pane {
                border: 1px solid #334155;
                border-radius: 8px;
                background: #0f172a;
            }
            QTabBar::tab {
                background: #1e293b;
                color: #94a3b8;
                padding: 10px 16px;
                margin-right: 4px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: #0284c7;
                color: #ffffff;
            }
            QPushButton {
                background-color: #0284c7;
                color: white;
                border: none;
                border-radius: 7px;
                padding: 8px 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0369a1;
            }
            QPushButton#btnSuccess {
                background-color: #16a34a;
            }
            QPushButton#btnSuccess:hover {
                background-color: #15803d;
            }
            QPushButton#btnDanger {
                background-color: #dc2626;
            }
            QPushButton#btnDanger:hover {
                background-color: #b91c1c;
            }
            QPushButton#btnPurple {
                background-color: #7c3aed;
            }
            QPushButton#btnPurple:hover {
                background-color: #6d28d9;
            }
            QLineEdit, QComboBox, QTextEdit {
                background-color: #0f172a;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 6px 10px;
                color: #f8fafc;
            }
            QTableWidget {
                background-color: #0f172a;
                border: 1px solid #334155;
                border-radius: 8px;
                gridline-color: #1e293b;
                selection-background-color: #1d4ed8;
            }
            QHeaderView::section {
                background-color: #1e293b;
                color: #38bdf8;
                padding: 8px;
                border: 1px solid #334155;
                font-weight: bold;
            }
        """)

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # ==================== THANH ĐIỀU KHIỂN SERVER (BẬT / TẮT SERVER & INTERNET) ====================
        header_frame = QFrame()
        header_frame.setStyleSheet("background-color: #1e293b; border: 2px solid #0284c7; border-radius: 10px; padding: 10px;")
        h_layout = QHBoxLayout(header_frame)

        title_box = QVBoxLayout()
        lbl_title = QLabel("🖥️ TRUNG TÂM ĐIỀU KHIỂN PYSIDE6 — QUẢN LÝ SERVER & CHIA SẺ DỮ LIỆU")
        lbl_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl_title.setStyleSheet("color: #38bdf8;")
        self.lbl_status = QLabel("⏳ Đang kiểm tra trạng thái Server...")
        self.lbl_status.setStyleSheet("color: #facc15; font-weight: bold; font-size: 13px;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(self.lbl_status)
        h_layout.addLayout(title_box, stretch=1)

        # Nút KHỞI ĐỘNG / TẮT SERVER
        self.btn_toggle_server = QPushButton("🟢 KHỞI ĐỘNG SERVER")
        self.btn_toggle_server.setObjectName("btnSuccess")
        self.btn_toggle_server.setMinimumHeight(38)
        self.btn_toggle_server.clicked.connect(self.toggle_server_power)
        h_layout.addWidget(self.btn_toggle_server)

        # Nút BẬT / TẮT KẾT NỐI INTERNET (4G / TỪ XA)
        self.btn_toggle_tunnel = QPushButton("🌍 BẬT INTERNET (4G/MỌI NƠI)")
        self.btn_toggle_tunnel.setObjectName("btnPurple")
        self.btn_toggle_tunnel.setMinimumHeight(38)
        self.btn_toggle_tunnel.clicked.connect(self.toggle_internet_tunnel)
        h_layout.addWidget(self.btn_toggle_tunnel)

        # Checkbox AUTO-PROCESS
        self.chk_auto = QCheckBox("⚡ Tự động xử lý & trả Báo Cáo")
        self.chk_auto.setChecked(True)
        self.chk_auto.setStyleSheet("color: #4ade80; font-weight: bold; padding: 4px;")
        self.chk_auto.toggled.connect(self.on_auto_mode_toggled)
        h_layout.addWidget(self.chk_auto)

        # Nút mở Web nhanh
        btn_open_web = QPushButton("🌐 Mở App Web")
        btn_open_web.setMinimumHeight(38)
        btn_open_web.clicked.connect(lambda: webbrowser.open(self.public_url or self.lan_url))
        h_layout.addWidget(btn_open_web)

        main_layout.addWidget(header_frame)

        # ==================== CÁC TAB CHỨC NĂNG ====================
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, stretch=1)

        self.init_tab_connect_qr()
        self.init_tab_share()
        self.init_tab_processing()
        self.init_tab_users()

        # LOG BAR
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(90)
        self.txt_log.setStyleSheet("background:#090d16; color:#94a3b8; font-family:Consolas; font-size:12px;")
        main_layout.addWidget(self.txt_log)
        self.log_msg("Phần mềm PySide6 đã sẵn sàng. Bạn có thể Bật/Tắt Server và lấy mã QR kết nối Điện thoại ngay tại đây.")

    # ==================== TAB 1 (MỚI): KẾT NỐI ĐIỆN THOẠI & APP KHÁC ====================
    def init_tab_connect_qr(self):
        tab = QWidget()
        layout = QHBoxLayout(tab)

        # Cột 1: Kết nối mạng nội bộ Wi-Fi (LAN)
        lan_group = QGroupBox("📶 CÁCH 1: Điện Thoại / Máy Khác Cùng Mạng Wi-Fi (LAN)")
        lan_vbox = QVBoxLayout(lan_group)
        lan_desc = QLabel(
            "Dùng khi Điện thoại và Máy tính bắt chung 1 mạng Wi-Fi.\n"
            "• Tốc độ cực nhanh, không cần Internet bên ngoài."
        )
        lan_desc.setWordWrap(True)
        lan_desc.setStyleSheet("color:#cbd5e1; font-weight:normal;")
        lan_vbox.addWidget(lan_desc)

        self.lbl_qr_lan = QLabel()
        self.lbl_qr_lan.setAlignment(Qt.AlignCenter)
        self.lbl_qr_lan.setPixmap(make_qpixmap_qr(self.lan_url, 185))
        lan_vbox.addWidget(self.lbl_qr_lan)

        self.inp_lan_url = QLineEdit(self.lan_url)
        self.inp_lan_url.setReadOnly(True)
        self.inp_lan_url.setAlignment(Qt.AlignCenter)
        self.inp_lan_url.setStyleSheet("font-size:15px; font-weight:bold; color:#4ade80; background:#090d16; padding:8px;")
        lan_vbox.addWidget(self.inp_lan_url)

        btn_copy_lan = QPushButton("📋 Copy Link Wi-Fi Nội Bộ")
        btn_copy_lan.clicked.connect(lambda: self.copy_to_clipboard(self.lan_url))
        lan_vbox.addWidget(btn_copy_lan)

        btn_fw = QPushButton("🛡️ Mở Tường Lửa Windows (Nếu ĐT cùng Wi-Fi không vào được)")
        btn_fw.setStyleSheet("background:#334155;")
        btn_fw.clicked.connect(self.open_windows_firewall_port)
        lan_vbox.addWidget(btn_fw)

        # Cột 2: Kết nối qua Internet (4G / 5G / Mọi nơi)
        net_group = QGroupBox("🌍 CÁCH 2: Điện Thoại Dùng 4G/5G Hoặc Ở Xa Qua Internet")
        net_vbox = QVBoxLayout(net_group)
        net_desc = QLabel(
            "Dùng khi Điện thoại bật 4G/5G hoặc ở khác tòa nhà/khác tỉnh.\n"
            "• Bấm nút 'BẬT INTERNET' để tạo đường link HTTPS toàn cầu miễn phí."
        )
        net_desc.setWordWrap(True)
        net_desc.setStyleSheet("color:#cbd5e1; font-weight:normal;")
        net_vbox.addWidget(net_desc)

        self.lbl_qr_pub = QLabel("Chưa bật Internet Tunnel.\nBấm nút '🌍 BẬT INTERNET' bên dưới\nđể lấy Mã QR 4G/Internet!")
        self.lbl_qr_pub.setAlignment(Qt.AlignCenter)
        self.lbl_qr_pub.setMinimumHeight(185)
        self.lbl_qr_pub.setStyleSheet("background:#090d16; border:1px dashed #7c3aed; border-radius:10px; color:#c4b5fd;")
        net_vbox.addWidget(self.lbl_qr_pub)

        self.inp_pub_url = QLineEdit("Chưa bật kết nối Internet từ xa")
        self.inp_pub_url.setReadOnly(True)
        self.inp_pub_url.setAlignment(Qt.AlignCenter)
        self.inp_pub_url.setStyleSheet("font-size:14px; font-weight:bold; color:#c4b5fd; background:#090d16; padding:8px;")
        net_vbox.addWidget(self.inp_pub_url)

        btn_start_net = QPushButton("🌍 Bật / Tắt Link Internet (4G / Mọi Nơi) Ngay")
        btn_start_net.setObjectName("btnPurple")
        btn_start_net.clicked.connect(self.toggle_internet_tunnel)
        net_vbox.addWidget(btn_start_net)

        btn_copy_pub = QPushButton("📋 Copy Link Internet Gửi Qua Zalo / Điện Thoại")
        btn_copy_pub.clicked.connect(lambda: self.copy_to_clipboard(self.public_url or "Hãy bấm Bật Internet trước!"))
        net_vbox.addWidget(btn_copy_pub)

        # Cột 3: Kết nối từ App Khác (API Chuẩn)
        api_group = QGroupBox("🔌 CÁCH 3: Kết Nối Từ Phần Mềm / App Khác Vào Hệ Thống (API)")
        api_vbox = QVBoxLayout(api_group)
        api_desc = QLabel(
            "Bất kỳ App khác (App Android APK riêng, Web khác, phần mềm Python/C#/Excel) đều kết nối chung qua cổng API chuẩn của Server:"
        )
        api_desc.setWordWrap(True)
        api_desc.setStyleSheet("color:#cbd5e1; font-weight:normal;")
        api_vbox.addWidget(api_desc)

        self.txt_api_guide = QTextEdit()
        self.txt_api_guide.setReadOnly(True)
        self.txt_api_guide.setStyleSheet("background:#090d16; color:#38bdf8; font-family:Consolas; font-size:12px;")
        self.update_api_guide_text()
        api_vbox.addWidget(self.txt_api_guide, stretch=1)

        layout.addWidget(lan_group, stretch=3)
        layout.addWidget(net_group, stretch=3)
        layout.addWidget(api_group, stretch=4)
        self.tabs.addTab(tab, "📲 1. Kết Nối Điện Thoại (Wi-Fi / 4G) & App Khác")

    def update_api_guide_text(self):
        base = self.public_url if self.public_url else self.lan_url
        guide = f"""=== ĐỊA CHỈ SERVER HIỆN TẠI (BASE URL) ===
{base}

1. API Đăng nhập kiểm tra quyền:
   POST {base}/api/login
   JSON: {{"username": "nhanvien1", "password": "123456"}}

2. API Lấy dữ liệu PySide6 cho phép chia sẻ:
   GET  {base}/api/shared-data?username=nhanvien1

3. API Gửi ảnh chụp + ghi chú từ App khác lên PySide6 xử lý:
   POST {base}/api/submissions
   Form-Data: username, title, note_text, image_file

4. API Nhận kết quả Báo cáo do PySide6 trả về:
   GET  {base}/api/submissions?username=nhanvien1

5. WebSocket Nhận thông báo Thời gian thực (Real-time):
   WS   {base.replace('http', 'ws')}/ws

--- CODE PYTHON MẪU CHO APP KHÁC KẾT NỐI ---
import requests
url = "{base}"
# Lấy các thông số & file PySide6 đang chia sẻ:
res = requests.get(f"{{url}}/api/shared-data", params={{"username": "nhanvien1"}})
print(res.json())
"""
        self.txt_api_guide.setPlainText(guide)

    # ==================== TAB 2: CHỌN DỮ LIỆU CHIA SẺ ====================
    def init_tab_share(self):
        tab = QWidget()
        layout = QHBoxLayout(tab)

        left_group = QGroupBox("📊 1. Chọn Thông Số Thời Gian Thực Muốn Chia Sẻ Lên App")
        l_vbox = QVBoxLayout(left_group)
        lbl_hint1 = QLabel("Tick chọn 'Chia sẻ' ở dòng nào thì Điện thoại/Web chỉ nhìn thấy đúng dòng đó:")
        lbl_hint1.setStyleSheet("color:#94a3b8; font-weight:normal;")
        l_vbox.addWidget(lbl_hint1)

        self.tbl_metrics = QTableWidget(0, 4)
        self.tbl_metrics.setHorizontalHeaderLabels(["Chia sẻ?", "Tên thông số trên PySide6", "Giá trị hiện tại", "Đơn vị"])
        self.tbl_metrics.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        l_vbox.addWidget(self.tbl_metrics)

        btn_save_metrics = QPushButton("💾 Cập Nhật Ngay Các Thông Số Đã Chọn Lên App Web/APK")
        btn_save_metrics.clicked.connect(self.save_metrics_from_table)
        l_vbox.addWidget(btn_save_metrics)

        right_group = QGroupBox("📁 2. Hình Ảnh, Tài Liệu & Báo Cáo Xuất Từ PySide6")
        r_vbox = QVBoxLayout(right_group)

        self.tbl_items = QTableWidget(0, 5)
        self.tbl_items.setHorizontalHeaderLabels(["ID", "Chia sẻ?", "Tiêu đề Tài liệu / Hình ảnh", "Tài khoản được xem", "Xóa"])
        self.tbl_items.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        r_vbox.addWidget(self.tbl_items)

        add_box = QGroupBox("➕ Xuất / Đẩy Thêm Hình Ảnh Hoặc Báo Cáo Mới Từ PySide6 Lên App")
        form = QFormLayout(add_box)
        self.inp_share_title = QLineEdit("Báo cáo & Biểu đồ kiểm tra mới từ PySide6")
        self.inp_share_desc = QLineEdit("Dữ liệu được xuất và phê duyệt chia sẻ trực tiếp trên máy tính PySide6.")
        self.inp_share_users = QComboBox()
        self.inp_share_users.setEditable(True)
        self.inp_share_users.addItems(["ALL", "admin,nhanvien1", "admin"])
        self.lbl_selected_file = QLabel("Chưa chọn file (Sẽ tự động vẽ biểu đồ PySide6 nếu để trống)")
        self.lbl_selected_file.setStyleSheet("color:#94a3b8; font-weight:normal;")
        self.selected_share_path = None

        file_btn_row = QHBoxLayout()
        btn_pick = QPushButton("📂 Chọn File Ảnh / Tài Liệu...")
        btn_pick.clicked.connect(self.pick_share_file)
        btn_push = QPushButton("🚀 Đẩy Lên App Web & Điện Thoại Ngay")
        btn_push.setObjectName("btnSuccess")
        btn_push.clicked.connect(self.push_new_shared_item)
        file_btn_row.addWidget(btn_pick)
        file_btn_row.addWidget(btn_push)

        form.addRow("Tiêu đề chia sẻ:", self.inp_share_title)
        form.addRow("Mô tả ngắn:", self.inp_share_desc)
        form.addRow("Ai được phép xem:", self.inp_share_users)
        form.addRow("File đính kèm:", self.lbl_selected_file)
        form.addRow("", file_btn_row)
        r_vbox.addWidget(add_box)

        layout.addWidget(left_group, stretch=4)
        layout.addWidget(right_group, stretch=6)
        self.tabs.addTab(tab, "📡 2. Chọn Dữ Liệu Chia Sẻ Lên Web/APK")

    # ==================== TAB 3: TỰ ĐỘNG XỬ LÝ YÊU CẦU & TRẢ BÁO CÁO ====================
    def init_tab_processing(self):
        tab = QWidget()
        layout = QHBoxLayout(tab)

        left_group = QGroupBox("📥 Hàng Đợi Tài Liệu Chụp Ảnh & Ghi Chú Tay Từ Điện Thoại Gửi Về")
        l_vbox = QVBoxLayout(left_group)

        self.tbl_subs = QTableWidget(0, 6)
        self.tbl_subs.setHorizontalHeaderLabels(["Mã", "Tài khoản gửi", "Tiêu đề & Ghi chú", "Trạng thái", "Thời gian", "Xử lý lại"])
        self.tbl_subs.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tbl_subs.itemSelectionChanged.connect(self.on_sub_selected)
        l_vbox.addWidget(self.tbl_subs)

        right_group = QGroupBox("🔍 Xem Trước Ảnh Ghi Chú Gửi Lên & Báo Cáo PySide6 Đã Xuất")
        r_vbox = QVBoxLayout(right_group)

        self.lbl_preview_info = QLabel("Hãy bấm vào 1 dòng bên trái để xem hình ảnh ghi chú tay và báo cáo kết quả.")
        self.lbl_preview_info.setWordWrap(True)
        r_vbox.addWidget(self.lbl_preview_info)

        self.lbl_preview_img = QLabel()
        self.lbl_preview_img.setAlignment(Qt.AlignCenter)
        self.lbl_preview_img.setMinimumHeight(340)
        self.lbl_preview_img.setStyleSheet("background:#090d16; border:1px dashed #38bdf8; border-radius:8px;")
        r_vbox.addWidget(self.lbl_preview_img, stretch=1)

        custom_row = QHBoxLayout()
        self.inp_custom_conclusion = QLineEdit("PySide6 đã xác nhận dữ liệu & ghi chú tay hợp lệ. Phê duyệt xuất báo cáo!")
        btn_manual_proc = QPushButton("⚙️ Chạy Xử Lý & Xuất Lại Báo Cáo")
        btn_manual_proc.setObjectName("btnSuccess")
        btn_manual_proc.clicked.connect(self.manual_reprocess_selected)
        btn_open_pdf = QPushButton("📄 Mở File PDF Báo Cáo A4")
        btn_open_pdf.clicked.connect(self.open_selected_sub_pdf)
        custom_row.addWidget(self.inp_custom_conclusion, stretch=1)
        custom_row.addWidget(btn_manual_proc)
        custom_row.addWidget(btn_open_pdf)
        r_vbox.addLayout(custom_row)

        layout.addWidget(left_group, stretch=5)
        layout.addWidget(right_group, stretch=5)
        self.tabs.addTab(tab, "🤖 3. Nhận Ảnh/Ghi Chú & Tự Động Trả Báo Cáo")

    # ==================== TAB 4: QUẢN LÝ TÀI KHOẢN & PHÂN QUYỀN ====================
    def init_tab_users(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        top_group = QGroupBox("🔐 Tạo Tài Khoản - Mật Khẩu & Cấp Quyền Truy Cập App Điện Thoại / Web")
        h_form = QHBoxLayout(top_group)

        self.u_username = QLineEdit()
        self.u_username.setPlaceholderText("Tên TK (VD: nhanvien2)")
        self.u_password = QLineEdit("123456")
        self.u_password.setPlaceholderText("Mật khẩu")
        self.u_fullname = QLineEdit()
        self.u_fullname.setPlaceholderText("Họ và tên người dùng")
        self.u_role = QComboBox()
        self.u_role.addItems(["staff", "viewer", "admin"])
        self.u_can_view = QCheckBox("Quyền Xem")
        self.u_can_view.setChecked(True)
        self.u_can_submit = QCheckBox("Quyền Chụp/Ghi chú gửi xử lý")
        self.u_can_submit.setChecked(True)
        self.u_auto_proc = QCheckBox("PySide6 Tự động xử lý ngay")
        self.u_auto_proc.setChecked(True)

        btn_add_u = QPushButton("➕ Tạo / Cập Nhật Tài Khoản")
        btn_add_u.setObjectName("btnSuccess")
        btn_add_u.clicked.connect(self.save_user_from_pyside)

        for w in [self.u_username, self.u_password, self.u_fullname, self.u_role,
                  self.u_can_view, self.u_can_submit, self.u_auto_proc, btn_add_u]:
            h_form.addWidget(w)

        layout.addWidget(top_group)

        self.tbl_users = QTableWidget(0, 7)
        self.tbl_users.setHorizontalHeaderLabels([
            "Tài khoản (Username)", "Mật khẩu", "Họ tên", "Vai trò",
            "Quyền Xem Chia Sẻ", "Quyền Gửi Xử Lý", "PySide6 Tự Động Trả KQ"
        ])
        self.tbl_users.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.tbl_users, stretch=1)

        self.tabs.addTab(tab, "🔐 4. Quản Lý Tài Khoản & Phân Quyền")

    # ==================== LOGIC BẬT / TẮT SERVER & INTERNET TUNNEL ====================
    def is_server_alive(self) -> bool:
        try:
            r = requests.get(f"{SERVER_URL}/api/network-info", timeout=1.0)
            return r.ok
        except Exception:
            return False

    def ensure_server_started_on_boot(self):
        if self.is_server_alive():
            self.server_running = True
            self.update_server_ui_state(True)
            self.initial_load()
        else:
            self.start_server_process()

    def toggle_server_power(self):
        if self.server_running:
            self.stop_server_process()
        else:
            self.start_server_process()

    def start_server_process(self):
        if self.is_server_alive():
            self.server_running = True
            self.update_server_ui_state(True)
            self.initial_load()
            return

        self.log_msg("🚀 Đang khởi động Server trung gian (FastAPI + WebSocket) trên cổng 8000...")
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.server_process = subprocess.Popen(
            [sys.executable, str(SERVER_SCRIPT)],
            cwd=str(BASE_DIR),
            creationflags=creation_flags
        )
        # Chờ Server lên rồi tải dữ liệu
        QTimer.singleShot(1500, self.verify_server_started)

    def verify_server_started(self):
        if self.is_server_alive():
            self.server_running = True
            self.update_server_ui_state(True)
            self.log_msg(f"✅ Server đã KHỞI ĐỘNG thành công! Địa chỉ mạng Wi-Fi: {self.lan_url}")
            self.initial_load()
        else:
            QTimer.singleShot(1000, self.verify_server_started)

    def stop_server_process(self):
        self.log_msg("🛑 Đang tắt Server trung gian...")
        # Tắt cả tunnel nếu đang bật
        if self.tunnel_process:
            self.stop_internet_tunnel()

        if self.server_process:
            try:
                self.server_process.terminate()
                self.server_process.wait(timeout=2)
            except Exception:
                pass
            self.server_process = None

        # Đảm bảo giải phóng cổng 8000 nếu Server được bật từ tiến trình bên ngoài
        if os.name == "nt":
            subprocess.run(
                'for /f "tokens=5" %a in (\'netstat -aon ^| findstr :8000 ^| findstr LISTENING\') do taskkill /F /PID %a',
                shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

        self.server_running = False
        self.update_server_ui_state(False)
        self.log_msg("🔴 Đã TẮT SERVER hoàn toàn! Điện thoại và các App bên ngoài tạm ngưng truy cập.")

    def update_server_ui_state(self, running: bool):
        if running:
            self.btn_toggle_server.setText("🛑 TẮT SERVER")
            self.btn_toggle_server.setObjectName("btnDanger")
            net_txt = f" | 🌍 Internet 4G: {self.public_url}" if self.public_url else ""
            self.lbl_status.setText(f"🟢 SERVER ĐANG CHẠY | 📶 Wi-Fi LAN: {self.lan_url}{net_txt}")
            self.lbl_status.setStyleSheet("color: #4ade80; font-weight: bold; font-size: 13px;")
        else:
            self.btn_toggle_server.setText("🟢 KHỞI ĐỘNG SERVER")
            self.btn_toggle_server.setObjectName("btnSuccess")
            self.lbl_status.setText("🔴 SERVER ĐANG TẮT (Bấm '🟢 KHỞI ĐỘNG SERVER' để cho phép Điện thoại & Web kết nối)")
            self.lbl_status.setStyleSheet("color: #f87171; font-weight: bold; font-size: 13px;")
        self.btn_toggle_server.style().unpolish(self.btn_toggle_server)
        self.btn_toggle_server.style().polish(self.btn_toggle_server)

    # ==================== KẾT NỐI INTERNET 4G/TỪ XA (SSH TUNNEL) ====================
    def toggle_internet_tunnel(self):
        if not self.server_running:
            QMessageBox.warning(self, "Server chưa bật", "Hãy bấm '🟢 KHỞI ĐỘNG SERVER' trước khi mở kết nối Internet!")
            return
        if self.tunnel_process:
            self.stop_internet_tunnel()
        else:
            self.start_internet_tunnel()

    def start_internet_tunnel(self):
        self.log_msg("🌍 Đang mở đường truyền Internet (HTTPS Tunnel) để điện thoại 4G/5G truy cập từ mọi nơi...")
        self.btn_toggle_tunnel.setText("⏳ ĐANG TẠO LINK INTERNET...")
        self.inp_pub_url.setText("Đang cấp phát địa chỉ HTTPS toàn cầu...")

        def tunnel_worker():
            try:
                creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                self.tunnel_process = subprocess.Popen(
                    ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ServerAliveInterval=30", "-R", "80:127.0.0.1:8000", "nokey@localhost.run"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    creationflags=creation_flags
                )
                for _ in range(90):
                    if not self.tunnel_process:
                        break
                    line = self.tunnel_process.stdout.readline()
                    if not line:
                        break
                    m = re.search(r"https://[a-zA-Z0-9-]+\.lhr\.life", line)
                    if m:
                        url = m.group(0)
                        self.signals.tunnel_url_ready.emit(url)
                        break
            except Exception as e:
                self.signals.log_signal.emit(f"❌ Lỗi mở Internet Tunnel: {e}")

        threading.Thread(target=tunnel_worker, daemon=True).start()

    def on_tunnel_url_found(self, url: str):
        self.public_url = url
        self.inp_pub_url.setText(url)
        self.lbl_qr_pub.setPixmap(make_qpixmap_qr(url, 185))
        self.btn_toggle_tunnel.setText("🔌 TẮT INTERNET (ĐANG MỞ 4G)")
        self.btn_toggle_tunnel.setObjectName("btnDanger")
        self.btn_toggle_tunnel.style().unpolish(self.btn_toggle_tunnel)
        self.btn_toggle_tunnel.style().polish(self.btn_toggle_tunnel)
        self.update_server_ui_state(self.server_running)
        self.update_api_guide_text()
        try:
            requests.post(f"{SERVER_URL}/api/pyside6/tunnel", json={"public_url": url}, timeout=2)
        except Exception:
            pass
        self.log_msg(f"🎉 ĐÃ MỞ KẾT NỐI INTERNET TOÀN CẦU: {url} — Điện thoại dùng 4G/5G quét mã QR vào được ngay!")

    def stop_internet_tunnel(self):
        if self.tunnel_process:
            try:
                self.tunnel_process.terminate()
            except Exception:
                pass
            self.tunnel_process = None
        self.public_url = ""
        self.inp_pub_url.setText("Đã tắt kết nối Internet từ xa")
        self.lbl_qr_pub.clear()
        self.lbl_qr_pub.setText("Đã tắt Internet Tunnel.\nBấm '🌍 BẬT INTERNET' khi cần dùng 4G.")
        self.btn_toggle_tunnel.setText("🌍 BẬT INTERNET (4G/MỌI NƠI)")
        self.btn_toggle_tunnel.setObjectName("btnPurple")
        self.btn_toggle_tunnel.style().unpolish(self.btn_toggle_tunnel)
        self.btn_toggle_tunnel.style().polish(self.btn_toggle_tunnel)
        self.update_server_ui_state(self.server_running)
        self.update_api_guide_text()
        try:
            if self.server_running:
                requests.post(f"{SERVER_URL}/api/pyside6/tunnel", json={"public_url": ""}, timeout=1.5)
        except Exception:
            pass
        self.log_msg("🔌 Đã tắt đường truyền Internet từ xa (Chỉ còn mạng nội bộ LAN).")

    def open_windows_firewall_port(self):
        cmd = 'netsh advfirewall firewall add rule name="PySide6_Sync_Port_8000" dir=in action=allow protocol=TCP localport=8000'
        res = subprocess.run(["powershell", "-Command", f"Start-Process cmd -ArgumentList '/c {cmd}' -Verb RunAs"], capture_output=True)
        if res.returncode == 0:
            self.log_msg("🛡️ Đã gửi lệnh mở cổng 8000 trên Windows Firewall cho mạng Wi-Fi nội bộ!")
            QMessageBox.information(self, "Tường lửa Windows", "Đã mở cổng 8000 cho mạng Wi-Fi! Điện thoại cùng Wi-Fi có thể truy cập mượt mà.")
        else:
            self.log_msg("⚠️ Không thể mở tường lửa tự động (hoặc bạn đã bấm Hủy). Bạn có thể dùng CÁCH 2 (Bật Internet) để không cần mở tường lửa!")

    def copy_to_clipboard(self, text: str):
        QApplication.clipboard().setText(text)
        self.log_msg(f"📋 Đã copy vào bộ nhớ tạm: {text}")
        QMessageBox.information(self, "Đã Copy", f"Đã copy đường dẫn:\n{text}")

    # ==================== ĐỒNG BỘ DỮ LIỆU VỚI SERVER ====================
    def log_msg(self, text: str):
        now = datetime.now().strftime("%H:%M:%S")
        self.txt_log.append(f"[{now}] {text}")

    def initial_load(self):
        if not self.is_server_alive():
            return
        self.refresh_shared_data()
        self.refresh_submissions()
        self.refresh_users()

    def on_auto_mode_toggled(self, checked: bool):
        self.auto_process_enabled = checked
        if self.server_running:
            try:
                requests.post(f"{SERVER_URL}/api/pyside6/heartbeat", params={"auto_mode": checked}, timeout=1.5)
                self.log_msg(f"Đã chuyển chế độ Tự động xử lý trên PySide6 sang: {'BẬT' if checked else 'TẮT'}")
            except Exception:
                pass

    def periodic_sync(self):
        alive = self.is_server_alive()
        if alive != self.server_running:
            self.server_running = alive
            self.update_server_ui_state(alive)
            if alive:
                self.initial_load()

        if not alive:
            return

        try:
            requests.post(
                f"{SERVER_URL}/api/pyside6/heartbeat",
                params={"auto_mode": self.auto_process_enabled},
                timeout=1.2
            )
            self.check_and_auto_process_submissions()
        except Exception:
            pass

    def refresh_shared_data(self):
        try:
            r = requests.get(f"{SERVER_URL}/api/shared-data", params={"username": "admin", "include_hidden": True}, timeout=2)
            if not r.ok:
                return
            data = r.json()

            metrics = data.get("metrics", [])
            self.tbl_metrics.setRowCount(len(metrics))
            for row_idx, m in enumerate(metrics):
                chk = QTableWidgetItem()
                chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                chk.setCheckState(Qt.Checked if m["is_shared"] else Qt.Unchecked)
                chk.setData(Qt.UserRole, m["metric_key"])
                self.tbl_metrics.setItem(row_idx, 0, chk)
                self.tbl_metrics.setItem(row_idx, 1, QTableWidgetItem(m["label"]))
                self.tbl_metrics.setItem(row_idx, 2, QTableWidgetItem(m["value"]))
                self.tbl_metrics.setItem(row_idx, 3, QTableWidgetItem(m["unit"] or ""))

            items = data.get("items", [])
            self.tbl_items.setRowCount(len(items))
            for row_idx, it in enumerate(items):
                self.tbl_items.setItem(row_idx, 0, QTableWidgetItem(str(it["id"])))

                chk_btn = QPushButton("🟢 Đang Chia Sẻ" if it["is_shared"] else "⚪ Đang Ẩn (Nội bộ)")
                chk_btn.setStyleSheet(
                    "background:#16a34a;padding:4px 8px;" if it["is_shared"] else "background:#475569;padding:4px 8px;"
                )
                item_id = it["id"]
                next_state = 0 if it["is_shared"] else 1
                chk_btn.clicked.connect(lambda _, iid=item_id, ns=next_state: self.toggle_item_share(iid, ns))
                self.tbl_items.setCellWidget(row_idx, 1, chk_btn)

                self.tbl_items.setItem(row_idx, 2, QTableWidgetItem(it["title"]))
                self.tbl_items.setItem(row_idx, 3, QTableWidgetItem(it["allowed_users"]))

                del_btn = QPushButton("🗑️ Xóa")
                del_btn.setObjectName("btnDanger")
                del_btn.clicked.connect(lambda _, iid=item_id: self.delete_shared_item(iid))
                self.tbl_items.setCellWidget(row_idx, 4, del_btn)
        except Exception as e:
            self.log_msg(f"Lỗi tải dữ liệu chia sẻ: {e}")

    def save_metrics_from_table(self):
        if not self.server_running:
            return QMessageBox.warning(self, "Server đang tắt", "Hãy khởi động Server trước!")
        for r in range(self.tbl_metrics.rowCount()):
            chk_item = self.tbl_metrics.item(r, 0)
            metric_key = chk_item.data(Qt.UserRole)
            is_shared = 1 if chk_item.checkState() == Qt.Checked else 0
            label = self.tbl_metrics.item(r, 1).text()
            value = self.tbl_metrics.item(r, 2).text()
            unit = self.tbl_metrics.item(r, 3).text()
            requests.post(f"{SERVER_URL}/api/live-metrics", json={
                "metric_key": metric_key,
                "label": label,
                "value": value,
                "unit": unit,
                "is_shared": is_shared
            }, timeout=2)
        self.log_msg("✅ Đã cập nhật chọn lọc thông số chia sẻ! Giao diện Web/Điện thoại đã thay đổi theo thời gian thực.")
        self.refresh_shared_data()

    def toggle_item_share(self, item_id: int, new_shared: int):
        requests.put(f"{SERVER_URL}/api/shared-items/{item_id}", json={"is_shared": new_shared}, timeout=2)
        state_str = "BẬT CHIA SẺ" if new_shared else "TẮT CHIA SẺ (Ẩn khỏi Điện thoại/Web)"
        self.log_msg(f"📡 Mục #{item_id} đã chuyển sang: {state_str}")
        self.refresh_shared_data()

    def delete_shared_item(self, item_id: int):
        requests.delete(f"{SERVER_URL}/api/shared-items/{item_id}", timeout=2)
        self.log_msg(f"🗑️ Đã xóa mục chia sẻ #{item_id}")
        self.refresh_shared_data()

    def pick_share_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn Hình Ảnh hoặc Tài Liệu", "", "Images (*.png *.jpg *.jpeg *.webp);;All Files (*.*)")
        if path:
            self.selected_share_path = path
            self.lbl_selected_file.setText(os.path.basename(path))

    def push_new_shared_item(self):
        if not self.server_running:
            return QMessageBox.warning(self, "Server đang tắt", "Hãy khởi động Server trước!")
        title = self.inp_share_title.text().strip() or "Báo cáo mới từ PySide6"
        desc = self.inp_share_desc.text().strip()
        allowed = self.inp_share_users.currentText().strip() or "ALL"

        files = None
        if self.selected_share_path and os.path.exists(self.selected_share_path):
            files = {"file": open(self.selected_share_path, "rb")}

        data = {
            "title": title,
            "category": "Xuất từ PySide6",
            "description": desc,
            "is_shared": 1,
            "allowed_users": allowed,
        }
        requests.post(f"{SERVER_URL}/api/shared-items", data=data, files=files, timeout=4)
        if files:
            files["file"].close()
        self.selected_share_path = None
        self.lbl_selected_file.setText("Đã đẩy thành công! (Sẽ tự tạo biểu đồ nếu để trống)")
        self.log_msg(f"🚀 Đã đẩy '{title}' lên chia sẻ cho [{allowed}]!")
        self.refresh_shared_data()

    def check_and_auto_process_submissions(self):
        r = requests.get(f"{SERVER_URL}/api/submissions", params={"username": "__pyside6__", "role": "admin", "light": True}, timeout=2)
        if not r.ok:
            return
        subs = r.json()

        need_ui_refresh = False
        for s in subs:
            if s["status"] == "pending" and self.auto_process_enabled and s.get("auto_process", 1) == 1:
                sub_id = s["id"]
                self.log_msg(f"⚡ [AUTO-PYSIDE6] Nhận yêu cầu mới #{sub_id} từ '{s['username']}': {s['title']} -> Đang tự động phân tích & xuất Báo cáo PDF/A4...")
                requests.post(
                    f"{SERVER_URL}/api/submissions/{sub_id}/process",
                    data={
                        "custom_conclusion": f"Phần mềm máy tính PySide6 đã tự động phân tích ảnh & ghi chú '{s['title']}' của {s['full_name']}. Kết quả: ĐẠT YÊU CẦU.",
                        "processed_by": "PySide6 Desktop Auto-Worker"
                    },
                    timeout=8
                )
                self.log_msg(f"✅ [AUTO-PYSIDE6] Đã xuất Báo cáo #BC-PYSIDE6-{sub_id:04d} (HTML + PDF) và gửi trả về điện thoại/Web của '{s['username']}'!")
                need_ui_refresh = True

        max_id = subs[0]["id"] if subs else 0
        if getattr(self, "_last_max_sub_id", 0) != max_id:
            if getattr(self, "_last_max_sub_id", 0) > 0 and subs:
                newest = subs[0]
                self.log_msg(f"📥 [NHẬN BÁO CÁO MỚI #{newest['id']}] {newest['title']} ({newest.get('note_text','')}) -> Đã xuất PDF/A4 trả về App!")
            self._last_max_sub_id = max_id
            need_ui_refresh = True

        if len(subs) != self.tbl_subs.rowCount() or need_ui_refresh:
            self.populate_submissions_table(subs)

    def refresh_submissions(self):
        try:
            r = requests.get(f"{SERVER_URL}/api/submissions", params={"username": "__pyside6__", "role": "admin", "light": True}, timeout=2)
            if r.ok:
                subs = r.json()
                self._last_max_sub_id = subs[0]["id"] if subs else 0
                self.populate_submissions_table(subs)
        except Exception:
            pass

    def populate_submissions_table(self, subs: list):
        self._cached_subs = subs
        self.tbl_subs.setRowCount(len(subs))
        for idx, s in enumerate(subs):
            self.tbl_subs.setItem(idx, 0, QTableWidgetItem(f"#{s['id']}"))
            self.tbl_subs.setItem(idx, 1, QTableWidgetItem(f"{s['username']} ({s['full_name']})"))
            self.tbl_subs.setItem(idx, 2, QTableWidgetItem(f"{s['title']} | {s.get('note_text') or ''}"))

            st_item = QTableWidgetItem("✓ Đã xuất Báo Cáo" if s["status"] == "completed" else "⏳ Đang chờ xử lý")
            st_item.setForeground(QColor("#4ade80") if s["status"] == "completed" else QColor("#facc15"))
            self.tbl_subs.setItem(idx, 3, st_item)
            self.tbl_subs.setItem(idx, 4, QTableWidgetItem(s.get("processed_at") or s.get("created_at") or ""))

            btn_proc = QPushButton("⚡ Xử lý & Xuất BC")
            sub_id = s["id"]
            btn_proc.clicked.connect(lambda _, sid=sub_id: self.process_single_sub(sid))
            self.tbl_subs.setCellWidget(idx, 5, btn_proc)

    def on_sub_selected(self):
        rows = self.tbl_subs.selectedItems()
        if not rows or not hasattr(self, "_cached_subs"):
            return
        row_idx = self.tbl_subs.currentRow()
        if row_idx < 0 or row_idx >= len(self._cached_subs):
            return
        s = self._cached_subs[row_idx]
        self.lbl_preview_info.setText(
            f"📌 Yêu cầu #{s['id']}: {s['title']} | Người gửi: {s['full_name']} ({s['username']})\n"
            f"📝 Ghi chú: {s.get('note_text') or 'Ghi chú tay trên ảnh'}\n"
            f"✅ Kết luận Báo cáo PySide6: {s.get('report_summary') or 'Chưa xử lý'}"
        )
        img_url = s.get("report_image_url") or s.get("input_image_url")
        if img_url:
            try:
                img_resp = requests.get(f"{SERVER_URL}{img_url}", timeout=2)
                if img_resp.ok:
                    pix = QPixmap()
                    pix.loadFromData(img_resp.content)
                    self.lbl_preview_img.setPixmap(pix.scaled(540, 340, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            except Exception:
                pass

    def process_single_sub(self, sub_id: int):
        conclusion = self.inp_custom_conclusion.text().strip()
        requests.post(
            f"{SERVER_URL}/api/submissions/{sub_id}/process",
            data={"custom_conclusion": conclusion, "processed_by": "PySide6 Manual Approve"},
            timeout=4
        )
        self.log_msg(f"✅ Đã xử lý và gửi lại Báo cáo cho yêu cầu #{sub_id}!")
        self.refresh_submissions()

    def manual_reprocess_selected(self):
        row_idx = self.tbl_subs.currentRow()
        if row_idx < 0 or not hasattr(self, "_cached_subs"):
            QMessageBox.information(self, "Thông báo", "Hãy chọn 1 yêu cầu ở bảng bên trái trước!")
            return
        sub_id = self._cached_subs[row_idx]["id"]
        self.process_single_sub(sub_id)

    def open_selected_sub_pdf(self):
        row_idx = self.tbl_subs.currentRow()
        if row_idx < 0 or not hasattr(self, "_cached_subs"):
            if hasattr(self, "_cached_subs") and self._cached_subs:
                row_idx = 0
            else:
                QMessageBox.information(self, "Thông báo", "Chưa có báo cáo nào để mở!")
                return
        s = self._cached_subs[row_idx]
        target = s.get("report_pdf_url") or s.get("report_html_url")
        if target:
            import webbrowser
            webbrowser.open(f"{SERVER_URL}{target}")
        else:
            QMessageBox.information(self, "Thông báo", "Mục này chưa có file PDF/HTML, hãy bấm xử lý trước!")

    def refresh_users(self):
        try:
            r = requests.get(f"{SERVER_URL}/api/users", timeout=2)
            if not r.ok:
                return
            users = r.json()
            self.tbl_users.setRowCount(len(users))
            for idx, u in enumerate(users):
                self.tbl_users.setItem(idx, 0, QTableWidgetItem(u["username"]))
                self.tbl_users.setItem(idx, 1, QTableWidgetItem(u["password"]))
                self.tbl_users.setItem(idx, 2, QTableWidgetItem(u["full_name"]))
                self.tbl_users.setItem(idx, 3, QTableWidgetItem(u["role"]))
                self.tbl_users.setItem(idx, 4, QTableWidgetItem("✅ Có" if u["can_view"] else "❌ Không"))
                self.tbl_users.setItem(idx, 5, QTableWidgetItem("✅ Có" if u["can_submit"] else "❌ Không (Chỉ xem)"))
                self.tbl_users.setItem(idx, 6, QTableWidgetItem("⚡ Tự động" if u["auto_process"] else "Thủ công"))
        except Exception:
            pass

    def save_user_from_pyside(self):
        if not self.server_running:
            return QMessageBox.warning(self, "Server đang tắt", "Hãy khởi động Server trước!")
        username = self.u_username.text().strip()
        if not username:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập tên tài khoản (Username)!")
            return
        payload = {
            "username": username,
            "password": self.u_password.text().strip() or "123456",
            "full_name": self.u_fullname.text().strip() or username,
            "role": self.u_role.currentText(),
            "can_view": 1 if self.u_can_view.isChecked() else 0,
            "can_submit": 1 if self.u_can_submit.isChecked() else 0,
            "auto_process": 1 if self.u_auto_proc.isChecked() else 0,
            "is_active": 1,
        }
        requests.post(f"{SERVER_URL}/api/users", json=payload, timeout=2)
        self.log_msg(f"🔐 Đã lưu tài khoản '{username}' và đồng bộ phân quyền lên Server!")
        self.u_username.clear()
        self.u_fullname.clear()
        self.refresh_users()

    def closeEvent(self, event):
        if self.tunnel_process:
            try:
                self.tunnel_process.terminate()
            except Exception:
                pass
        if self.server_process:
            try:
                self.server_process.terminate()
            except Exception:
                pass
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = PySide6ControlCenter()
    win.show()
    sys.exit(app.exec())
