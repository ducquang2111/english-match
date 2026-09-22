# English Match v2 — học từ vựng theo list, random không lặp

Bản nâng cấp từ source code cũ, vẫn dùng **Python chuẩn + SQLite**, không cần cài Flask hay thư viện ngoài.

## Chức năng mới

- Chia từ vựng thành nhiều **list** riêng: ví dụ `TOEIC 1`, `Unit 3`, `Travel`, `School`...
- Khi thêm từ mới, chọn list để lưu.
- Có thể chuyển một từ từ list này sang list khác ngay trong phần quản lý.
- Chọn học **một list cụ thể** hoặc **🎲 Tất cả list · Random toàn bộ**.
- Trong mỗi vòng học, danh sách được trộn **một lần**, sau đó chia thành từng trang 8 cặp. Vì vậy một từ không bị random lặp lại ở các trang khác trong cùng vòng.
- Hết một trang: tự chuyển trang kế tiếp.
- Hết toàn bộ vòng: dừng lại và cho phép bấm **Random vòng mới**.
- Nút **Trộn vị trí ô** chỉ đổi vị trí các ô hiện tại, không đổi bộ từ và không làm phát sinh từ lặp.
- Tìm kiếm từ, lọc theo list, xóa từ.
- Có thể xóa list rỗng. Nếu list còn từ, hệ thống không cho xóa để tránh mất dữ liệu ngoài ý muốn.
- Dữ liệu lưu trong `vocabulary.db`, không mất khi tắt web/máy.

## Tương thích với database cũ

Khi chạy bản v2 lần đầu, `server.py` tự nâng cấp database cũ:

1. Tạo bảng `vocabulary_lists`.
2. Tạo `List 1`.
3. Thêm cột `list_id` vào bảng `vocabulary` nếu database cũ chưa có.
4. Toàn bộ từ cũ được đưa vào `List 1`.

Không cần xóa database cũ và không cần nhập lại từ.

## Chạy web

### Windows

```bash
python server.py
```

### macOS / Linux

```bash
python3 server.py
```

Sau đó mở:

```text
http://127.0.0.1:8000
```

Dừng server bằng `Ctrl + C`.

## Cấu trúc

- `server.py`: server + API + SQLite + migration.
- `index.html`: toàn bộ giao diện và logic game.
- `vocabulary.db`: database từ vựng và list.

## API chính

- `GET /api/lists` — lấy danh sách list.
- `POST /api/lists` — tạo list mới.
- `DELETE /api/lists/<id>` — xóa list rỗng.
- `GET /api/vocabulary?list_id=<id>&search=...` — lấy/lọc từ.
- `POST /api/vocabulary` — thêm từ mới vào list.
- `PUT /api/vocabulary/<id>` — sửa/chuyển từ sang list khác.
- `DELETE /api/vocabulary/<id>` — xóa từ.

## Lưu ý khi deploy Internet

SQLite lưu bền vững trên máy/VPS có ổ đĩa cố định. Nếu deploy lên dịch vụ có filesystem tạm thời, cần persistent volume hoặc chuyển sang PostgreSQL/MySQL để dữ liệu không bị reset khi deploy lại.
