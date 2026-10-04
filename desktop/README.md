# English Match — ứng dụng Windows và macOS

Chuyển từ file `english-match-web-v2(2)(2).zip` được cung cấp ngày 27/09/2026. Giữ 16 từ và List 1, ghép cặp, random không lặp, quản lý từ/list, nhập CSV, lưu vòng học, xuất/khôi phục JSON, flashcard, gõ đáp án, phát âm, ôn từ sai, lịch sử và thống kê.

## Mới trong 1.4.0

- **Ngữ pháp:** đọc ngoại tuyến đủ 26 chương và 295 mục; tìm nội dung có/không dấu, đánh dấu đã đọc, lưu mục để xem lại, mở lại đúng vị trí học. Công thức, ví dụ và bảng tra cứu được đưa vào giao diện đọc riêng.
- **Loại từ:** hiện trên cả hai mặt flashcard và thẻ gợi ý khi gõ; ghép cặp hiện `provide (v)`. Từ chưa có loại từ không hiện ngoặc rỗng. Chấm bài gõ và phát âm chỉ dùng từ tiếng Anh. Phiên âm vẫn ở phần quản lý/xem trước nhập.
- **Chọn nhiều list:** mở bộ chọn, đánh dấu các list rồi bấm **Áp dụng**. Có Chọn tất cả, Bỏ chọn và tìm tên list. Hỗ trợ ghép cặp, flashcard, gõ đáp án, ôn từ sai và lọc kho từ. Phần ôn tập áp dụng nhóm đã chọn khi bắt đầu buổi mới.
- Sao lưu **định dạng 4** giữ cả tiến độ ngữ pháp và nhóm list của buổi học. Cần ứng dụng 1.4.0 trở lên để đọc bản sao lưu mới; vẫn khôi phục được định dạng 1, 2, 3.
- Tài liệu ngữ pháp được đóng gói cùng ứng dụng. Các file tài liệu gốc không cần có trên máy. Bản này bổ sung lý thuyết và theo dõi việc đọc, chưa có bộ sinh bài tập ngữ pháp tự động.

## Nhập từ bằng 2 hoặc 4 cột

- Phần **Nhập & sao lưu** tự nhận diện từng dòng: `từ | nghĩa` hoặc `từ | loại từ | phiên âm | nghĩa`. Có thể trộn cả hai dạng trong cùng lần nhập; dùng cùng một dấu phân cách cho cả nội dung.
- Hỗ trợ dán từ Excel (Tab), CSV UTF-8, TSV và TXT; nhận dấu `|`, Tab, dấu phẩy hoặc chấm phẩy. Có thể chọn dấu phân cách thủ công khi nội dung khó nhận diện.
- Loại từ và phiên âm có thể để trống trong dạng 4 cột, nhưng giữ đủ dấu phân cách: `order | | /ˈɔːdə/ | đặt hàng`.
- Tiêu đề không bắt buộc. Nhận `english,vietnamese` hoặc `english,part_of_speech,phonetic,vietnamese`, và các tên tiếng Việt tương ứng. Nếu đủ tiêu đề hợp lệ, có thể đổi thứ tự cột; dòng không có tiêu đề dùng thứ tự trong mẫu.
- Bảng xem trước hiển thị đủ từ, loại từ, phiên âm, nghĩa, số dòng và kết quả. Dòng sai số cột hoặc quá dài sẽ được báo lỗi; không nhập một phần khi còn lỗi.
- Cặp từ/nghĩa đã có được bỏ qua, không ghi đè hai trường cũ. Để sửa từ đã có, dùng **Quản lý từ & list**.
- JSON giữ đầy đủ hai trường, tiến độ học, lịch sử và tiến độ ngữ pháp.

Ví dụ dán cả ba dòng cùng lúc:

```text
noon | giữa trưa
provide | v | /prəˈvaɪd/ | cung cấp
offer | n/v | /ˈɒfə/ | đề nghị, lời đề nghị
```

Nếu một ô chứa dấu phân cách, đặt ô đó trong ngoặc kép; ví dụ CSV: `offer,n/v,/ˈɒfə/,"đề nghị, lời đề nghị"`. Không tự tách nội dung loại từ/phiên âm đang gõ chung trong ô từ tiếng Anh.

## Loại từ và phiên âm (từ 1.2.0)

- Trong **Quản lý từ & list**, bảng có các cột: Từ tiếng Anh, Loại từ, Phiên âm, Nghĩa tiếng Việt, List và Thao tác.
- Form thêm/sửa có hai ô không bắt buộc: **Loại từ** (ví dụ `n`, `v`, `adj`, `n/v`) và **Phiên âm** (ví dụ `/ˈɔːdə/`). Nhập tiếng Anh thuần ở ô Từ tiếng Anh, chẳng hạn `order`.
- Loại từ hiện trong quản lý, xem trước nhập, flashcard, gõ đáp án và sau từ tiếng Anh ở ghép cặp. Phiên âm chỉ hiện trong quản lý và xem trước nhập. Phát âm vẫn đọc từ tiếng Anh.
- Có thể tìm theo loại từ hoặc phiên âm. Sửa hai ô này hoặc chuyển list không xóa giá trị ở ô còn lại. Chỉ sửa loại từ/phiên âm không làm mất vòng học và lịch sử.
- Các từ đã có được giữ nguyên và hai ô mới để trống. Nếu trước đây bạn nhập `order (v/n) /ˈɔːdə/` vào ô tiếng Anh, bấm Sửa để tách thành `order`, `v/n`, `/ˈɔːdə/`. Ứng dụng không tự đoán hay sửa nội dung từ cũ. Đổi chính từ/nghĩa có thể tạo lại vòng học đang dùng từ đó như trước.
- Sao lưu định dạng 4 giữ loại từ, phiên âm và tiến độ ngữ pháp. Nhập được định dạng 1–3; các thông tin chưa có sẽ để trống.
- Nhập CSV hai cột từ/nghĩa vẫn hoạt động; từ 1.3.0 có thể nhập cả bốn cột như hướng dẫn trên.

## Cài và mở

| Máy | File |
| --- | --- |
| Windows 10/11, 64-bit Intel/AMD | `English-Match-1.4.0-win-x64.exe` |
| Mac chip Apple Silicon (M1, M2, M3, M4…); macOS 13 trở lên | `English-Match-1.4.0-mac-arm64.dmg` |
| Mac chip Intel; macOS 13 trở lên | `English-Match-1.4.0-mac-x64.dmg` |

Windows: mở bộ cài, chọn thư mục và hoàn tất. Sau đó mở biểu tượng **English Match** ở Desktop hoặc Start Menu.

Mac: mở DMG, kéo **English Match** vào **Applications**, rồi mở trong Applications. Chọn đúng loại chip tại menu Apple → About This Mac.

Không cần cài Python, Node.js, trình duyệt hoặc thuê máy chủ. Học được khi tắt mạng. Bộ cài miễn phí chưa có chứng chỉ nhà phát hành thương mại / Apple notarization, nên hệ điều hành có thể hiển thị cảnh báo khi mở lần đầu. Hãy kiểm tra đúng nguồn tải; nếu máy do công ty quản lý chặn cài đặt, liên hệ quản trị viên. Không cần tắt bảo vệ của hệ điều hành.

## Cập nhật từ các bản trước

Hãy xuất JSON trước khi cập nhật. Thoát ứng dụng cũ, chạy bộ cài 1.4.0 (Mac: thay ứng dụng trong Applications). Dữ liệu vẫn ở cùng thư mục trên máy. Bản mới tự thêm hai cột, giữ kho từ, list, tiến độ và lịch sử cũ. Tiêu đề “English Match 2.2” từng hiển thị là nhãn của giao diện web gốc; số phiên bản ứng dụng desktop được xem tại menu English Match → Về English Match.

Phát âm sử dụng giọng tiếng Anh được cài trên hệ điều hành. Nếu chưa có giọng, ứng dụng hướng dẫn cài giọng trong Windows/macOS. Chọn giọng cài trên máy để nghe khi offline.

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
