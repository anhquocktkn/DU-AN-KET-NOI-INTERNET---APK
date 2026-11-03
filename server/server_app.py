import os
import io
import json
import time
import base64
import socket
import sqlite3
import smtplib
import threading
from email.message import EmailMessage
from datetime import datetime
from typing import List, Optional
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

try:
    import pymupdf
    HAS_PYMUPDF = True
except Exception:
    HAS_PYMUPDF = False

BASE_DIR = Path(__file__).resolve().parent.parent
# Lưu toàn bộ Database, Ảnh Upload, Báo cáo PDF/HTML và Email Outbox RA NGOÀI thư mục code để tránh làm nặng Git & đồng bộ
DATA_DIR = Path(os.environ.get("ALLSEA_STORAGE_DIR", str(BASE_DIR.parent / "DU_AN_ALLSEA_STORAGE_DATA")))
UPLOADS_DIR = DATA_DIR / "uploads"
REPORTS_DIR = DATA_DIR / "reports"
SHARED_FILES_DIR = DATA_DIR / "shared_files"
EMAIL_OUTBOX_DIR = DATA_DIR / "emails_outbox"
WEB_DIR = BASE_DIR / "web"

for d in [DATA_DIR, UPLOADS_DIR, REPORTS_DIR, SHARED_FILES_DIR, EMAIL_OUTBOX_DIR, WEB_DIR]:
    d.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "app_system.db"

app = FastAPI(title="PySide6 <-> Web/APK Sync Server")

# Nén GZip tự động giúp tăng tốc độ tải trang và truyền JSON qua 4G/5G nhanh gấp 5-7 lần
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")
app.mount("/shared_files", StaticFiles(directory=str(SHARED_FILES_DIR)), name="shared_files")
app.mount("/emails_outbox", StaticFiles(directory=str(EMAIL_OUTBOX_DIR)), name="emails_outbox")


def get_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def make_qr_base64(url: str) -> str:
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")


def get_db():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def create_sample_shared_image(filename: str, title: str, subtitle: str, color=(22, 78, 99)):
    filepath = SHARED_FILES_DIR / filename
    if filepath.exists():
        return f"/shared_files/{filename}"
    img = Image.new("RGB", (800, 450), color=color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([25, 25, 775, 425], outline=(56, 189, 248), width=3)
    draw.rectangle([45, 45, 755, 115], fill=(15, 23, 42))
    draw.text((65, 68), title, fill=(56, 189, 248))
    draw.text((65, 150), subtitle, fill=(241, 245, 249))
    draw.text((65, 210), f"Thoi gian xuat tu PySide6: {datetime.now().strftime('%d/%m/%Y %H:%M')}", fill=(148, 163, 184))
    bars = [120, 190, 150, 240, 210, 270]
    for i, h in enumerate(bars):
        x0 = 80 + i * 105
        y0 = 390 - int(h * 0.45)
        draw.rectangle([x0, y0, x0 + 65, 390], fill=(34, 197, 94) if i % 2 == 0 else (59, 130, 246))
    img.save(str(filepath), "PNG")
    return f"/shared_files/{filename}"


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        can_view INTEGER NOT NULL DEFAULT 1,
        can_submit INTEGER NOT NULL DEFAULT 1,
        auto_process INTEGER NOT NULL DEFAULT 1,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS shared_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        category TEXT NOT NULL,
        description TEXT,
        file_url TEXT,
        file_type TEXT DEFAULT 'image',
        is_shared INTEGER NOT NULL DEFAULT 1,
        allowed_users TEXT NOT NULL DEFAULT 'ALL',
        updated_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS live_metrics (
        metric_key TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        value TEXT NOT NULL,
        unit TEXT DEFAULT '',
        is_shared INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        full_name TEXT NOT NULL,
        title TEXT NOT NULL,
        note_text TEXT,
        task_type TEXT DEFAULT 'Phan tich & Bao cao',
        input_image_url TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        auto_process INTEGER NOT NULL DEFAULT 1,
        report_summary TEXT,
        report_data_json TEXT,
        report_image_url TEXT,
        report_html_url TEXT,
        created_at TEXT NOT NULL,
        processed_at TEXT
    )
    """)
    for col_sql in [
        "ALTER TABLE submissions ADD COLUMN form_payload_json TEXT",
        "ALTER TABLE submissions ADD COLUMN report_pdf_url TEXT",
        "ALTER TABLE submissions ADD COLUMN email_status TEXT DEFAULT 'unsent'",
        "ALTER TABLE submissions ADD COLUMN email_recipients TEXT DEFAULT ''",
        "ALTER TABLE submissions ADD COLUMN email_subject TEXT DEFAULT ''",
        "ALTER TABLE submissions ADD COLUMN email_schedule_hhmm TEXT DEFAULT ''",
        "ALTER TABLE submissions ADD COLUMN email_sent_at TEXT DEFAULT ''",
    ]:
        try:
            cur.execute(col_sql)
        except Exception:
            pass

    cur.execute("""
    CREATE TABLE IF NOT EXISTS email_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        smtp_host TEXT NOT NULL DEFAULT 'smtp.gmail.com',
        smtp_port INTEGER NOT NULL DEFAULT 587,
        sender_email TEXT NOT NULL DEFAULT '',
        sender_password TEXT NOT NULL DEFAULT '',
        sender_name TEXT NOT NULL DEFAULT 'ALLSEA MANAGEMENT REPORT',
        default_recipients TEXT NOT NULL DEFAULT 'banlanhdao@allsea.com.vn',
        default_subject TEXT NOT NULL DEFAULT '[ALLSEA REPORT] {report_header_title} - {ship_name} ({report_date})',
        default_body TEXT NOT NULL DEFAULT 'Kính gửi Ban Lãnh Đạo,\n\nHệ thống gửi đính kèm file Báo cáo PDF: {report_header_title} - Tàu {ship_name} ({report_date}).\nNgười báo cáo: {reporter}.\n\nTrân trọng,\nALLSEA MANAGEMENT JSC',
        auto_send_enabled INTEGER NOT NULL DEFAULT 0,
        schedule_time_hhmm TEXT NOT NULL DEFAULT '17:00',
        last_auto_sent_date TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT ''
    )
    """)

    cur.execute("SELECT COUNT(*) as cnt FROM email_settings")
    if cur.fetchone()["cnt"] == 0:
        cur.execute("""
            INSERT INTO email_settings (id, smtp_host, smtp_port, sender_email, sender_password, sender_name, default_recipients, auto_send_enabled, schedule_time_hhmm, updated_at)
            VALUES (1, 'smtp.gmail.com', 587, '', '', 'ALLSEA MANAGEMENT REPORT', 'banlanhdao@allsea.com.vn', 0, '17:00', ?)
        """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))

    cur.execute("""
    CREATE TABLE IF NOT EXISTS email_contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE,
        label TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("SELECT COUNT(*) as cnt FROM email_contacts")
    if cur.fetchone()["cnt"] == 0:
        now_c = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.executemany("""
            INSERT INTO email_contacts (email, label, created_at) VALUES (?, ?, ?)
        """, [
            ("banlanhdao@allsea.com.vn", "Ban Lãnh Đạo Công Ty", now_c),
            ("kythuat@allsea.com.vn", "Phòng Kỹ Thuật Tàu Biển", now_c),
            ("vattu@allsea.com.vn", "Bộ Phận Vật Tư & Cung Ứng", now_c),
        ])

    cur.execute("SELECT COUNT(*) as cnt FROM users")
    if cur.fetchone()["cnt"] == 0:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        default_users = [
            ("admin", "admin123", "Quản Trị Viên (Full Quyền)", "admin", 1, 1, 1, 1, now),
            ("nhanvien1", "123456", "Nhân Viên Hiện Trường 01", "staff", 1, 1, 1, 1, now),
            ("khach1", "123456", "Khách Hàng / Giám Sát (Chỉ Xem)", "viewer", 1, 0, 0, 1, now),
        ]
        cur.executemany("""
            INSERT INTO users (username, password, full_name, role, can_view, can_submit, auto_process, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, default_users)

    cur.execute("SELECT COUNT(*) as cnt FROM live_metrics")
    if cur.fetchone()["cnt"] == 0:
        now = datetime.now().strftime("%H:%M:%S")
        metrics = [
            ("pyside_status", "Trạng thái máy chủ PySide6", "Đang hoạt động (Auto)", "", 1, now),
            ("active_line", "Tiến độ xử lý trong ngày", "86.5", "%", 1, now),
            ("completed_docs", "Hồ sơ / Báo cáo đã xuất", "42", "bộ", 1, now),
            ("internal_secret", "Chi phí nội bộ (Không chia sẻ)", "145,000,000", "VNĐ", 0, now),
        ]
        cur.executemany("""
            INSERT INTO live_metrics (metric_key, label, value, unit, is_shared, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, metrics)

    cur.execute("SELECT COUNT(*) as cnt FROM shared_items")
    if cur.fetchone()["cnt"] == 0:
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        img1 = create_sample_shared_image(
            "bieu_do_tien_do.png",
            "BAO CAO TIEN DO TRUC TUYEN TU PYSIDE6",
            "Du lieu thong ke san luong & trang thai he thong (Da duyet chia se)",
            color=(15, 52, 96)
        )
        img2 = create_sample_shared_image(
            "so_do_kiem_tra.png",
            "HINH ANH KIEM TRA KY THUAT CA SANG",
            "Chi chia se cho tai khoan Admin va Nhan Vien 01",
            color=(30, 58, 47)
        )
        img3 = create_sample_shared_image(
            "tai_lieu_noi_bo.png",
            "DU LIEU NOI BO TREN MAY TINH PYSIDE6",
            "Muc nay dang TAT chia se - Dien thoai/Web se KHONG nhin thay",
            color=(76, 29, 49)
        )
        items = [
            ("Biểu đồ Tiến độ & Sản lượng Thời gian thực", "Báo cáo nhanh", "Dữ liệu xuất trực tiếp từ phần mềm PySide6 cho tất cả tài khoản được phép xem.", img1, "image", 1, "ALL", now),
            ("Bản vẽ / Hình ảnh Kiểm tra Kỹ thuật Ca Sáng", "Hình ảnh kỹ thuật", "Chỉ tài khoản Admin và nhanvien1 được phân quyền nhìn thấy mục này.", img2, "image", 1, "admin,nhanvien1", now),
            ("Báo cáo Tài chính Nội bộ (Chỉ lưu trên PySide6)", "Nội bộ", "Đang tắt nút Chia sẻ trên PySide6 -> Web và APK hoàn toàn không thấy.", img3, "image", 0, "admin", now),
        ]
        cur.executemany("""
            INSERT INTO shared_items (title, category, description, file_url, file_type, is_shared, allowed_users, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, items)

    conn.commit()
    conn.close()


init_db()


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.pyside6_last_seen: float = time.time()
        self.pyside6_auto_mode: bool = True
        self.public_tunnel_url: str = ""

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, event_type: str, payload: dict):
        message = json.dumps({"event": event_type, "data": payload, "ts": datetime.now().strftime("%H:%M:%S")})
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                dead.append(connection)
        for d in dead:
            self.disconnect(d)


manager = ConnectionManager()


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreateUpdate(BaseModel):
    username: str
    password: Optional[str] = "123456"
    full_name: str
    role: str = "staff"
    can_view: int = 1
    can_submit: int = 1
    auto_process: int = 1
    is_active: int = 1


class SharedItemToggle(BaseModel):
    is_shared: Optional[int] = None
    allowed_users: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None


class MetricUpdate(BaseModel):
    metric_key: str
    label: str
    value: str
    unit: str = ""
    is_shared: int = 1


class TunnelUpdate(BaseModel):
    public_url: str = ""


def extract_and_save_form_photos(form_payload_json: Optional[str], prefix: str):
    """Giải nén toàn bộ ảnh Base64 trong form_payload_json ra file vật lý trong /uploads/,
    đồng thời tạo bản nén nhẹ cho PDF để giảm dung lượng PDF từ vài MB xuống ~160KB (tối ưu 4G/5G & Email)."""
    if not form_payload_json:
        return None, None, ""
    try:
        data = json.loads(form_payload_json) if isinstance(form_payload_json, str) else dict(form_payload_json)
    except Exception:
        return form_payload_json, None, ""

    first_saved_path: Optional[Path] = None
    first_saved_url: str = ""

    # Xử lý logo nếu là base64
    logo_val = data.get("logo_url") or ""
    if isinstance(logo_val, str) and logo_val.startswith("data:image") and "," in logo_val:
        try:
            raw = base64.b64decode(logo_val.split(",", 1)[1])
            l_name = f"{prefix}_logo.png"
            (UPLOADS_DIR / l_name).write_bytes(raw)
            data["logo_url"] = f"/uploads/{l_name}"
        except Exception:
            data["logo_url"] = "/allsea_logo.png"
    elif isinstance(logo_val, str) and "/allsea_logo.png" in logo_val:
        data["logo_url"] = "/allsea_logo.png"

    photos = data.get("photos") or []
    cleaned_photos = []
    for idx, p in enumerate(photos):
        src = p.get("src") if isinstance(p, dict) else (p if isinstance(p, str) else "")
        caption = p.get("caption", "") if isinstance(p, dict) else ""
        if isinstance(src, str) and src.startswith("data:image") and "," in src:
            try:
                _, b64_part = src.split(",", 1)
                raw_bytes = base64.b64decode(b64_part)
                fname = f"{prefix}_p{idx + 1}.jpg"
                fpath = UPLOADS_DIR / fname
                # Nén chuẩn Web/4G & tạo bản thu nhỏ cho PDF
                im = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
                im_web = im.copy()
                im_web.thumbnail((760, 760))
                im_web.save(str(fpath), "JPEG", quality=78, optimize=True)

                pdf_thumb_name = f"{prefix}_p{idx + 1}_pdf.jpg"
                im_pdf = im.copy()
                im_pdf.thumbnail((380, 280))
                im_pdf.save(str(UPLOADS_DIR / pdf_thumb_name), "JPEG", quality=72, optimize=True)

                url_path = f"/uploads/{fname}"
                if first_saved_path is None:
                    first_saved_path = fpath
                    first_saved_url = url_path
                cleaned_photos.append({"src": url_path, "pdf_src": pdf_thumb_name, "caption": caption})
            except Exception:
                pass
        elif isinstance(src, str) and src:
            cleaned_photos.append({
                "src": src,
                "pdf_src": p.get("pdf_src", "") if isinstance(p, dict) else "",
                "caption": caption
            })
            if first_saved_path is None and src.startswith("/uploads/"):
                cand = UPLOADS_DIR / src.replace("/uploads/", "")
                if cand.exists():
                    first_saved_path = cand
                    first_saved_url = src

    data["photos"] = cleaned_photos
    return json.dumps(data, ensure_ascii=False), first_saved_path, first_saved_url


def resolve_local_photo_path(src: str) -> Optional[Path]:
    if not src or not isinstance(src, str):
        return None
    if src.startswith("/uploads/"):
        p = UPLOADS_DIR / src.replace("/uploads/", "")
        if p.exists():
            return p
    if src.startswith("/reports/"):
        p = REPORTS_DIR / src.replace("/reports/", "")
        if p.exists():
            return p
    p_web = WEB_DIR / src.lstrip("/")
    if p_web.exists():
        return p_web
    return None


def _get_str_field(form_data: dict, key: str, default_val: str) -> str:
    """Cho phép người dùng sửa hoặc xóa trắng bất kỳ trường chữ nào trên báo cáo (không ép chữ cố định)."""
    if key in form_data and form_data[key] is not None:
        return str(form_data[key])
    return default_val


def generate_report_files(sub_id: int, title: str, username: str, full_name: str, note_text: str, task_type: str, input_image_path: Optional[Path], custom_conclusion: Optional[str] = None, form_payload_json: Optional[str] = None):
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    report_code = f"BC-PYSIDE6-{sub_id:04d}"

    # Đảm bảo ảnh base64 (nếu còn) được lưu thành file vật lý
    if form_payload_json and "data:image" in form_payload_json:
        form_payload_json, extracted_path, _ = extract_and_save_form_photos(form_payload_json, f"sub_{sub_id}")
        if input_image_path is None and extracted_path is not None:
            input_image_path = extracted_path

    form_data = {}
    if form_payload_json:
        try:
            form_data = json.loads(form_payload_json)
        except Exception:
            form_data = {}

    # Toàn bộ các nhãn và tiêu đề đều đọc từ form_data (không cố định chữ nào)
    company_title = _get_str_field(form_data, "company_title", "ALLSEA MANAGEMENT JSC")
    company_subtitle = _get_str_field(form_data, "company_subtitle", "CÔNG TY CỔ PHẦN ALLSEA MANAGEMENT")
    rep_header_title = _get_str_field(form_data, "report_header_title", "BÁO CÁO NGÀY")
    label_ship = _get_str_field(form_data, "label_ship", "Ship's name :")
    ship_name = _get_str_field(form_data, "ship_name", "LS JUPITER")
    label_reporter = _get_str_field(form_data, "label_reporter", "Superintendent :")
    reporter_name = _get_str_field(form_data, "reporter", full_name)
    label_items = _get_str_field(form_data, "label_items", "Items :")
    item_type_str = _get_str_field(form_data, "item_type", task_type)
    salutation_str = _get_str_field(form_data, "salutation", "Kính gửi: BAN LÃNH ĐẠO CÔNG TY.")
    report_date_str = _get_str_field(form_data, "report_date", datetime.now().strftime("Ngày %d/%m/%Y"))
    sec_a_title = _get_str_field(form_data, "sec_a_title", "A. HẠNG MỤC PHÁT SINH:")
    arising_str = _get_str_field(form_data, "arising_text", "")
    sec_b_title = _get_str_field(form_data, "sec_b_title", "B. NỘI DUNG CÔNG VIỆC HẰNG NGÀY:")
    sec_c_title = _get_str_field(form_data, "sec_c_title", "C. MỘT SỐ HÌNH ẢNH SỬA TRONG NGÀY:")
    footer_note = _get_str_field(form_data, "footer_note", "")

    rows = form_data.get("rows") or []
    photos = form_data.get("photos") or []
    rows_count = len(rows)
    photos_count = len(photos)
    conclusion = custom_conclusion or f"PySide6 da tong hop '{rep_header_title}' - {ship_name} ({rows_count} hang muc, {photos_count} hinh anh)."

    # Xuất ảnh Preview định dạng JPEG nén nhẹ (~50KB thay vì ~500KB PNG) để tải qua 4G/5G siêu nhanh
    out_img_name = f"report_img_{sub_id}_{int(time.time())}.jpg"
    out_img_path = REPORTS_DIR / out_img_name

    photo_paths: List[Path] = []
    for p in photos[:12]:
        src = p.get("src") if isinstance(p, dict) else p
        loc = resolve_local_photo_path(src)
        if loc:
            photo_paths.append(loc)
    if not photo_paths and input_image_path and input_image_path.exists():
        photo_paths.append(input_image_path)

    canvas_w = 820
    if len(photo_paths) > 1:
        cols = 4
        grid_rows = (len(photo_paths) + cols - 1) // cols
        cell_w, cell_h = 185, 130
        grid_h = grid_rows * (cell_h + 10) + 10
        canvas_h = 105 + grid_h + 105
        report_canvas = Image.new("RGB", (canvas_w, canvas_h), (15, 23, 42))
        draw = ImageDraw.Draw(report_canvas)
        draw.rectangle([0, 0, canvas_w, 82], fill=(3, 105, 161))
        draw.text((22, 16), f"{company_title} - {rep_header_title} ({report_code})", fill=(255, 255, 255))
        draw.text((22, 46), f"{ship_name} | {reporter_name} | {photos_count} anh | {now_str}", fill=(224, 242, 254))

        start_x = 22
        y_offset = 95
        for idx, ppath in enumerate(photo_paths):
            r_idx = idx // cols
            c_idx = idx % cols
            x0 = start_x + c_idx * (cell_w + 10)
            y0 = y_offset + r_idx * (cell_h + 10)
            try:
                im = Image.open(str(ppath)).convert("RGB")
                im = im.resize((cell_w, cell_h))
                report_canvas.paste(im, (x0, y0))
                draw.rectangle([x0, y0, x0 + cell_w, y0 + cell_h], outline=(56, 189, 248), width=2)
                draw.rectangle([x0 + 4, y0 + 4, x0 + 54, y0 + 21], fill=(15, 23, 42))
                draw.text((x0 + 9, y0 + 6), f"#{idx + 1}", fill=(255, 255, 255))
            except Exception:
                pass
        y_offset += grid_h + 6
    else:
        base_img = None
        if photo_paths:
            try:
                base_img = Image.open(str(photo_paths[0])).convert("RGB")
                base_img.thumbnail((740, 420))
            except Exception:
                base_img = None
        canvas_h = (110 + base_img.height + 105) if base_img else 300
        report_canvas = Image.new("RGB", (canvas_w, canvas_h), (15, 23, 42))
        draw = ImageDraw.Draw(report_canvas)
        draw.rectangle([0, 0, canvas_w, 82], fill=(3, 105, 161))
        draw.text((22, 16), f"{company_title} - {rep_header_title} ({report_code})", fill=(255, 255, 255))
        draw.text((22, 46), f"{ship_name} | {reporter_name} | {now_str}", fill=(224, 242, 254))
        y_offset = 95
        if base_img:
            x_pos = (canvas_w - base_img.width) // 2
            report_canvas.paste(base_img, (x_pos, y_offset))
            draw.rectangle([x_pos - 2, y_offset - 2, x_pos + base_img.width + 2, y_offset + base_img.height + 2], outline=(34, 197, 94), width=3)
            y_offset += base_img.height + 12

    draw.rectangle([22, y_offset, canvas_w - 22, canvas_h - 14], fill=(30, 41, 59), outline=(56, 189, 248), width=2)
    draw.text((36, y_offset + 10), f"{label_ship} {ship_name} | {label_items} {item_type_str}", fill=(56, 189, 248))
    draw.text((36, y_offset + 34), f"Hang muc: {rows_count} muc | Hinh anh: {photos_count} anh", fill=(226, 232, 240))
    draw.text((36, y_offset + 58), f"Ket luan: {conclusion[:88]}", fill=(74, 222, 128))

    report_canvas.save(str(out_img_path), "JPEG", quality=80, optimize=True)
    report_image_url = f"/reports/{out_img_name}"

    html_name = f"bao_cao_{report_code}.html"
    html_path = REPORTS_DIR / html_name
    report_html_url = f"/reports/{html_name}"

    pdf_name = f"bao_cao_{report_code}.pdf"
    pdf_path = REPORTS_DIR / pdf_name
    report_pdf_url = f"/reports/{pdf_name}"

    headers = form_data.get("headers") if "headers" in form_data else ["STT", "NỘI DUNG CÔNG VIỆC", "PHƯƠNG ÁN", "TIẾN ĐỘ DỰ KIẾN"]
    logo_src = form_data.get("logo_url") or "/allsea_logo.png"
    if not isinstance(logo_src, str) or not logo_src.startswith("/"):
        logo_src = "/allsea_logo.png"

    rows_html = ""
    for r in rows:
        if r.get("is_group"):
            rows_html += f"""
            <tr class="group-row">
              <td style="text-align:center;font-weight:bold;background:#f1f5f9;">{r.get('stt','')}</td>
              <td colspan="3" style="font-weight:bold;text-transform:uppercase;background:#f1f5f9;">{r.get('work','')}</td>
            </tr>"""
        else:
            work_Formatted = (r.get("work") or "").replace("\n", "<br/>")
            plan_Formatted = (r.get("plan") or "").replace("\n", "<br/>")
            prog_Formatted = (r.get("progress") or "").replace("\n", "<br/>")
            rows_html += f"""
            <tr>
              <td style="text-align:center;">{r.get('stt','')}</td>
              <td>{work_Formatted}</td>
              <td>{plan_Formatted}</td>
              <td>{prog_Formatted}</td>
            </tr>"""

    photos_html = ""
    pdf_photos_table_html = ""
    if photos:
        imgs_tags = "".join(
            f'<div class="photo-cell"><img src="{p.get("src") if isinstance(p, dict) else p}" alt="Ảnh"/><div class="photo-cap">{p.get("caption","") if isinstance(p, dict) else ""}</div></div>'
            for p in photos
        )
        sec_c_block = f'<div class="section-title" style="margin-top:16px;">{sec_c_title}</div>' if sec_c_title else ""
        photos_html = f"""
        {sec_c_block}
        <div class="photo-grid">{imgs_tags}</div>
        """

        pdf_cells = []
        for idx, p in enumerate(photos):
            raw_src = p.get("src") if isinstance(p, dict) else p
            pdf_thumb = p.get("pdf_src") if isinstance(p, dict) else ""
            cap = p.get("caption", "") if isinstance(p, dict) else ""
            arch_name = pdf_thumb if pdf_thumb and (UPLOADS_DIR / pdf_thumb).exists() else str(raw_src).split("/")[-1]
            cap_html = f'<div style="font-size:8pt;text-align:center;color:#334155;margin-top:2pt;">{cap}</div>' if cap else ""
            pdf_cells.append(
                f'<td style="width:25%;border:0.5pt solid #cbd5e1;padding:3pt;text-align:center;vertical-align:top;">'
                f'<img src="{arch_name}" width="118" height="90" />{cap_html}</td>'
            )
        pdf_rows_str = ""
        for i in range(0, len(pdf_cells), 4):
            chunk = pdf_cells[i:i + 4]
            while len(chunk) < 4:
                chunk.append('<td style="width:25%;border:none;padding:3pt;"></td>')
            pdf_rows_str += "<tr>" + "".join(chunk) + "</tr>"
        pdf_sec_c = f'<div style="font-weight:bold;margin-top:10pt;margin-bottom:5pt;font-size:10pt;">{sec_c_title}</div>' if sec_c_title else ""
        pdf_photos_table_html = f"""
        {pdf_sec_c}
        <table style="width:100%;border-collapse:collapse;">{pdf_rows_str}</table>
        """

    footer_html = f'<div style="margin-top:16px;white-space:pre-line;font-size:13px;">{footer_note}</div>' if footer_note else ""
    pdf_footer_html = f'<p style="margin-top:10pt;font-size:9.5pt;">{footer_note.replace(chr(10), "<br/>")}</p>' if footer_note else ""

    if HAS_PYMUPDF:
        try:
            logo_arch_name = logo_src.split("/")[-1] if "/" in logo_src else "allsea_logo.png"
            pdf_story_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: Arial, Tahoma, sans-serif; font-size: 9.5pt; color: #000; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 7pt; }}
  th, td {{ border: 0.75pt solid #000; padding: 4pt 5pt; vertical-align: top; }}
  th {{ background-color: #f1f5f9; font-weight: bold; text-align: center; }}
</style>
</head>
<body>
  <table>
    <tr>
      <td style="width:18%;text-align:center;vertical-align:middle;">
        <img src="{logo_arch_name}" width="52" height="52" />
      </td>
      <td style="width:82%;text-align:center;vertical-align:middle;">
        <div style="font-size:13pt;font-weight:bold;">{company_title}</div>
        <div style="font-size:9.5pt;font-weight:bold;color:#334155;">{company_subtitle}</div>
        <div style="font-size:11.5pt;font-weight:bold;margin-top:3pt;">{rep_header_title}</div>
      </td>
    </tr>
  </table>
  <table>
    <tr>
      <td style="width:52%;"><b>{label_ship}</b> {ship_name}</td>
      <td style="width:48%;"><b>{label_reporter}</b> {reporter_name}</td>
    </tr>
    <tr>
      <td colspan="2"><b>{label_items}</b> {item_type_str}</td>
    </tr>
  </table>
  {f'<p style="margin:4pt 0;">{salutation_str}</p>' if salutation_str else ''}
  {f'<p style="font-weight:bold;margin:5pt 0;">{report_date_str}</p>' if report_date_str else ''}
  {f'<p style="font-weight:bold;margin:4pt 0;">{sec_a_title} <span style="font-weight:normal;">{arising_str}</span></p>' if (sec_a_title or arising_str) else ''}
  {f'<p style="font-weight:bold;margin:4pt 0;">{sec_b_title}</p>' if sec_b_title else ''}
  <table>
    <thead>
      <tr>
        <th style="width:8%;">{headers[0] if len(headers)>0 else ''}</th>
        <th style="width:34%;">{headers[1] if len(headers)>1 else ''}</th>
        <th style="width:42%;">{headers[2] if len(headers)>2 else ''}</th>
        <th style="width:16%;">{headers[3] if len(headers)>3 else ''}</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
  {pdf_photos_table_html}
  {pdf_footer_html}
</body>
</html>"""
            arch = pymupdf.Archive([str(WEB_DIR), str(UPLOADS_DIR), str(REPORTS_DIR)])
            story = pymupdf.Story(html=pdf_story_html, archive=arch)
            writer = pymupdf.DocumentWriter(str(pdf_path))
            mediabox = pymupdf.paper_rect("a4")
            where = mediabox + (28, 28, -28, -28)
            more = 1
            while more:
                device = writer.begin_page(mediabox)
                more, _ = story.place(where)
                story.draw(device)
                writer.end_page()
            writer.close()
        except Exception as e:
            print("PDF generation warning:", e)

    html_content = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{rep_header_title} - {ship_name} ({report_code})</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
<style>
  body {{ font-family: 'Tahoma', 'Segoe UI', Arial, sans-serif; margin: 0; padding: 14px; background: #cbd5e1; color: #000; font-size: 13px; }}
  .a4-page {{ max-width: 820px; margin: 0 auto; background: #fff; padding: 26px 32px; box-shadow: 0 4px 25px rgba(0,0,0,0.15); outline: none; }}
  .a4-page[contenteditable="true"] {{ box-shadow: 0 0 0 3px #eab308, 0 4px 25px rgba(0,0,0,0.2); }}
  .top-actions {{ max-width: 820px; margin: 0 auto 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; background: #0f172a; padding: 10px 14px; border-radius: 10px; color: #fff; }}
  .btn-act {{ background: #0284c7; color: #fff; border: none; padding: 8px 14px; border-radius: 8px; cursor: pointer; font-weight: bold; font-size: 12.5px; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; }}
  .btn-pdf {{ background: #16a34a; }}
  .header-table {{ width: 100%; border-collapse: collapse; border: 2px solid #000; margin-bottom: 14px; }}
  .header-table td {{ border: 1.5px solid #000; padding: 10px 14px; vertical-align: middle; }}
  .logo-cell {{ width: 115px; text-align: center; }}
  .logo-cell img {{ width: 72px; height: 72px; object-fit: contain; }}
  .title-cell {{ text-align: center; }}
  .company-name {{ font-size: 16px; font-weight: bold; letter-spacing: 0.4px; }}
  .report-name {{ font-size: 15px; font-weight: bold; margin-top: 4px; }}
  .meta-table {{ width: 100%; border-collapse: collapse; border: 1.5px solid #000; margin-bottom: 14px; font-size: 13px; }}
  .meta-table td {{ border: 1px solid #000; padding: 6px 10px; }}
  .salutation {{ margin: 10px 0 14px; font-size: 13px; }}
  .date-line {{ font-weight: bold; margin: 12px 0; font-size: 13.5px; }}
  .section-title {{ font-weight: bold; margin: 6px 0 6px 18px; font-size: 13px; }}
  .work-table {{ width: 100%; border-collapse: collapse; border: 1.5px solid #000; margin-top: 8px; font-size: 12.5px; }}
  .work-table th, .work-table td {{ border: 1px solid #000; padding: 6px 8px; vertical-align: top; line-height: 1.4; }}
  .work-table th {{ background: #f8fafc; text-align: center; font-weight: bold; }}
  .group-row td {{ background: #f1f5f9; font-weight: bold; }}
  .photo-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-top: 10px; }}
  .photo-cell {{ border: 1px solid #cbd5e1; background: #f8fafc; overflow: hidden; page-break-inside: avoid; display: flex; flex-direction: column; }}
  .photo-cell img {{ width: 100%; height: 155px; object-fit: cover; display: block; }}
  .photo-cap {{ font-size: 11px; padding: 3px 5px; text-align: center; color: #334155; }}
  @media (max-width: 650px) {{ .photo-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
  @media print {{
    body {{ background: #fff; padding: 0; }}
    .top-actions {{ display: none !important; }}
    .a4-page {{ box-shadow: none !important; padding: 10px; max-width: 100%; }}
    .photo-grid {{ grid-template-columns: repeat(4, 1fr); }}
  }}
</style>
</head>
<body>
<div class="top-actions">
  <div style="display:flex;gap:8px;flex-wrap:wrap;">
    <a class="btn-act btn-pdf" href="{report_pdf_url}" download="{pdf_name}">📥 Tải File PDF (.pdf) Сиêu Nhẹ</a>
    <button class="btn-act" style="background:#0d9488;" onclick="exportClientPdf()">📄 Xuất PDF Sau Khi Sửa</button>
    <button class="btn-act" style="background:#d97706;" id="btn-edit-a4" onclick="toggleEditA4()">✏️ Sửa Chữ Trực Tiếp Trên Trang A4</button>
    <button class="btn-act" onclick="window.print()">🖨️ In Báo Cáo A4</button>
  </div>
  <span style="color:#cbd5e1;font-size:12px;">Mã: <b>{report_code}</b></span>
</div>
<div class="a4-page" id="a4-printable-area" contenteditable="false">
  <table class="header-table">
    <tr>
      <td class="logo-cell"><img src="{logo_src}" alt="Logo" crossorigin="anonymous"/></td>
      <td class="title-cell">
        <div class="company-name">{company_title}</div>
        <div style="font-size:12px;color:#334155;font-weight:bold;">{company_subtitle}</div>
        <div class="report-name">{rep_header_title}</div>
      </td>
    </tr>
  </table>

  <table class="meta-table">
    <tr>
      <td style="width:52%;"><b>{label_ship}</b> &nbsp;{ship_name}</td>
      <td style="width:48%;"><b>{label_reporter}</b> &nbsp;{reporter_name}</td>
    </tr>
    <tr>
      <td colspan="2"><b>{label_items}</b> &nbsp;{item_type_str}</td>
    </tr>
  </table>

  {f'<div class="salutation">{salutation_str}</div>' if salutation_str else ''}
  {f'<div class="date-line">{report_date_str}</div>' if report_date_str else ''}

  {f'<div class="section-title">{sec_a_title} <span style="font-weight:normal;">{arising_str}</span></div>' if (sec_a_title or arising_str) else ''}
  {f'<div class="section-title">{sec_b_title}</div>' if sec_b_title else ''}

  <table class="work-table">
    <thead>
      <tr>
        <th style="width:46px;">{headers[0] if len(headers)>0 else ''}</th>
        <th style="width:34%;">{headers[1] if len(headers)>1 else ''}</th>
        <th style="width:42%;">{headers[2] if len(headers)>2 else ''}</th>
        <th style="width:16%;">{headers[3] if len(headers)>3 else ''}</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>

  {photos_html}
  {footer_html}
</div>
<script>
function toggleEditA4() {{
  const el = document.getElementById('a4-printable-area');
  const btn = document.getElementById('btn-edit-a4');
  const isEd = el.getAttribute('contenteditable') === 'true';
  el.setAttribute('contenteditable', isEd ? 'false' : 'true');
  btn.innerHTML = isEd ? '✏️ Sửa Chữ Trực Tiếp Trên Trang A4' : '✅ Đang Bật Sửa Chữ (Bấm vào bất kỳ chữ nào để sửa)';
  btn.style.background = isEd ? '#d97706' : '#16a34a';
  if (!isEd) el.focus();
}}
function exportClientPdf() {{
  const el = document.getElementById('a4-printable-area');
  el.setAttribute('contenteditable', 'false');
  if (window.html2pdf) {{
    html2pdf().set({{
      margin: [8, 8, 8, 8],
      filename: '{pdf_name}',
      image: {{ type: 'jpeg', quality: 0.88 }},
      html2canvas: {{ scale: 2, useCORS: true }},
      jsPDF: {{ unit: 'mm', format: 'a4', orientation: 'portrait' }}
    }}).from(el).save();
  }} else {{
    window.print();
  }}
}}
</script>
</body>
</html>"""
    html_path.write_text(html_content, encoding="utf-8")

    report_data = {
        "report_code": report_code,
        "processed_by": "Phần mềm máy tính PySide6 (Allsea Report Engine)",
        "processed_at": now_str,
        "sender": f"{form_data.get('reporter') or full_name} ({username})",
        "ship_name": ship_name,
        "task_type": form_data.get("item_type") or task_type,
        "status_badge": "ĐÃ TỔNG HỢP BÁO CÁO CHUẨN ALLSEA",
        "conclusion": conclusion,
        "report_pdf_url": report_pdf_url,
        "report_html_url": report_html_url,
        "report_image_url": report_image_url,
        "form_data": form_data,
        "metrics": [
            {"name": "Tên tàu (Ship's Name)", "value": ship_name, "status": "Đã xác nhận"},
            {"name": "Loại báo cáo (Items)", "value": form_data.get("item_type") or task_type, "status": "Hợp lệ"},
            {"name": "Tổng số hạng mục & Hình ảnh", "value": f"{rows_count} mục / {photos_count} ảnh", "status": "Hoàn tất"},
        ]
    }

    return report_data["conclusion"], json.dumps(report_data, ensure_ascii=False), report_image_url, report_html_url, report_pdf_url


@app.get("/api/network-info")
def get_network_info():
    lan_ip = get_lan_ip()
    port = 8000
    lan_url = f"http://{lan_ip}:{port}"
    qr_lan = make_qr_base64(lan_url)
    qr_public = make_qr_base64(manager.public_tunnel_url) if manager.public_tunnel_url else ""

    pyside_online = (time.time() - manager.pyside6_last_seen) < 30
    return {
        "lan_ip": lan_ip,
        "port": port,
        "lan_url": lan_url,
        "local_url": f"http://127.0.0.1:{port}",
        "public_url": manager.public_tunnel_url,
        "qr_code": qr_lan,
        "qr_public": qr_public,
        "pyside6_online": pyside_online,
        "pyside6_auto_mode": manager.pyside6_auto_mode,
        "connected_clients": len(manager.active_connections),
    }


@app.post("/api/pyside6/tunnel")
async def update_tunnel_url(req: TunnelUpdate):
    manager.public_tunnel_url = req.public_url.strip()
    await manager.broadcast("tunnel_updated", {"public_url": manager.public_tunnel_url})
    return {"status": "ok", "public_url": manager.public_tunnel_url}


@app.post("/api/pyside6/heartbeat")
async def pyside6_heartbeat(auto_mode: bool = True):
    manager.pyside6_last_seen = time.time()
    manager.pyside6_auto_mode = auto_mode
    return {"status": "ok", "auto_mode": auto_mode}


@app.post("/api/login")
def login(req: LoginRequest):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ? AND password = ?", (req.username.strip(), req.password.strip()))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="Sai tên đăng nhập hoặc mật khẩu!")
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="Tài khoản này đang bị tạm khóa bởi Admin!")
    return dict(row)


@app.get("/api/users")
def list_users():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users ORDER BY role ASC, username ASC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


@app.post("/api/users")
async def create_or_update_user(user: UserCreateUpdate):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("SELECT username FROM users WHERE username = ?", (user.username.strip(),))
    exists = cur.fetchone()
    if exists:
        cur.execute("""
            UPDATE users
            SET password = COALESCE(NULLIF(?, ''), password),
                full_name = ?, role = ?, can_view = ?, can_submit = ?, auto_process = ?, is_active = ?
            WHERE username = ?
        """, (user.password, user.full_name, user.role, user.can_view, user.can_submit, user.auto_process, user.is_active, user.username.strip()))
    else:
        cur.execute("""
            INSERT INTO users (username, password, full_name, role, can_view, can_submit, auto_process, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user.username.strip(), user.password or "123456", user.full_name, user.role, user.can_view, user.can_submit, user.auto_process, user.is_active, now))
    conn.commit()
    conn.close()
    await manager.broadcast("users_updated", {"username": user.username})
    return {"status": "ok", "username": user.username}


@app.delete("/api/users/{username}")
async def delete_user(username: str):
    if username == "admin":
        raise HTTPException(status_code=400, detail="Không thể xóa tài khoản admin gốc!")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    conn.close()
    await manager.broadcast("users_updated", {"deleted": username})
    return {"status": "deleted"}


@app.get("/api/shared-data")
def get_shared_data(username: str = "admin", include_hidden: bool = False):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    u = cur.fetchone()
    if not u and not include_hidden:
        conn.close()
        raise HTTPException(status_code=403, detail="Tài khoản không hợp lệ")

    if include_hidden:
        cur.execute("SELECT * FROM live_metrics ORDER BY metric_key ASC")
        metrics = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT * FROM shared_items ORDER BY id DESC")
        items = [dict(r) for r in cur.fetchall()]
    else:
        if u["can_view"] == 0 and u["role"] != "admin":
            conn.close()
            return {"metrics": [], "items": [], "permission_denied": True}

        cur.execute("SELECT * FROM live_metrics WHERE is_shared = 1 ORDER BY metric_key ASC")
        metrics = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM shared_items WHERE is_shared = 1 ORDER BY id DESC")
        all_shared = [dict(r) for r in cur.fetchall()]
        items = []
        for it in all_shared:
            allowed = [x.strip() for x in (it["allowed_users"] or "ALL").split(",") if x.strip()]
            if "ALL" in allowed or username in allowed or u["role"] == "admin":
                items.append(it)

    conn.close()
    return {"metrics": metrics, "items": items, "permission_denied": False}


@app.post("/api/live-metrics")
async def update_live_metric(m: MetricUpdate):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now().strftime("%H:%M:%S")
    cur.execute("""
        INSERT INTO live_metrics (metric_key, label, value, unit, is_shared, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(metric_key) DO UPDATE SET
            label = excluded.label,
            value = excluded.value,
            unit = excluded.unit,
            is_shared = excluded.is_shared,
            updated_at = excluded.updated_at
    """, (m.metric_key, m.label, m.value, m.unit, m.is_shared, now))
    conn.commit()
    conn.close()
    await manager.broadcast("shared_data_updated", {"metric_key": m.metric_key})
    return {"status": "ok"}


@app.post("/api/shared-items")
async def create_shared_item(
    title: str = Form(...),
    category: str = Form("Báo cáo từ PySide6"),
    description: str = Form(""),
    is_shared: int = Form(1),
    allowed_users: str = Form("ALL"),
    file: Optional[UploadFile] = File(None),
):
    file_url = ""
    file_type = "note"
    if file and file.filename:
        ext = Path(file.filename).suffix or ".png"
        safe_name = f"shared_{int(time.time())}{ext}"
        dest = SHARED_FILES_DIR / safe_name
        content = await file.read()
        dest.write_bytes(content)
        file_url = f"/shared_files/{safe_name}"
        file_type = "image" if ext.lower() in [".png", ".jpg", ".jpeg", ".webp", ".gif"] else "file"
    else:
        file_url = create_sample_shared_image(
            f"shared_card_{int(time.time())}.png",
            title[:42].upper(),
            description[:65] or "Du lieu chia se truc tiep tu phan mem PySide6",
        )
        file_type = "image"

    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO shared_items (title, category, description, file_url, file_type, is_shared, allowed_users, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (title, category, description, file_url, file_type, is_shared, allowed_users, now))
    item_id = cur.lastrowid
    conn.commit()
    conn.close()
    await manager.broadcast("shared_data_updated", {"item_id": item_id})
    return {"status": "ok", "id": item_id, "file_url": file_url}


@app.put("/api/shared-items/{item_id}")
async def toggle_shared_item(item_id: int, req: SharedItemToggle):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM shared_items WHERE id = ?", (item_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Không tìm thấy mục chia sẻ")

    new_shared = req.is_shared if req.is_shared is not None else row["is_shared"]
    new_allowed = req.allowed_users if req.allowed_users is not None else row["allowed_users"]
    new_title = req.title if req.title is not None else row["title"]
    new_desc = req.description if req.description is not None else row["description"]
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    cur.execute("""
        UPDATE shared_items
        SET is_shared = ?, allowed_users = ?, title = ?, description = ?, updated_at = ?
        WHERE id = ?
    """, (new_shared, new_allowed, new_title, new_desc, now, item_id))
    conn.commit()
    conn.close()
    await manager.broadcast("shared_data_updated", {"item_id": item_id, "is_shared": new_shared})
    return {"status": "ok", "id": item_id, "is_shared": new_shared}


@app.delete("/api/shared-items/{item_id}")
async def delete_shared_item(item_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM shared_items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    await manager.broadcast("shared_data_updated", {"deleted_id": item_id})
    return {"status": "deleted"}


def _auto_save_contacts_from_string(cur, recipients_str: str):
    if not recipients_str:
        return
    now_c = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for raw in recipients_str.replace(";", ",").split(","):
        addr = raw.strip()
        if "@" in addr and "." in addr:
            try:
                cur.execute(
                    "INSERT OR IGNORE INTO email_contacts (email, label, created_at) VALUES (?, ?, ?)",
                    (addr, addr.split("@")[0], now_c)
                )
            except Exception:
                pass


def deliver_report_email(
    sub_id: int,
    recipients_str: Optional[str] = None,
    subject_str: Optional[str] = None,
    body_str: Optional[str] = None,
) -> dict:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM submissions WHERE id = ?", (sub_id,))
    sub = cur.fetchone()
    if not sub:
        conn.close()
        return {"ok": False, "detail": f"Không tìm thấy báo cáo #{sub_id}"}

    cur.execute("SELECT * FROM email_settings WHERE id = 1")
    cfg = dict(cur.fetchone())

    form_data = {}
    if sub["form_payload_json"]:
        try:
            form_data = json.loads(sub["form_payload_json"])
        except Exception:
            form_data = {}

    report_code = f"BC-PYSIDE6-{sub_id:04d}"
    ctx_vars = {
        "report_code": report_code,
        "report_header_title": form_data.get("report_header_title") or sub["title"],
        "ship_name": form_data.get("ship_name") or "LS JUPITER",
        "report_date": form_data.get("report_date") or datetime.now().strftime("%d/%m/%Y"),
        "reporter": form_data.get("reporter") or sub["full_name"],
        "item_type": form_data.get("item_type") or sub["task_type"],
    }

    to_raw = (recipients_str or sub["email_recipients"] or cfg.get("default_recipients") or "").strip()
    to_list = [x.strip() for x in to_raw.replace(";", ",").split(",") if "@" in x.strip()]
    if not to_list:
        conn.close()
        return {"ok": False, "detail": "Chưa nhập địa chỉ Email người nhận!"}

    _auto_save_contacts_from_string(cur, ", ".join(to_list))

    subj_tpl = (subject_str or sub["email_subject"] or cfg.get("default_subject") or "[ALLSEA REPORT] {report_header_title} - {ship_name}").strip()
    body_tpl = (body_str or cfg.get("default_body") or "Kính gửi Ban Lãnh Đạo,\n\nĐính kèm báo cáo PDF {report_header_title} - {ship_name}.").strip()
    try:
        final_subject = subj_tpl.format(**ctx_vars)
    except Exception:
        final_subject = subj_tpl
    try:
        final_body = body_tpl.format(**ctx_vars)
    except Exception:
        final_body = body_tpl

    # Đảm bảo đã có file PDF để đính kèm
    pdf_url = sub["report_pdf_url"] or f"/reports/bao_cao_{report_code}.pdf"
    pdf_path = REPORTS_DIR / pdf_url.replace("/reports/", "")
    if not pdf_path.exists():
        input_path = UPLOADS_DIR / sub["input_image_url"].replace("/uploads/", "") if sub["input_image_url"] else None
        generate_report_files(
            sub_id=sub_id,
            title=sub["title"],
            username=sub["username"],
            full_name=sub["full_name"],
            note_text=sub["note_text"] or "",
            task_type=sub["task_type"] or "DAILY REPORT",
            input_image_path=input_path,
            form_payload_json=sub["form_payload_json"],
        )

    msg = EmailMessage()
    sender_addr = (cfg.get("sender_email") or "report@allseamanagement.vn").strip()
    sender_name = (cfg.get("sender_name") or "ALLSEA MANAGEMENT REPORT").strip()
    msg["From"] = f"{sender_name} <{sender_addr}>"
    msg["To"] = ", ".join(to_list)
    msg["Subject"] = final_subject
    msg.set_content(final_body)

    if pdf_path.exists():
        pdf_bytes = pdf_path.read_bytes()
        msg.add_attachment(
            pdf_bytes,
            maintype="application",
            subtype="pdf",
            filename=pdf_path.name,
        )

    # Lưu bản sao .eml chuẩn ra thư mục EMAIL_OUTBOX_DIR (ngoài thư mục code)
    eml_name = f"mail_sub_{sub_id}_{int(time.time())}.eml"
    eml_path = EMAIL_OUTBOX_DIR / eml_name
    eml_path.write_bytes(msg.as_bytes())

    sent_now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    smtp_host = (cfg.get("smtp_host") or "smtp.gmail.com").strip()
    smtp_port = int(cfg.get("smtp_port") or 587)
    smtp_user = (cfg.get("sender_email") or "").strip()
    smtp_pass = (cfg.get("sender_password") or "").strip()

    status_code = "saved_outbox"
    status_msg = f"Đã đóng gói Email kèm PDF ({pdf_path.name}) gửi tới {', '.join(to_list)} (Đã lưu file {eml_name}; nhập mật khẩu ứng dụng Gmail trong Cài đặt SMTP nếu muốn gửi qua máy chủ Gmail)."

    if smtp_user and smtp_pass:
        try:
            if smtp_port == 465:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=12) as server:
                    server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=12) as server:
                    server.ehlo()
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
            status_code = "sent"
            status_msg = f"Đã gửi Email đính kèm PDF ({pdf_path.name}) thành công tới: {', '.join(to_list)} lúc {sent_now}!"
        except Exception as e:
            status_code = "smtp_error_saved_eml"
            status_msg = f"Lỗi xác thực SMTP ({e}) — Đã lưu bản Email đính kèm PDF tại {eml_name}"

    cur.execute("""
        UPDATE submissions
        SET email_status = ?,
            email_recipients = ?,
            email_subject = ?,
            email_sent_at = ?
        WHERE id = ?
    """, (status_code, ", ".join(to_list), final_subject, sent_now, sub_id))
    conn.commit()
    conn.close()

    return {
        "ok": True,
        "submission_id": sub_id,
        "email_status": status_code,
        "recipients": ", ".join(to_list),
        "subject": final_subject,
        "sent_at": sent_now,
        "eml_url": f"/emails_outbox/{eml_name}",
        "pdf_url": pdf_url,
        "message": status_msg,
    }


def _email_scheduler_worker():
    """Tiến trình ngầm kiểm tra mỗi 15 giây để tự động gửi Email báo cáo PDF đúng giờ hẹn HH:MM."""
    while True:
        try:
            now_dt = datetime.now()
            now_hhmm = now_dt.strftime("%H:%M")
            today_str = now_dt.strftime("%Y-%m-%d")

            conn = get_db()
            cur = conn.cursor()

            # 1. Kiểm tra các báo cáo được hẹn giờ riêng (email_status = 'scheduled')
            cur.execute("""
                SELECT id, email_recipients, email_subject, email_schedule_hhmm
                FROM submissions
                WHERE email_status = 'scheduled' AND email_schedule_hhmm != ''
            """)
            scheduled_rows = [dict(r) for r in cur.fetchall()]

            # 2. Kiểm tra cài đặt tự động gửi hàng ngày theo giờ cố định HH:MM
            cur.execute("SELECT * FROM email_settings WHERE id = 1")
            cfg_row = cur.fetchone()
            cfg = dict(cfg_row) if cfg_row else {}
            conn.close()

            for srow in scheduled_rows:
                if srow["email_schedule_hhmm"] <= now_hhmm:
                    deliver_report_email(
                        sub_id=srow["id"],
                        recipients_str=srow["email_recipients"],
                        subject_str=srow["email_subject"],
                    )

            if cfg.get("auto_send_enabled") == 1 and cfg.get("schedule_time_hhmm") == now_hhmm:
                if cfg.get("last_auto_sent_date") != today_str:
                    conn2 = get_db()
                    cur2 = conn2.cursor()
                    cur2.execute("UPDATE email_settings SET last_auto_sent_date = ? WHERE id = 1", (today_str,))
                    cur2.execute("SELECT id FROM submissions WHERE status = 'completed' AND email_status = 'unsent'")
                    unsent_ids = [r["id"] for r in cur2.fetchall()]
                    conn2.commit()
                    conn2.close()
                    for uid in unsent_ids:
                        deliver_report_email(sub_id=uid)
        except Exception:
            pass
        time.sleep(15)


threading.Thread(target=_email_scheduler_worker, daemon=True).start()


async def _handle_new_submission(
    username: str,
    title: str,
    note_text: str,
    task_type: str,
    canvas_base64: Optional[str],
    form_payload_json: Optional[str],
    uploaded_bytes: Optional[bytes] = None,
    uploaded_ext: str = ".png",
):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cur.fetchone()
    if not user or not user["is_active"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Tài khoản không hợp lệ hoặc đã bị khóa!")
    if user["can_submit"] == 0 and user["role"] != "admin":
        conn.close()
        raise HTTPException(status_code=403, detail="Tài khoản của bạn CHỈ CÓ QUYỀN XEM, không có quyền gửi tài liệu lên PySide6 xử lý!")

    saved_input_path: Optional[Path] = None
    input_image_url = ""
    ts = int(time.time() * 1000)
    prefix = f"sub_{username}_{ts}"

    cleaned_payload_json, first_photo_path, first_photo_url = extract_and_save_form_photos(form_payload_json, prefix)
    if first_photo_path is not None:
        saved_input_path = first_photo_path
        input_image_url = first_photo_url

    if canvas_base64 and "," in canvas_base64 and not saved_input_path:
        try:
            b64_data = canvas_base64.split(",", 1)[1]
            raw_bytes = base64.b64decode(b64_data)
            fname = f"{prefix}_main.jpg"
            saved_input_path = UPLOADS_DIR / fname
            saved_input_path.write_bytes(raw_bytes)
            input_image_url = f"/uploads/{fname}"
        except Exception:
            pass
    elif uploaded_bytes and not saved_input_path:
        fname = f"{prefix}_main{uploaded_ext}"
        saved_input_path = UPLOADS_DIR / fname
        saved_input_path.write_bytes(uploaded_bytes)
        input_image_url = f"/uploads/{fname}"

    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    auto_proc = int(user["auto_process"] == 1 and manager.pyside6_auto_mode)

    # Kiểm tra tùy chọn Email gửi kèm trong form_payload_json
    parsed_form = {}
    if cleaned_payload_json:
        try:
            parsed_form = json.loads(cleaned_payload_json)
        except Exception:
            parsed_form = {}
    email_opts = parsed_form.get("email_options") or {}
    email_action = email_opts.get("action") or "none"  # 'none' | 'send_now' | 'schedule'
    email_to = (email_opts.get("recipients") or "").strip()
    email_subj = (email_opts.get("subject") or "").strip()
    email_body = (email_opts.get("body") or "").strip()
    email_hhmm = (email_opts.get("schedule_hhmm") or "").strip()

    if email_to:
        _auto_save_contacts_from_string(cur, email_to)

    init_email_status = "scheduled" if (email_action == "schedule" and email_hhmm) else "unsent"

    cur.execute("""
        INSERT INTO submissions (
            username, full_name, title, note_text, task_type, input_image_url,
            status, auto_process, form_payload_json,
            email_status, email_recipients, email_subject, email_schedule_hhmm, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        username, user["full_name"], title, note_text, task_type, input_image_url,
        "pending", auto_proc, cleaned_payload_json,
        init_email_status, email_to, email_subj, email_hhmm, now
    ))
    sub_id = cur.lastrowid
    conn.commit()

    if auto_proc:
        summary, data_json, rep_img_url, rep_html_url, rep_pdf_url = generate_report_files(
            sub_id=sub_id,
            title=title,
            username=username,
            full_name=user["full_name"],
            note_text=note_text or "",
            task_type=task_type or "DAILY REPORT",
            input_image_path=saved_input_path,
            custom_conclusion=None,
            form_payload_json=cleaned_payload_json,
        )
        proc_now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        cur.execute("""
            UPDATE submissions
            SET status = 'completed',
                report_summary = ?,
                report_data_json = ?,
                report_image_url = ?,
                report_html_url = ?,
                report_pdf_url = ?,
                processed_at = ?
            WHERE id = ?
        """, (summary, data_json, rep_img_url, rep_html_url, rep_pdf_url, proc_now, sub_id))
        conn.commit()
        conn.close()

        email_result = None
        if email_action == "send_now" and email_to:
            email_result = deliver_report_email(sub_id, email_to, email_subj, email_body)
        elif email_action == "schedule" and email_hhmm and email_to:
            email_result = {
                "ok": True,
                "email_status": "scheduled",
                "schedule_hhmm": email_hhmm,
                "recipients": email_to,
                "message": f"Đã hẹn giờ tự động gửi Email báo cáo PDF lúc {email_hhmm} tới {email_to}!"
            }

        await manager.broadcast("submission_completed", {
            "id": sub_id,
            "username": username,
            "full_name": user["full_name"],
            "title": title,
            "status": "completed",
            "report_summary": summary,
            "report_image_url": rep_img_url,
            "report_html_url": rep_html_url,
            "report_pdf_url": rep_pdf_url,
            "email_result": email_result,
            "processed_by": "PySide6 Fast Auto-Engine",
        })
        return {
            "status": "completed",
            "submission_id": sub_id,
            "auto_process": auto_proc,
            "report_summary": summary,
            "report_image_url": rep_img_url,
            "report_html_url": rep_html_url,
            "report_pdf_url": rep_pdf_url,
            "email_result": email_result,
        }

    conn.close()
    await manager.broadcast("submission_created", {
        "id": sub_id,
        "username": username,
        "full_name": user["full_name"],
        "title": title,
        "status": "pending",
        "auto_process": auto_proc
    })
    return {"status": "ok", "submission_id": sub_id, "auto_process": auto_proc}


@app.post("/api/submissions-json")
async def create_submission_json(request: Request):
    """Endpoint JSON tốc độ cao không giới hạn dung lượng 1MB của Multipart Form,
    cho phép gửi 12 - 50 ảnh cùng lúc mượt mà từ Web và Điện thoại."""
    body = await request.json()
    username = body.get("username") or "nhanvien1"
    title = body.get("title") or "Báo cáo hiện trường Allsea"
    note_text = body.get("note_text") or ""
    task_type = body.get("task_type") or "DAILY REPORT"
    canvas_base64 = body.get("canvas_base64")
    payload_obj = body.get("payload") or body.get("form_payload_json")
    if isinstance(payload_obj, dict):
        form_payload_json = json.dumps(payload_obj, ensure_ascii=False)
    else:
        form_payload_json = payload_obj

    return await _handle_new_submission(
        username=username,
        title=title,
        note_text=note_text,
        task_type=task_type,
        canvas_base64=canvas_base64,
        form_payload_json=form_payload_json,
    )


@app.post("/api/submissions")
async def create_submission(
    username: str = Form(...),
    title: str = Form(...),
    note_text: str = Form(""),
    task_type: str = Form("DAILY REPORT"),
    canvas_base64: Optional[str] = Form(None),
    form_payload_json: Optional[str] = Form(None),
    image_file: Optional[UploadFile] = File(None),
):
    uploaded_bytes = None
    uploaded_ext = ".png"
    if image_file and image_file.filename:
        uploaded_ext = Path(image_file.filename).suffix or ".png"
        uploaded_bytes = await image_file.read()

    return await _handle_new_submission(
        username=username,
        title=title,
        note_text=note_text,
        task_type=task_type,
        canvas_base64=canvas_base64,
        form_payload_json=form_payload_json,
        uploaded_bytes=uploaded_bytes,
        uploaded_ext=uploaded_ext,
    )


@app.get("/api/submissions")
def list_submissions(username: str = "admin", role: str = "admin", status: Optional[str] = None, light: bool = False):
    conn = get_db()
    cur = conn.cursor()
    cols = (
        "id, username, full_name, title, note_text, task_type, input_image_url, status, auto_process, "
        "report_summary, report_image_url, report_html_url, report_pdf_url, "
        "email_status, email_recipients, email_subject, email_schedule_hhmm, email_sent_at, created_at, processed_at"
        if light else "*"
    )
    if role == "admin" or username == "__pyside6__":
        if status:
            cur.execute(f"SELECT {cols} FROM submissions WHERE status = ? ORDER BY id DESC", (status,))
        else:
            cur.execute(f"SELECT {cols} FROM submissions ORDER BY id DESC")
    else:
        cur.execute(f"SELECT {cols} FROM submissions WHERE username = ? ORDER BY id DESC", (username,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


@app.delete("/api/submissions/{sub_id}")
async def delete_submission(sub_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM submissions WHERE id = ?", (sub_id,))
    conn.commit()
    conn.close()
    await manager.broadcast("submission_deleted", {"id": sub_id})
    return {"status": "deleted", "id": sub_id}


@app.get("/api/email/settings")
def get_email_settings_and_contacts():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM email_settings WHERE id = 1")
    settings_row = cur.fetchone()
    settings = dict(settings_row) if settings_row else {}
    cur.execute("SELECT * FROM email_contacts ORDER BY id ASC")
    contacts = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {
        "settings": settings,
        "contacts": contacts,
        "storage_dir": str(DATA_DIR),
    }


@app.post("/api/email/settings")
async def update_email_settings(request: Request):
    body = await request.json()
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
        UPDATE email_settings
        SET smtp_host = COALESCE(?, smtp_host),
            smtp_port = COALESCE(?, smtp_port),
            sender_email = COALESCE(?, sender_email),
            sender_password = COALESCE(?, sender_password),
            sender_name = COALESCE(?, sender_name),
            default_recipients = COALESCE(?, default_recipients),
            default_subject = COALESCE(?, default_subject),
            default_body = COALESCE(?, default_body),
            auto_send_enabled = COALESCE(?, auto_send_enabled),
            schedule_time_hhmm = COALESCE(?, schedule_time_hhmm),
            updated_at = ?
        WHERE id = 1
    """, (
        body.get("smtp_host"),
        body.get("smtp_port"),
        body.get("sender_email"),
        body.get("sender_password"),
        body.get("sender_name"),
        body.get("default_recipients"),
        body.get("default_subject"),
        body.get("default_body"),
        body.get("auto_send_enabled"),
        body.get("schedule_time_hhmm"),
        now,
    ))
    if body.get("default_recipients"):
        _auto_save_contacts_from_string(cur, body["default_recipients"])
    conn.commit()
    conn.close()
    await manager.broadcast("email_settings_updated", {"schedule_time_hhmm": body.get("schedule_time_hhmm")})
    return {"status": "ok"}


@app.post("/api/email/contacts")
async def add_email_contact(request: Request):
    body = await request.json()
    email_addr = (body.get("email") or "").strip()
    label = (body.get("label") or email_addr.split("@")[0]).strip()
    if "@" not in email_addr:
        raise HTTPException(status_code=400, detail="Địa chỉ Email không hợp lệ!")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO email_contacts (email, label, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET label = excluded.label
    """, (email_addr, label, now))
    conn.commit()
    cur.execute("SELECT * FROM email_contacts ORDER BY id ASC")
    contacts = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"status": "ok", "contacts": contacts}


@app.delete("/api/email/contacts/{contact_id}")
async def delete_email_contact(contact_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM email_contacts WHERE id = ?", (contact_id,))
    conn.commit()
    cur.execute("SELECT * FROM email_contacts ORDER BY id ASC")
    contacts = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"status": "deleted", "contacts": contacts}


@app.post("/api/email/send")
async def send_or_schedule_report_email(request: Request):
    body = await request.json()
    sub_id = int(body.get("submission_id") or 0)
    mode = body.get("mode") or "now"  # 'now' | 'schedule'
    recipients = (body.get("recipients") or "").strip()
    subject = (body.get("subject") or "").strip()
    email_body = (body.get("body") or "").strip()
    schedule_hhmm = (body.get("schedule_hhmm") or "").strip()

    if not sub_id:
        raise HTTPException(status_code=400, detail="Thiếu mã báo cáo (submission_id)!")

    if mode == "schedule" and schedule_hhmm:
        conn = get_db()
        cur = conn.cursor()
        _auto_save_contacts_from_string(cur, recipients)
        cur.execute("""
            UPDATE submissions
            SET email_status = 'scheduled',
                email_recipients = ?,
                email_subject = ?,
                email_schedule_hhmm = ?
            WHERE id = ?
        """, (recipients, subject, schedule_hhmm, sub_id))
        conn.commit()
        conn.close()
        msg = f"⏰ Đã hẹn giờ tự động gửi Email Báo cáo #{sub_id} (kèm PDF) lúc {schedule_hhmm} tới: {recipients}!"
        await manager.broadcast("email_status_updated", {"id": sub_id, "email_status": "scheduled", "schedule_hhmm": schedule_hhmm})
        return {"ok": True, "email_status": "scheduled", "schedule_hhmm": schedule_hhmm, "message": msg}

    res = deliver_report_email(sub_id=sub_id, recipients_str=recipients, subject_str=subject, body_str=email_body)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("detail", "Lỗi gửi email"))
    await manager.broadcast("email_status_updated", {"id": sub_id, "email_status": res["email_status"], "sent_at": res.get("sent_at")})
    return res


@app.post("/api/submissions/{sub_id}/process")
async def process_submission_by_pyside6(
    sub_id: int,
    custom_conclusion: Optional[str] = Form(None),
    processed_by: str = Form("PySide6 Desktop Auto-Engine"),
):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM submissions WHERE id = ?", (sub_id,))
    sub = cur.fetchone()
    if not sub:
        conn.close()
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu xử lý!")

    if sub["status"] == "completed" and not custom_conclusion and sub["report_html_url"]:
        rep_pdf = sub["report_pdf_url"] if "report_pdf_url" in sub.keys() else ""
        conn.close()
        return {
            "status": "completed",
            "id": sub_id,
            "report_summary": sub["report_summary"],
            "report_image_url": sub["report_image_url"],
            "report_html_url": sub["report_html_url"],
            "report_pdf_url": rep_pdf,
        }

    cur.execute("UPDATE submissions SET status = 'processing' WHERE id = ?", (sub_id,))
    conn.commit()
    await manager.broadcast("submission_status", {"id": sub_id, "status": "processing", "title": sub["title"]})

    input_path = None
    if sub["input_image_url"]:
        rel_name = sub["input_image_url"].replace("/uploads/", "")
        input_path = UPLOADS_DIR / rel_name

    summary, data_json, rep_img_url, rep_html_url, rep_pdf_url = generate_report_files(
        sub_id=sub_id,
        title=sub["title"],
        username=sub["username"],
        full_name=sub["full_name"],
        note_text=sub["note_text"] or "",
        task_type=sub["task_type"] or "DAILY REPORT",
        input_image_path=input_path,
        custom_conclusion=custom_conclusion,
        form_payload_json=sub["form_payload_json"] if "form_payload_json" in sub.keys() else None,
    )

    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    cur.execute("""
        UPDATE submissions
        SET status = 'completed',
            report_summary = ?,
            report_data_json = ?,
            report_image_url = ?,
            report_html_url = ?,
            report_pdf_url = ?,
            processed_at = ?
        WHERE id = ?
    """, (summary, data_json, rep_img_url, rep_html_url, rep_pdf_url, now, sub_id))
    conn.commit()
    conn.close()

    await manager.broadcast("submission_completed", {
        "id": sub_id,
        "username": sub["username"],
        "title": sub["title"],
        "status": "completed",
        "report_summary": summary,
        "report_image_url": rep_img_url,
        "report_html_url": rep_html_url,
        "report_pdf_url": rep_pdf_url,
        "processed_by": processed_by,
    })
    return {
        "status": "completed",
        "id": sub_id,
        "report_summary": summary,
        "report_image_url": rep_img_url,
        "report_html_url": rep_html_url,
        "report_pdf_url": rep_pdf_url,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            _ = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/manifest.json")
def get_manifest():
    return FileResponse(str(WEB_DIR / "manifest.json"), media_type="application/manifest+json")


@app.get("/sw.js")
def get_sw():
    return FileResponse(str(WEB_DIR / "sw.js"), media_type="application/javascript")


@app.get("/")
def serve_web_app():
    index_file = WEB_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file), headers={"Cache-Control": "no-cache"})
    return HTMLResponse("<h3>Đang khởi tạo giao diện Web/APK...</h3>")


@app.get("/{asset_name}")
def serve_web_assets(asset_name: str):
    safe_path = (WEB_DIR / asset_name).resolve()
    if safe_path.parent == WEB_DIR.resolve() and safe_path.exists() and safe_path.is_file():
        ext = safe_path.suffix.lower()
        headers = {"Cache-Control": "public, max-age=86400"} if ext in [".jpg", ".jpeg", ".png", ".webp", ".ico"] else {}
        return FileResponse(str(safe_path), headers=headers)
    raise HTTPException(status_code=404, detail="Không tìm thấy file")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
