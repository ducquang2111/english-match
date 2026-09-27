# English Match — ứng dụng Windows và macOS

Chuyển từ đúng file `english-match-web-v2(2)(1).zip` được cung cấp ngày 27/09/2026. Giữ giao diện, 16 từ và List 1, ghép cặp, random không lặp, quản lý từ/list, nhập CSV, lưu vòng học, xuất và khôi phục JSON. Đây là các chức năng trong ZIP; ZIP chưa chứa flashcard hoặc tài khoản online.

## Cài và mở

| Máy | File |
| --- | --- |
| Windows 10/11, 64-bit Intel/AMD | `English-Match-1.0.0-win-x64.exe` |
| Mac chip Apple Silicon (M1, M2, M3, M4…); macOS 13 trở lên | `English-Match-1.0.0-mac-arm64.dmg` |
| Mac chip Intel; macOS 13 trở lên | `English-Match-1.0.0-mac-x64.dmg` |

Windows: mở bộ cài, chọn thư mục và hoàn tất. Sau đó mở biểu tượng **English Match** ở Desktop hoặc Start Menu.

Mac: mở DMG, kéo **English Match** vào **Applications**, rồi mở trong Applications. Chọn đúng loại chip tại menu Apple → About This Mac.

Không cần cài Python, Node.js, trình duyệt hoặc thuê máy chủ. Học được khi tắt mạng. Bộ cài miễn phí chưa có chứng chỉ nhà phát hành thương mại / Apple notarization, nên hệ điều hành có thể hiển thị cảnh báo khi mở lần đầu. Hãy kiểm tra đúng nguồn tải; nếu máy do công ty quản lý chặn cài đặt, liên hệ quản trị viên. Không cần tắt bảo vệ của hệ điều hành.

## Dữ liệu và sao lưu

- Dữ liệu ban đầu lấy từ ZIP. Những lần mở tiếp theo chỉ dùng dữ liệu của bạn, không nạp đè 16 từ mẫu.
- Từ và tiến độ lưu vào `vocabulary.db` trong thư mục dữ liệu. Menu **Dữ liệu → Mở thư mục dữ liệu** mở đúng nơi này.
- Windows: `%APPDATA%\English Match\data`.
- Mac: `~/Library/Application Support/English Match/data`.
- Trước khi cập nhật hoặc chuyển máy, vào **Nhập & sao lưu → Tải bản sao lưu JSON**. Trên máy mới, chọn file JSON trong phần khôi phục, xem trước rồi xác nhận.
- Cài bản mới vào cùng ứng dụng giữ lại dữ liệu. Gỡ ứng dụng cũng không chủ động xóa thư mục dữ liệu riêng.
- Bản desktop này học offline và không tự đồng bộ giữa hai máy. Chuyển dữ liệu bằng JSON; cần máy chủ và bản có tài khoản để đồng bộ online.
- Trước mỗi lần khôi phục, ứng dụng giữ một bản database cũ trong `data/backups`. Để phục hồi thủ công, thoát ứng dụng, sao chép bản đó ra nơi an toàn rồi dùng bản sao làm `data/vocabulary.db`.
- Không đặt database đang chạy trong thư mục đồng bộ đám mây. Hãy đồng bộ bản JSON đã xuất.

## Tự tạo bộ cài miễn phí

Mã nguồn nằm trong thư mục `desktop/` của nhánh `english-match-desktop` trong GitHub. Workflow `.github/workflows/desktop-build.yml` chạy trên Windows, Mac Intel và Mac Apple Silicon, dùng máy chạy tiêu chuẩn của kho công khai.

Mỗi lượt chạy kiểm tra API, quyền truy cập, sao lưu, giữ dữ liệu sau khởi động lại và mở ứng dụng đã đóng gói trên hệ điều hành tương ứng. Các bộ cài ở phần **Artifacts** của lượt chạy; giải nén ZIP artifact để lấy EXE/DMG. Artifact có thời hạn lưu 7 ngày; tải về máy để giữ lâu dài hoặc chạy workflow lại.

Máy phát triển cần Python 3.12 và Node.js 24:

```sh
python -m pip install pyinstaller==6.22.3
npm ci
python scripts/build-backend.py
npm test
python scripts/smoke-backend.py --frozen
npm run dist
python scripts/smoke-native.py
```

Tạo bộ cài macOS trên Mac và Windows trên Windows. Trên Mac, kiến trúc Python/Node phải trùng kiến trúc muốn đóng gói. Chạy mã nguồn: `npm start` (cần Python trên máy; có thể đặt `EM_PYTHON` thành đường dẫn Python).

Kiến trúc: Electron mở giao diện có sẵn, khởi động backend Python đóng gói bằng PyInstaller ở cổng loopback ngẫu nhiên. Backend chỉ nhận yêu cầu có khóa phiên do ứng dụng cấp. Renderer không có Node.js và chạy trong sandbox. Không có dịch vụ tự khởi động cùng hệ điều hành hoặc tiến trình nền sau khi thoát bình thường.

Giấy phép thư viện bên thứ ba đi kèm bộ Electron. Không tự cập nhật âm thầm; cài bản mới do chủ dự án cung cấp.
