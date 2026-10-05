# Ôn tập Lịch sử – trắc nghiệm kiểu Quizlet

Website ôn tập trắc nghiệm nhẹ, nhanh, tối ưu cho điện thoại.
🔗 **https://dontplsgx.github.io/Projects/**

## Tính năng
- Ôn từng bài, **ôn tổng hợp** tất cả, hoặc tự chọn nhiều bài để ôn chung
- Xáo trộn câu hỏi và đáp án (không xáo những câu có đáp án kiểu "Cả A và B")
- Trả lời sai: hiện đáp án bạn chọn (đỏ) và đáp án đúng (xanh)
- Trả lời đúng: tự chuyển câu ngay, không mất thời gian
- Hết lượt: xem lại toàn bộ câu sai và **ôn lại riêng các câu sai**
- Ghi nhớ tiến độ: "Đã thuộc", "Câu hay sai", tiếp tục phiên đang làm dở
- Giao diện sáng/tối, cài lên màn hình chính như app, dùng được khi mất mạng

## Cập nhật câu hỏi
Tải các file `.docx` vào thư mục [`quiz/source`](quiz/source) trên nhánh `main`.
GitHub Actions sẽ chạy `tools/docx_to_quiz.py` để tạo `quiz/questions.json` rồi đưa website lên nhánh `gh-pages`.
Xem tab **Actions** để kiểm tra cảnh báo (vd câu chưa xác định được đáp án đúng).

Trình chuyển đổi nhận đáp án đúng được đánh dấu bằng tô màu nền, chữ màu, gạch chân,
in đậm, dấu `*`, dòng `Đáp án: B`, hoặc bảng/dòng đáp án ở cuối file.

Chạy thử trên máy: `pip install python-docx && python tools/docx_to_quiz.py && python -m http.server -d quiz`
