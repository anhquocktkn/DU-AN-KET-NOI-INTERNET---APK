import os
import io
import json
import time
import base64
import socket
import sqlite3
from datetime import datetime
from typing import List, Optional
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

try:
    import pymupdf
    HAS_PYMUPDF = True
except Exception:
    HAS_PYMUPDF = False

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
REPORTS_DIR = DATA_DIR / "reports"
SHARED_FILES_DIR = DATA_DIR / "shared_files"
WEB_DIR = BASE_DIR / "web"

for d in [DATA_DIR, UPLOADS_DIR, REPORTS_DIR, SHARED_FILES_DIR, WEB_DIR]:
    d.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "app_system.db"

app = FastAPI(title="PySide6 <-> Web/APK Sync Server")

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
    try:
        cur.execute("ALTER TABLE submissions ADD COLUMN form_payload_json TEXT")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE submissions ADD COLUMN report_pdf_url TEXT")
    except Exception:
        pass

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
    """Giải nén toàn bộ ảnh Base64 trong form_payload_json ra file vật lý trong /uploads/
    giúp giảm kích thước JSON lưu DB từ vài MB xuống < 2KB, tăng tốc truyền/nhận gấp 50 lần."""
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
                header, b64_part = src.split(",", 1)
                ext = ".png" if "png" in header.lower() else ".jpg"
                raw_bytes = base64.b64decode(b64_part)
                fname = f"{prefix}_p{idx + 1}{ext}"
                fpath = UPLOADS_DIR / fname
                fpath.write_bytes(raw_bytes)
                url_path = f"/uploads/{fname}"
                if first_saved_path is None:
                    first_saved_path = fpath
                    first_saved_url = url_path
                cleaned_photos.append({"src": url_path, "caption": caption})
            except Exception:
                pass
        elif isinstance(src, str) and src:
            cleaned_photos.append({"src": src, "caption": caption})
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

    ship_name = form_data.get("ship_name") or "LS JUPITER"
    report_title_type = form_data.get("report_header_title") or "BÁO CÁO NGÀY"
    rows = form_data.get("rows") or []
    photos = form_data.get("photos") or []
    rows_count = len(rows)
    photos_count = len(photos)
    conclusion = custom_conclusion or f"PySide6 da tong hop '{report_title_type}' - Tau {ship_name} ({rows_count} hang muc, {photos_count} hinh anh)."

    out_img_name = f"report_img_{sub_id}_{int(time.time())}.png"
    out_img_path = REPORTS_DIR / out_img_name

    # Tạo ảnh Tổng hợp Preview (Hiển thị lưới tối đa 12 ảnh nếu có nhiều ảnh, hoặc 1 ảnh lớn)
    photo_paths: List[Path] = []
    for p in photos[:12]:
        src = p.get("src") if isinstance(p, dict) else p
        loc = resolve_local_photo_path(src)
        if loc:
            photo_paths.append(loc)
    if not photo_paths and input_image_path and input_image_path.exists():
        photo_paths.append(input_image_path)

    canvas_w = 840
    if len(photo_paths) > 1:
        cols = 4
        grid_rows = (len(photo_paths) + cols - 1) // cols
        cell_w, cell_h = 190, 135
        grid_h = grid_rows * (cell_h + 10) + 10
        canvas_h = 110 + grid_h + 115
        report_canvas = Image.new("RGB", (canvas_w, canvas_h), (15, 23, 42))
        draw = ImageDraw.Draw(report_canvas)
        draw.rectangle([0, 0, canvas_w, 85], fill=(3, 105, 161))
        draw.text((25, 18), f"ALLSEA MANAGEMENT JSC - {report_title_type} ({report_code})", fill=(255, 255, 255))
        draw.text((25, 48), f"Tau: {ship_name} | Nguoi BC: {form_data.get('reporter') or full_name} | {photos_count} anh | {now_str}", fill=(224, 242, 254))

        start_x = 25
        y_offset = 100
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
                draw.rectangle([x0 + 4, y0 + 4, x0 + 58, y0 + 22], fill=(15, 23, 42))
                draw.text((x0 + 10, y0 + 7), f"#{idx + 1}", fill=(255, 255, 255))
            except Exception:
                pass
        y_offset += grid_h + 8
    else:
        base_img = None
        if photo_paths:
            try:
                base_img = Image.open(str(photo_paths[0])).convert("RGB")
                base_img.thumbnail((760, 440))
            except Exception:
                base_img = None
        canvas_h = (115 + base_img.height + 115) if base_img else 320
        report_canvas = Image.new("RGB", (canvas_w, canvas_h), (15, 23, 42))
        draw = ImageDraw.Draw(report_canvas)
        draw.rectangle([0, 0, canvas_w, 85], fill=(3, 105, 161))
        draw.text((25, 18), f"ALLSEA MANAGEMENT JSC - REPORT ({report_code})", fill=(255, 255, 255))
        draw.text((25, 48), f"Nguoi bao cao: {form_data.get('reporter') or full_name} | Tau: {ship_name} | {now_str}", fill=(224, 242, 254))
        y_offset = 100
        if base_img:
            x_pos = (canvas_w - base_img.width) // 2
            report_canvas.paste(base_img, (x_pos, y_offset))
            draw.rectangle([x_pos - 2, y_offset - 2, x_pos + base_img.width + 2, y_offset + base_img.height + 2], outline=(34, 197, 94), width=3)
            y_offset += base_img.height + 15

    draw.rectangle([25, y_offset, canvas_w - 25, canvas_h - 15], fill=(30, 41, 59), outline=(56, 189, 248), width=2)
    draw.text((40, y_offset + 12), f"Tau: {ship_name} | Items: {form_data.get('item_type') or task_type}", fill=(56, 189, 248))
    draw.text((40, y_offset + 38), f"So hang muc cong viec: {rows_count} muc | Hinh anh dinh kem: {photos_count} anh", fill=(226, 232, 240))
    draw.text((40, y_offset + 64), f"Ket luan PySide6: {conclusion[:88]}", fill=(74, 222, 128))

    report_canvas.save(str(out_img_path), "PNG")
    report_image_url = f"/reports/{out_img_name}"

    # Tạo tên file HTML & PDF chuẩn A4
    html_name = f"bao_cao_{report_code}.html"
    html_path = REPORTS_DIR / html_name
    report_html_url = f"/reports/{html_name}"

    pdf_name = f"bao_cao_{report_code}.pdf"
    pdf_path = REPORTS_DIR / pdf_name
    report_pdf_url = f"/reports/{pdf_name}"

    headers = form_data.get("headers") or ["STT", "NỘI DUNG CÔNG VIỆC", "PHƯƠNG ÁN", "TIẾN ĐỘ DỰ KIẾN"]
    if not photos and report_image_url:
        photos = [{"src": report_image_url, "caption": "Ảnh tổng hợp từ PySide6"}]
    logo_src = form_data.get("logo_url") or "/allsea_logo.png"
    if not isinstance(logo_src, str) or not logo_src.startswith("/"):
        logo_src = "/allsea_logo.png"
    rep_header_title = form_data.get("report_header_title") or "BÁO CÁO NGÀY"
    reporter_name = form_data.get("reporter") or full_name
    item_type_str = form_data.get("item_type") or task_type
    report_date_str = form_data.get("report_date") or datetime.now().strftime("Ngày %d/%m/%Y")
    arising_str = form_data.get("arising_text") or ""

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
            f'<div class="photo-cell"><img src="{p.get("src") if isinstance(p, dict) else p}" alt="Ảnh hiện trường"/><div class="photo-cap">{p.get("caption","") if isinstance(p, dict) else ""}</div></div>'
            for p in photos
        )
        photos_html = f"""
        <div class="section-title" style="margin-top:18px;">C. MỘT SỐ HÌNH ẢNH SỬA TRONG NGÀY ({len(photos)} ẢNH):</div>
        <div class="photo-grid">{imgs_tags}</div>
        """

        # Bảng 4 cột cho PyMuPDF Story để xuất file PDF chuẩn A4
        pdf_cells = []
        for idx, p in enumerate(photos):
            raw_src = p.get("src") if isinstance(p, dict) else p
            cap = p.get("caption", "") if isinstance(p, dict) else ""
            arch_name = str(raw_src).split("/")[-1]
            cap_html = f'<div style="font-size:8.5pt;text-align:center;color:#334155;margin-top:2pt;">{cap}</div>' if cap else ""
            pdf_cells.append(
                f'<td style="width:25%;border:0.5pt solid #cbd5e1;padding:3pt;text-align:center;vertical-align:top;">'
                f'<img src="{arch_name}" width="118" height="92" />{cap_html}</td>'
            )
        pdf_rows_str = ""
        for i in range(0, len(pdf_cells), 4):
            chunk = pdf_cells[i:i + 4]
            while len(chunk) < 4:
                chunk.append('<td style="width:25%;border:none;padding:3pt;"></td>')
            pdf_rows_str += "<tr>" + "".join(chunk) + "</tr>"
        pdf_photos_table_html = f"""
        <div style="font-weight:bold;margin-top:12pt;margin-bottom:6pt;font-size:10pt;">C. MỘT SỐ HÌNH ẢNH SỬA TRONG NGÀY ({len(photos)} ẢNH):</div>
        <table style="width:100%;border-collapse:collapse;">{pdf_rows_str}</table>
        """

    # Xuất file PDF thật bằng PyMuPDF (fitz.Story)
    if HAS_PYMUPDF:
        try:
            logo_arch_name = logo_src.split("/")[-1] if "/" in logo_src else "allsea_logo.png"
            pdf_story_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: Arial, Tahoma, sans-serif; font-size: 9.5pt; color: #000; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 8pt; }}
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
        <div style="font-size:13pt;font-weight:bold;">ALLSEA MANAGEMENT JSC</div>
        <div style="font-size:9.5pt;font-weight:bold;color:#334155;">CÔNG TY CỔ PHẦN ALLSEA MANAGEMENT</div>
        <div style="font-size:11.5pt;font-weight:bold;margin-top:3pt;">{rep_header_title}</div>
      </td>
    </tr>
  </table>
  <table>
    <tr>
      <td style="width:52%;"><b>Ship's name :</b> {ship_name}</td>
      <td style="width:48%;"><b>Superintendent :</b> {reporter_name}</td>
    </tr>
    <tr>
      <td colspan="2"><b>Items :</b> {item_type_str}</td>
    </tr>
  </table>
  <p style="margin:4pt 0;">Kính gửi: <b>BAN LÃNH ĐẠO CÔNG TY.</b></p>
  <p style="font-weight:bold;margin:5pt 0;">{report_date_str}</p>
  <p style="font-weight:bold;margin:4pt 0;">A. HẠNG MỤC PHÁT SINH: <span style="font-weight:normal;">{arising_str}</span></p>
  <p style="font-weight:bold;margin:4pt 0;">B. NỘI DUNG CÔNG VIỆC HẰNG NGÀY:</p>
  <table>
    <thead>
      <tr>
        <th style="width:8%;">{headers[0] if len(headers)>0 else 'STT'}</th>
        <th style="width:34%;">{headers[1] if len(headers)>1 else 'NỘI DUNG CÔNG VIỆC'}</th>
        <th style="width:42%;">{headers[2] if len(headers)>2 else 'PHƯƠNG ÁN'}</th>
        <th style="width:16%;">{headers[3] if len(headers)>3 else 'TIẾN ĐỘ'}</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
  {pdf_photos_table_html}
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
  body {{ font-family: 'Tahoma', 'Segoe UI', Arial, sans-serif; margin: 0; padding: 16px; background: #cbd5e1; color: #000; font-size: 13px; }}
  .a4-page {{ max-width: 820px; margin: 0 auto; background: #fff; padding: 26px 32px; box-shadow: 0 4px 25px rgba(0,0,0,0.15); }}
  .top-actions {{ max-width: 820px; margin: 0 auto 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; background: #0f172a; padding: 10px 14px; border-radius: 10px; color: #fff; }}
  .btn-act {{ background: #0284c7; color: #fff; border: none; padding: 9px 15px; border-radius: 8px; cursor: pointer; font-weight: bold; font-size: 13px; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; }}
  .btn-pdf {{ background: #16a34a; }}
  /* Bảng Header Logo & Tên Công Ty */
  .header-table {{ width: 100%; border-collapse: collapse; border: 2px solid #000; margin-bottom: 14px; }}
  .header-table td {{ border: 1.5px solid #000; padding: 10px 14px; vertical-align: middle; }}
  .logo-cell {{ width: 115px; text-align: center; }}
  .logo-cell img {{ width: 72px; height: 72px; object-fit: contain; }}
  .title-cell {{ text-align: center; }}
  .company-name {{ font-size: 16px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.4px; }}
  .report-name {{ font-size: 15px; font-weight: bold; text-transform: uppercase; margin-top: 4px; }}
  /* Bảng Ship's name / Superintendent / Items */
  .meta-table {{ width: 100%; border-collapse: collapse; border: 1.5px solid #000; margin-bottom: 14px; font-size: 13px; }}
  .meta-table td {{ border: 1px solid #000; padding: 6px 10px; }}
  .salutation {{ margin: 10px 0 14px; font-size: 13px; }}
  .date-line {{ font-weight: bold; margin: 12px 0; font-size: 13.5px; }}
  .section-title {{ font-weight: bold; margin: 6px 0 6px 18px; font-size: 13px; text-transform: uppercase; }}
  /* Bảng Nội dung công việc */
  .work-table {{ width: 100%; border-collapse: collapse; border: 1.5px solid #000; margin-top: 8px; font-size: 12.5px; }}
  .work-table th, .work-table td {{ border: 1px solid #000; padding: 6px 8px; vertical-align: top; line-height: 1.4; }}
  .work-table th {{ background: #f8fafc; text-align: center; font-weight: bold; text-transform: uppercase; }}
  .group-row td {{ background: #f1f5f9; font-weight: bold; }}
  /* Lưới hình ảnh tự động sắp xếp 4 cột gọn gàng, rõ nét */
  .photo-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-top: 10px; }}
  .photo-cell {{ border: 1px solid #cbd5e1; background: #f8fafc; overflow: hidden; page-break-inside: avoid; display: flex; flex-direction: column; }}
  .photo-cell img {{ width: 100%; height: 155px; object-fit: cover; display: block; }}
  .photo-cap {{ font-size: 11px; padding: 3px 5px; text-align: center; color: #334155; }}
  @media (max-width: 650px) {{ .photo-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
  @media print {{
    body {{ background: #fff; padding: 0; }}
    .top-actions {{ display: none !important; }}
    .a4-page {{ box-shadow: none; padding: 10px; max-width: 100%; }}
    .photo-grid {{ grid-template-columns: repeat(4, 1fr); }}
  }}
</style>
</head>
<body>
<div class="top-actions">
  <div style="display:flex;gap:8px;flex-wrap:wrap;">
    <a class="btn-act btn-pdf" href="{report_pdf_url}" download="{pdf_name}">📥 Tải File PDF (.pdf) Về Máy / Điện Thoại</a>
    <button class="btn-act" style="background:#0d9488;" onclick="exportClientPdf()">📄 Xuất PDF Trực Tiếp</button>
    <button class="btn-act" onclick="window.print()">🖨️ In Báo Cáo A4</button>
  </div>
  <span style="color:#cbd5e1;font-size:12px;">Mã PySide6: <b>{report_code}</b> | {now_str}</span>
</div>
<div class="a4-page" id="a4-printable-area">
  <table class="header-table">
    <tr>
      <td class="logo-cell"><img src="{logo_src}" alt="Allsea Logo" crossorigin="anonymous"/></td>
      <td class="title-cell">
        <div class="company-name">ALLSEA MANAGEMENT JSC</div>
        <div style="font-size:12px;color:#334155;font-weight:bold;">CÔNG TY CỔ PHẦN ALLSEA MANAGEMENT</div>
        <div class="report-name">{rep_header_title}</div>
      </td>
    </tr>
  </table>

  <table class="meta-table">
    <tr>
      <td style="width:52%;"><b>Ship's name :</b> &nbsp;{ship_name}</td>
      <td style="width:48%;"><b>Người báo cáo (Superintendent) :</b> &nbsp;{reporter_name}</td>
    </tr>
    <tr>
      <td colspan="2"><b>Items :</b> &nbsp;{item_type_str}</td>
    </tr>
  </table>

  <div class="salutation">Kính gửi: <b>BAN LÃNH ĐẠO CÔNG TY.</b></div>
  <div class="date-line">{report_date_str}</div>

  <div class="section-title">A. HẠNG MỤC PHÁT SINH: <span style="font-weight:normal;text-transform:none;">{arising_str}</span></div>
  <div class="section-title">B. NỘI DUNG CÔNG VIỆC HẰNG NGÀY:</div>

  <table class="work-table">
    <thead>
      <tr>
        <th style="width:46px;">{headers[0] if len(headers)>0 else 'STT'}</th>
        <th style="width:34%;">{headers[1] if len(headers)>1 else 'NỘI DUNG CÔNG VIỆC'}</th>
        <th style="width:42%;">{headers[2] if len(headers)>2 else 'PHƯƠNG ÁN'}</th>
        <th style="width:16%;">{headers[3] if len(headers)>3 else 'TIẾN ĐỘ DỰ KIẾN'}</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>

  {photos_html}
</div>
<script>
function exportClientPdf() {{
  const el = document.getElementById('a4-printable-area');
  if (window.html2pdf) {{
    html2pdf().set({{
      margin: [8, 8, 8, 8],
      filename: '{pdf_name}',
      image: {{ type: 'jpeg', quality: 0.92 }},
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

    # Tối ưu tốc độ: Tách toàn bộ ảnh Base64 trong form_payload_json ra file vật lý ngay lập tức
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

    cur.execute("""
        INSERT INTO submissions (username, full_name, title, note_text, task_type, input_image_url, status, auto_process, form_payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (username, user["full_name"], title, note_text, task_type, input_image_url, "pending", auto_proc, cleaned_payload_json, now))
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
        "report_summary, report_image_url, report_html_url, report_pdf_url, created_at, processed_at"
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

    # Nếu đã completed và không có yêu cầu ghi đè custom_conclusion thì trả về ngay để tránh xử lý lặp
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
        return FileResponse(str(index_file))
    return HTMLResponse("<h3>Đang khởi tạo giao diện Web/APK...</h3>")


@app.get("/{asset_name}")
def serve_web_assets(asset_name: str):
    safe_path = (WEB_DIR / asset_name).resolve()
    if safe_path.parent == WEB_DIR.resolve() and safe_path.exists() and safe_path.is_file():
        return FileResponse(str(safe_path))
    raise HTTPException(status_code=404, detail="Không tìm thấy file")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
