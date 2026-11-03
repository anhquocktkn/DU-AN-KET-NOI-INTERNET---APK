# 📱 HỆ THỐNG QUẢN LÝ BÁO CÁO ALLSEA MANAGEMENT — KẾT NỐI PYSIDE6, WEB & APK 2 CHIỀU

Hệ thống kết nối 2 chiều giữa phần mềm máy tính **PySide6**, **App Điện Thoại (Android APK / PWA)** và **Web Application** thông qua **Server trung gian FastAPI + WebSocket + SQLite**.

Dự án phục vụ lập báo cáo kỹ thuật, báo cáo ngày hiện trường tàu biển cho **ALLSEA MANAGEMENT JSC**, hỗ trợ người dùng điện thoại chụp ảnh, lập báo cáo offline/online, tự động chuyển về máy tính Python xử lý, xuất PDF chuẩn in A4 và tự động gửi Email báo cáo kèm file PDF theo giờ hẹn (`HH:MM`).

---

## 🚀 1. Cách Khởi Động Nhanh (1-Click)

1. Nháy đúp vào file **`CHAY_HE_THONG.bat`** (hoặc chạy lệnh: `python pyside6_app/pyside6_main.py`).
2. Cửa sổ điều khiển **PySide6** mở lên và **tự động khởi động FastAPI Server (Cổng 8000)**.
3. Các nút điều khiển chính trên giao diện PySide6:
   - **`🟢 KHỞI ĐỘNG SERVER` / `🛑 TẮT SERVER`**: Bật/tắt toàn bộ kết nối từ điện thoại và bên ngoài.
   - **`🌍 BẬT INTERNET (4G/MỌI NƠI)`**: Tự động tạo link **HTTPS toàn cầu miễn phí** kèm **Mã QR** để điện thoại 4G/5G ở bất kỳ đâu quét vào ngay.
   - **`🌐 Mở App Web`**: Mở trực tiếp giao diện Web trên trình duyệt máy tính.

---

## 🔑 2. Tài Khoản Phân Quyền Mặc Định

| Tài khoản | Mật khẩu | Vai trò | Quyền hạn |
| :--- | :--- | :--- | :--- |
| **`admin`** | `admin123` | Quản trị viên | Full quyền: Quản lý người dùng, xem dữ liệu, duyệt/xuất báo cáo PDF, gửi/hẹn giờ Email |
| **`nhanvien1`** | `123456` | Kỹ thuật / Hiện trường | Xem dữ liệu chia sẻ + Lập báo cáo, chụp ảnh hiện trường, xuất PDF, gửi xử lý |
| **`khach1`** | `123456` | Giám sát / Khách | **Chỉ xem** dữ liệu được phân quyền, khóa tính năng gửi báo cáo |

---

## ✨ 3. Các Điểm Nâng Cấp Đột Phá Mới

### ✏️ 1. 100% Nội Dung Trên Báo Cáo Đều Sửa Được (Không Cố Định Chữ Nào)
- Người dùng có thể sửa trực tiếp mọi chữ trên biểu mẫu:
  - **Tên công ty:** Dòng 1 (*ALLSEA MANAGEMENT JSC*), Dòng 2 (*CÔNG TY CỔ PHẦN ALLSEA MANAGEMENT*), Logo công ty.
  - **Tiêu đề báo cáo:** Chọn nhanh (*BÁO CÁO NGÀY*, *BÁO CÁO LÊN ĐÀ - DOCKING*, *BÁO CÁO KỸ THUẬT KHÁC*) hoặc tự gõ tay chữ bất kỳ.
  - **Nhãn & Giá trị:** Nhãn tàu (*Ship's name :*), Nhãn người báo cáo (*Superintendent :*), Nhãn phân loại (*Items :*), Ngày báo cáo, Lời chào (*Kính gửi: BAN LÃNH ĐẠO CÔNG TY.*).
  - **Tiêu đề các mục:** Tiêu đề mục A (*A. HẠNG MỤC PHÁT SINH:*), Tiêu đề mục B (*B. NỘI DUNG CÔNG VIỆC HẰNG NGÀY:*), toàn bộ 4 tiêu đề cột bảng công việc (*STT*, *NỘI DUNG CÔNG VIỆC*, *PHƯƠNG ÁN SỬA CHỮA*, *TIẾN ĐỘ*), Tiêu đề mục C (*C. MỘT SỐ HÌNH ẢNH SỬA TRONG NGÀY:*).
  - **Ghi chú & Chữ ký chân trang:** Thêm ghi chú/chữ ký tùy ý ở cuối báo cáo.
  - **Chế độ Sửa trực tiếp trên trang A4 (`contenteditable`):** Bấm nút `✏️ Sửa Chữ Trực Tiếp Trên Trang A4` để click và sửa trực tiếp từng chữ ngay trên trang in A4 trước khi xuất PDF.

### ⚡ 2. Tối Ưu Truyền Dẫn & Tải Siêu Tốc Qua Mạng 4G/5G
- **GZipMiddleware:** Bật nén luồng HTTP tự động, giảm kích thước HTML/JSON truyền tải từ **150 KB xuống chỉ còn ~20-25 KB** (tiết kiệm 85% băng thông 4G).
- **Chế độ nén ảnh 4G/5G:** Tùy chọn `⚡ Siêu tốc 4G/5G` tự động nén tối ưu ảnh hiện trường xuống ~25 KB/ảnh, tải lên cực nhanh kể cả khi sóng 4G/5G yếu.
- **Tối ưu file PDF:** Tự động tạo ảnh thumbnail chuẩn in cho lưới 4 cột, giúp file PDF 12 ảnh giảm dung lượng từ **2.6 MB xuống chỉ còn ~200-600 KB**, tải về điện thoại chỉ mất chưa tới 1 giây.
- **Cache-Control:** Đặt bộ nhớ đệm HTTP cho các tài nguyên web cố định (Logo, icon, ảnh tĩnh), tránh tải lại nhiều lần.

### 📧 3. Tác Vụ Gửi Email Báo Cáo PDF & Hẹn Giờ Tự Động (`HH:MM`)
- **Gửi ngay lập tức:** Xuất PDF xong tự động đính kèm file PDF chuẩn A4 gửi tới danh sách email đã chọn.
- **Hẹn giờ gửi tự động (`HH:MM`):** Người dùng có thể hẹn giờ gửi cho từng báo cáo (ví dụ: `17:00` cuối ngày) hoặc bật chế độ tự động gửi toàn bộ báo cáo trong ngày vào giờ cố định `HH:MM`. Tiến trình nền Python Daemon Worker liên tục quét và thực thi chuẩn xác.
- **Danh bạ Email lưu sẵn (`email_contacts`):** Lưu các địa chỉ email thường dùng (Ban giám đốc, phòng kỹ thuật, phòng vật tư...). Lần sau chỉ cần bấm 1 chạm để chọn nhanh, không phải gõ lại.
- **Hộp thư Outbox chuẩn `.eml`:** Tự động đóng gói và lưu bản sao thư điện tử kèm tệp `.pdf` vào thư mục outbox, đảm bảo lưu vết đầy đủ kể cả khi chưa cấu hình máy chủ SMTP ngoài.

### 💾 4. Tách Biệt Thư Mục Lưu Trữ Khỏi Thư Mục Code
- Toàn bộ dữ liệu cơ sở dữ liệu (`app_system.db`), ảnh tải lên (`uploads/`), file báo cáo PDF (`reports/`), file chia sẻ (`shared_files/`) và email lưu trữ (`emails_outbox/`) được lưu tại:
  - **`e:\DU_AN_ALLSEA_STORAGE_DATA\`** (Nằm hoàn toàn ngoài thư mục mã nguồn git).
- Kho Git luôn nhẹ, sạch, không bị phình to khi sinh ra hàng trăm báo cáo và ảnh hiện trường, đồng thời bảo mật dữ liệu tàu thực tế trước khi push lên GitHub.

### 📱 5. Chế Độ Làm Việc Offline Trên Điện Thoại (APK)
- Khi ra công trường mất sóng điện thoại/mất mạng Wi-Fi, người dùng vẫn nhập dữ liệu, chụp ảnh bình thường và bấm **`💾 LƯU OFFLINE`**.
- Báo cáo được lưu an toàn trong bộ nhớ thiết bị. Khi có mạng trở lại, hệ thống sẽ hiện thông báo và chỉ cần bấm **`🚀 Đồng Bộ Về Python`** để tự động xử lý và xuất PDF.

### 📑 6. Giao Diện 2 Tab Tích Hợp Sẵn
- **Tab 1: Bảng điều khiển Đội tàu Allsea (Google Sheets):** Giữ giao diện theo dõi tổng thể đội tàu trực tuyến, mở lên là có đầy đủ nội dung ngay.
- **Tab 2: Hệ thống App Kết Nối & Lập Báo Cáo:** Chứa toàn bộ giao diện làm việc thời gian thực với PySide6, lập báo cáo, xem kết quả và quản trị.

---

## 🔌 4. Hệ Thống Endpoint API

- `POST /api/login`: Đăng nhập xác thực và kiểm tra phân quyền.
- `GET  /api/shared-data`: Lấy các thông số và tài liệu PySide6 chia sẻ.
- `POST /api/submissions-json`: Đẩy biểu mẫu báo cáo kèm ảnh dung lượng lớn từ Web/Điện thoại về Python.
- `GET  /api/submissions`: Lấy danh sách báo cáo kết quả, file HTML và file PDF.
- `POST /api/submissions/{id}/process`: Xử lý và phê duyệt xuất báo cáo PDF/HTML.
- `GET  /api/email/settings`: Lấy thông số cấu hình Email, giờ hẹn HH:MM và danh bạ email đã lưu.
- `POST /api/email/settings`: Lưu cấu hình Email, giờ hẹn tự động HH:MM hàng ngày.
- `POST /api/email/contacts`: Thêm mới địa chỉ email vào danh bạ chọn nhanh.
- `DELETE /api/email/contacts/{id}`: Xóa địa chỉ email khỏi danh bạ.
- `POST /api/email/send`: Gửi email ngay hoặc đặt lịch hẹn giờ gửi (`HH:MM`).
- `DELETE /api/submissions/{id}`: Xóa báo cáo và dọn dẹp các tệp liên quan.
- `WS   /ws`: Kênh WebSocket đồng bộ dữ liệu thời gian thực.

---

## 📂 Cấu Trúc Dự Án

```text
├── CHAY_HE_THONG.bat          # File 1-click khởi động toàn bộ PySide6 và FastAPI Server
├── README.md                  # Tài liệu hướng dẫn sử dụng & kết nối
├── requirements.txt           # Thư viện Python (PySide6, FastAPI, Uvicorn, PyMuPDF, Pillow,...)
├── Dockerfile                 # Cấu hình đóng gói Docker chạy Cloud 24/7
├── render.yaml                # Cấu hình triển khai Cloud tự động
├── server/
│   └── server_app.py          # Server trung gian (FastAPI + WebSocket + SQLite + Email Engine)
├── pyside6_app/
│   └── pyside6_main.py        # Ứng dụng Desktop PySide6 quản lý kết nối, duyệt & gửi Email
├── web/
│   ├── index.html             # App Web & APK (Biểu mẫu báo cáo tùy chỉnh 100%, 4G nén nhanh, Email)
│   ├── manifest.json          # Cấu hình cài đặt Web App lên màn hình chính điện thoại (PWA)
│   ├── sw.js                  # Service Worker hỗ trợ Offline
│   └── allsea_logo.png        # Logo Allsea cố định cho giao diện
└── index.html                 # Bản build web đồng bộ tại thư mục gốc
```
*(Thư mục dữ liệu người dùng & báo cáo thực tế được lưu độc lập tại `e:\DU_AN_ALLSEA_STORAGE_DATA\`)*
