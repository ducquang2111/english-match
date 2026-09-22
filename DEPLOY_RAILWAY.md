# Deploy English Match lên Railway

## 1. Đưa source lên GitHub
Tạo một repository mới trên GitHub rồi upload toàn bộ các file trong thư mục này.

## 2. Tạo project Railway
- Vào Railway.
- Chọn New Project -> Deploy from GitHub Repo.
- Chọn repository vừa tạo.
- Railway sẽ dùng `railway.json` và chạy `python server.py`.

## 3. Tạo Persistent Volume cho SQLite
Trong service trên Railway:
- Mở phần Volumes.
- Add Volume.
- Mount path: `/data`

## 4. Khai báo vị trí database
Trong Variables của service thêm:

`DB_PATH=/data/vocabulary.db`

Source này có cơ chế bootstrap: nếu `/data/vocabulary.db` chưa tồn tại ở lần chạy đầu,
nó sẽ copy file `vocabulary.db` đang có trong repository sang Volume. Vì vậy dữ liệu/list hiện tại
được giữ nguyên khi deploy lần đầu.

## 5. Tạo link public
Trong Railway service:
- Networking -> Generate Domain.
- Railway sẽ cấp một URL public.
- Gửi URL đó cho điện thoại/laptop khác để sử dụng.

## 6. Sau khi đã deploy
Mọi từ/list mới thêm qua website sẽ được ghi vào `/data/vocabulary.db` trên Persistent Volume.
Redeploy code sẽ không xóa database trong Volume.

Lưu ý: không xóa Volume nếu vẫn cần dữ liệu. Nên tải/copy database định kỳ để sao lưu.
