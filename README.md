# 📱 HỆ THỐNG KẾT NỐI PYSIDE6 VỚI APP ĐIỆN THOẠI (APK) & APP WEB 2 CHIỀU

Dự án kết nối phần mềm máy tính **PySide6** với **App Điện Thoại (Android APK / PWA)** và **App Web** thông qua **Server trung gian (FastAPI + WebSocket + SQLite)**.

Hệ thống đảm bảo nguyên tắc: **Chỉ phản ánh những dữ liệu mà phần mềm PySide6 cho phép chia sẻ**, đồng thời hỗ trợ người dùng được cấp quyền trên điện thoại **chụp hình + vẽ ghi chú bằng tay** gửi về cho **PySide6 tự động xử lý và trả lại Báo cáo**.

---

## 🚀 1. Cách Chạy Hệ Thống Nhanh Nhất (1-Click)

1. Nháy đúp vào file **`CHAY_HE_THONG.bat`** (hoặc chạy `python pyside6_app/pyside6_main.py`).
2. Cửa sổ phần mềm **PySide6** sẽ mở lên và **tự động khởi động Server ngầm**.
3. Trên thanh điều khiển đầu tiên của **PySide6**, bạn có các nút điều khiển trực tiếp:
   - **`🟢 KHỞI ĐỘNG SERVER` / `🛑 TẮT SERVER`**: Bật hoặc ngắt toàn bộ kết nối từ điện thoại & bên ngoài bất cứ lúc nào.
   - **`🌍 BẬT INTERNET (4G/MỌI NƠI)` / `🔌 TẮT INTERNET`**: Tạo đường link **HTTPS toàn cầu miễn phí** kèm **Mã QR** để điện thoại dùng 4G/5G ở bất kỳ đâu truy cập được ngay.
   - **`🌐 Mở App Web`**: Mở giao diện App trên trình duyệt.

---

## 🔑 2. Tài Khoản Mặc Định Để Test Phân Quyền

| Tài khoản | Mật khẩu | Vai trò | Quyền hạn |
| :--- | :--- | :--- | :--- |
| **`admin`** | `admin123` | Quản trị viên | Toàn quyền: Tạo TK/MK, cấp quyền, xem mọi dữ liệu chia sẻ, gửi xử lý báo cáo |
| **`nhanvien1`** | `123456` | Nhân viên hiện trường | Xem dữ liệu được phép chia sẻ + Chụp hình & vẽ ghi chú tay gửi PySide6 tự xử lý |
| **`khach1`** | `123456` | Khách / Giám sát | **Chỉ Xem** dữ liệu công khai (`ALL`), bị khóa tính năng gửi yêu cầu xử lý |

---

## ✨ 3. Các Tính Năng Chính

### 🖥️ Phía Phần Mềm Máy Tính (PySide6 - `pyside6_app/pyside6_main.py`)
1. **Tab 1 — Kết nối Điện thoại (Wi-Fi / 4G) & App khác:**
   - Hiển thị trực tiếp **Mã QR mạng Wi-Fi nội bộ (LAN)** và **Mã QR mạng Internet toàn cầu (4G/5G)**.
   - Có nút **`🛡️ Mở Tường Lửa Windows`** tự động mở cổng `8000` cho mạng nội bộ.
   - Cung cấp tài liệu & code mẫu API để các phần mềm/app khác kết nối vào.
2. **Tab 2 — Chọn dữ liệu chia sẻ lên Web/APK:**
   - Tick chọn từng thông số thời gian thực hoặc từng hình ảnh/báo cáo muốn chia sẻ.
   - Khi bật/tắt chia sẻ trên PySide6, màn hình Điện thoại/Web tự động cập nhật ngay lập tức qua WebSocket.
3. **Tab 3 — Nhận Ảnh/Ghi chú & Tự động trả Báo cáo:**
   - Tự động lắng nghe yêu cầu từ các tài khoản có quyền (`Auto-Process`).
   - Tự động phân tích, đóng dấu xác nhận lên hình ảnh ghi chú tay và xuất Báo cáo (kèm bản in PDF/HTML) trả về cho điện thoại.
4. **Tab 4 — Quản lý Tài khoản & Phân quyền:**
   - Tạo tài khoản mới, đổi mật khẩu, bật/tắt quyền Xem, quyền Gửi xử lý và quyền Tự động xử lý trên PySide6.

### 📱 Phía App Điện Thoại (APK / PWA) & Web (`web/index.html`)
- **Xem Thời Gian Thực:** Chỉ hiển thị đúng những thông số và tài liệu mà PySide6 đã đánh dấu chia sẻ cho tài khoản đang đăng nhập.
- **Chụp Hình & Viết Ghi Chú Bằng Tay:**
  - Mở trực tiếp Camera điện thoại chụp hình hiện trường/tài liệu hoặc chọn ảnh từ máy.
  - Bảng vẽ cảm ứng (**Touch Canvas**) cho phép dùng ngón tay khoanh vùng, viết chữ ghi chú nhiều màu trực tiếp lên ảnh.
- **Nhận Báo Cáo Tự Động:**
  - Nhận kết quả xử lý từ PySide6 theo thời gian thực, xem bảng thông số đánh giá và tải/in Báo cáo định dạng chuẩn PDF/HTML.

---

## 🔌 4. Chuẩn API Để Kết Nối Từ App Khác

Mọi ứng dụng khác (App Android APK độc lập, Web khác, phần mềm Python/C#/Excel) đều có thể kết nối vào Server qua các cổng sau:

- **Đăng nhập:** `POST /api/login` — Body JSON: `{"username": "...", "password": "..."}`
- **Lấy dữ liệu PySide6 chia sẻ:** `GET /api/shared-data?username=nhanvien1`
- **Gửi ảnh & ghi chú lên PySide6 xử lý:** `POST /api/submissions` (`multipart/form-data`: `username`, `title`, `note_text`, `image_file` hoặc `canvas_base64`)
- **Lấy danh sách Báo cáo kết quả:** `GET /api/submissions?username=nhanvien1`
- **Đồng bộ thời gian thực:** `WS /ws`

---

## ☁️ 5. Triển Khai Chạy 24/7 Trên Đám Mây (Khi Cần Dùng Sau Này)

Dự án đã tích hợp sẵn bộ cấu hình Cloud 24/7 (`requirements.txt`, `Dockerfile`, `render.yaml`):
- **Render.com / Railway.app:** Kết nối trực tiếp vào kho GitHub này, hệ thống sẽ tự động đọc `render.yaml` hoặc `Dockerfile` để chạy `server.server_app:app` 24/7 với đường link `https://...` cố định vĩnh viễn.

---

## 📂 Cấu Trúc Thư Mục

```text
├── CHAY_HE_THONG.bat          # File chạy nhanh toàn bộ hệ thống (1-Click)
├── README.md                  # Tài liệu hướng dẫn sử dụng & kết nối
├── requirements.txt           # Danh sách thư viện Python
├── Dockerfile                 # Cấu hình đóng gói Docker chạy 24/7
├── render.yaml                # Cấu hình triển khai Cloud Render.com tự động
├── server/
│   └── server_app.py          # Server trung gian (FastAPI + WebSocket + SQLite)
├── pyside6_app/
│   └── pyside6_main.py        # Phần mềm máy tính PySide6 (Quản lý Server & Xử lý tự động)
└── web/
    ├── index.html             # Giao diện App Điện thoại (PWA/APK) & Web
    ├── manifest.json          # Cấu hình cài đặt App lên màn hình chính điện thoại
    └── sw.js                  # Service Worker hỗ trợ Web App
```
