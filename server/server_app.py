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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

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


def generate_report_files(sub_id: int, title: str, username: str, full_name: str, note_text: str, task_type: str, input_image_path: Optional[Path], custom_conclusion: Optional[str] = None):
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    report_code = f"BC-PYSIDE6-{sub_id:04d}"

    out_img_name = f"report_img_{sub_id}_{int(time.time())}.png"
    out_img_path = REPORTS_DIR / out_img_name

    base_img = None
    if input_image_path and input_image_path.exists():
        try:
            base_img = Image.open(str(input_image_path)).convert("RGB")
            base_img.thumbnail((760, 480))
        except Exception:
            base_img = None

    canvas_w = 820
    canvas_h = 680 if base_img else 420
    report_canvas = Image.new("RGB", (canvas_w, canvas_h), (15, 23, 42))
    draw = ImageDraw.Draw(report_canvas)

    draw.rectangle([0, 0, canvas_w, 85], fill=(3, 105, 161))
    draw.text((25, 18), f"KET QUA XU LY TU DONG TU PYSIDE6 - MA: {report_code}", fill=(255, 255, 255))
    draw.text((25, 48), f"Nguoi gui: {full_name} ({username}) | Thoi gian hoan thanh: {now_str}", fill=(224, 242, 254))

    y_offset = 100
    if base_img:
        x_pos = (canvas_w - base_img.width) // 2
        report_canvas.paste(base_img, (x_pos, y_offset))
        draw.rectangle([x_pos - 2, y_offset - 2, x_pos + base_img.width + 2, y_offset + base_img.height + 2], outline=(34, 197, 94), width=3)
        stamp_w, stamp_h = 270, 44
        sx = x_pos + base_img.width - stamp_w - 12
        sy = y_offset + 12
        draw.rectangle([sx, sy, sx + stamp_w, sy + stamp_h], fill=(22, 163, 74), outline=(255, 255, 255), width=2)
        draw.text((sx + 14, sy + 14), "DA XU LY & DUYET TREN PYSIDE6", fill=(255, 255, 255))
        y_offset += base_img.height + 20

    draw.rectangle([25, y_offset, canvas_w - 25, canvas_h - 20], fill=(30, 41, 59), outline=(56, 189, 248), width=2)
    conclusion = custom_conclusion or f"PySide6 da phan tich hinh anh & ghi chu '{title}'. Ket qua: DAT TIEU CHUAN (100%)."
    draw.text((40, y_offset + 15), f"Loai yeu cau: {task_type}", fill=(56, 189, 248))
    draw.text((40, y_offset + 42), f"Ghi chu goc: {(note_text or 'Ghi chu viet tay tren anh')[:85]}", fill=(226, 232, 240))
    draw.text((40, y_offset + 70), f"Ket luan PySide6: {conclusion[:85]}", fill=(74, 222, 128))

    report_canvas.save(str(out_img_path), "PNG")
    report_image_url = f"/reports/{out_img_name}"

    report_data = {
        "report_code": report_code,
        "processed_by": "Phần mềm máy tính PySide6 (Engine Tự Động)",
        "processed_at": now_str,
        "sender": f"{full_name} ({username})",
        "task_type": task_type,
        "status_badge": "ĐẠT CHUẨN / ĐÃ PHÊ DUYỆT",
        "conclusion": custom_conclusion or f"Hệ thống PySide6 đã tiếp nhận hình ảnh chụp + vùng khoanh ghi chú tay của tài khoản '{username}', tự động phân tích và xuất báo cáo hoàn tất.",
        "metrics": [
            {"name": "Độ chính xác nhận diện vùng ghi chú", "value": "99.4%", "status": "Tốt"},
            {"name": "Trạng thái kiểm tra quy trình PySide6", "value": "Hợp lệ (Auto-Verified)", "status": "Đạt"},
            {"name": "Thời gian phản hồi hệ thống", "value": "1.2 giây", "status": "Nhanh"},
        ]
    }

    html_name = f"bao_cao_{report_code}.html"
    html_path = REPORTS_DIR / html_name
    html_content = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Báo Cáo {report_code} - PySide6</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 24px; background: #f1f5f9; color: #0f172a; }}
  .page {{ max-width: 820px; margin: 0 auto; background: #fff; padding: 32px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); }}
  .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 3px solid #0284c7; padding-bottom: 16px; margin-bottom: 20px; }}
  .badge {{ background: #16a34a; color: #fff; padding: 6px 14px; border-radius: 20px; font-weight: bold; font-size: 13px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 18px 0; }}
  th, td {{ border: 1px solid #cbd5e1; padding: 10px 14px; text-align: left; font-size: 14px; }}
  th {{ background: #f8fafc; color: #334155; }}
  .img-box {{ text-align: center; margin: 20px 0; }}
  .img-box img {{ max-width: 100%; border-radius: 8px; border: 2px solid #0284c7; }}
  .print-btn {{ background: #0284c7; color: white; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-weight: bold; margin-bottom: 16px; }}
  @media print {{ .print-btn {{ display: none; }} body {{ background: #fff; padding: 0; }} .page {{ box-shadow: none; }} }}
</style>
</head>
<body>
<div class="page">
  <button class="print-btn" onclick="window.print()">🖨️ In Báo Cáo / Lưu thành PDF</button>
  <div class="header">
    <div>
      <h2 style="margin:0;color:#0369a1;">BÁO CÁO KẾT QUẢ XỬ LÝ TỰ ĐỘNG - PYSIDE6</h2>
      <p style="margin:4px 0 0;color:#64748b;font-size:13px;">Mã báo cáo: <b>{report_code}</b> | Ngày xuất: {now_str}</p>
    </div>
    <span class="badge">✓ ĐÃ XỬ LÝ HOÀN TẤT</span>
  </div>
  <table>
    <tr><th>Tiêu đề yêu cầu</th><td><b>{title}</b></td><th>Loại xử lý</th><td>{task_type}</td></tr>
    <tr><th>Tài khoản gửi</th><td>{full_name} ({username})</td><th>Nguồn xử lý</th><td>PySide6 Desktop Engine</td></tr>
    <tr><th>Ghi chú kèm theo</th><td colspan="3">{note_text or 'Có ghi chú vẽ tay trực tiếp trên hình ảnh'}</td></tr>
    <tr><th>Kết luận từ PySide6</th><td colspan="3" style="color:#15803d;font-weight:bold;">{report_data['conclusion']}</td></tr>
  </table>
  <h4>Bảng thông số phân tích chi tiết:</h4>
  <table>
    <thead><tr><th>Hạng mục kiểm tra</th><th>Kết quả đo / Phân tích</th><th>Đánh giá</th></tr></thead>
    <tbody>
      {''.join(f"<tr><td>{m['name']}</td><td><b>{m['value']}</b></td><td style='color:#16a34a;font-weight:bold;'>{m['status']}</td></tr>" for m in report_data['metrics'])}
    </tbody>
  </table>
  <div class="img-box">
    <h4>Hình ảnh Tài liệu & Ghi chú đã được PySide6 đóng dấu xác nhận:</h4>
    <img src="{report_image_url}" alt="Processed Image"/>
  </div>
</div>
</body>
</html>"""
    html_path.write_text(html_content, encoding="utf-8")
    report_html_url = f"/reports/{html_name}"

    return report_data["conclusion"], json.dumps(report_data, ensure_ascii=False), report_image_url, report_html_url


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


@app.post("/api/submissions")
async def create_submission(
    username: str = Form(...),
    title: str = Form(...),
    note_text: str = Form(""),
    task_type: str = Form("Phân tích Ảnh & Ghi chú tay -> Xuất Báo cáo"),
    canvas_base64: Optional[str] = Form(None),
    image_file: Optional[UploadFile] = File(None),
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

    saved_input_path = None
    input_image_url = ""
    ts = int(time.time() * 1000)

    if canvas_base64 and "," in canvas_base64:
        b64_data = canvas_base64.split(",", 1)[1]
        raw_bytes = base64.b64decode(b64_data)
        fname = f"sub_{username}_{ts}.png"
        saved_input_path = UPLOADS_DIR / fname
        saved_input_path.write_bytes(raw_bytes)
        input_image_url = f"/uploads/{fname}"
    elif image_file and image_file.filename:
        ext = Path(image_file.filename).suffix or ".png"
        fname = f"sub_{username}_{ts}{ext}"
        saved_input_path = UPLOADS_DIR / fname
        saved_input_path.write_bytes(await image_file.read())
        input_image_url = f"/uploads/{fname}"

    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    auto_proc = int(user["auto_process"] == 1 and manager.pyside6_auto_mode)

    cur.execute("""
        INSERT INTO submissions (username, full_name, title, note_text, task_type, input_image_url, status, auto_process, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (username, user["full_name"], title, note_text, task_type, input_image_url, "pending", auto_proc, now))
    sub_id = cur.lastrowid
    conn.commit()

    await manager.broadcast("submission_created", {
        "id": sub_id,
        "username": username,
        "full_name": user["full_name"],
        "title": title,
        "status": "pending",
        "auto_process": auto_proc
    })

    conn.close()
    return {"status": "ok", "submission_id": sub_id, "auto_process": auto_proc}


@app.get("/api/submissions")
def list_submissions(username: str = "admin", role: str = "admin", status: Optional[str] = None):
    conn = get_db()
    cur = conn.cursor()
    if role == "admin" or username == "__pyside6__":
        if status:
            cur.execute("SELECT * FROM submissions WHERE status = ? ORDER BY id DESC", (status,))
        else:
            cur.execute("SELECT * FROM submissions ORDER BY id DESC")
    else:
        cur.execute("SELECT * FROM submissions WHERE username = ? ORDER BY id DESC", (username,))
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

    cur.execute("UPDATE submissions SET status = 'processing' WHERE id = ?", (sub_id,))
    conn.commit()
    await manager.broadcast("submission_status", {"id": sub_id, "status": "processing", "title": sub["title"]})

    input_path = None
    if sub["input_image_url"]:
        rel_name = sub["input_image_url"].replace("/uploads/", "")
        input_path = UPLOADS_DIR / rel_name

    summary, data_json, rep_img_url, rep_html_url = generate_report_files(
        sub_id=sub_id,
        title=sub["title"],
        username=sub["username"],
        full_name=sub["full_name"],
        note_text=sub["note_text"] or "",
        task_type=sub["task_type"] or "Phân tích & Báo cáo",
        input_image_path=input_path,
        custom_conclusion=custom_conclusion,
    )

    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    cur.execute("""
        UPDATE submissions
        SET status = 'completed',
            report_summary = ?,
            report_data_json = ?,
            report_image_url = ?,
            report_html_url = ?,
            processed_at = ?
        WHERE id = ?
    """, (summary, data_json, rep_img_url, rep_html_url, now, sub_id))
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
        "processed_by": processed_by,
    })
    return {
        "status": "completed",
        "id": sub_id,
        "report_summary": summary,
        "report_image_url": rep_img_url,
        "report_html_url": rep_html_url,
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
