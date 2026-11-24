# Bìa booklet ISC – International Student Connection

| File | Dùng để |
|---|---|
| `isc_cover_art.png` | Nền bìa **không chữ** (A4 ngang, 3508×2480 px, 300 dpi) – đưa vào Canva rồi đặt logo + chữ lên |
| `isc_cover_with_title.png` | Bản xem trước có sẵn tagline + tiêu đề (Bebas Neue / Montserrat) |
| `render_cover.py` | Script tạo ảnh (chỉnh góc quay, ánh sáng, màu… rồi chạy lại) |

Ý tưởng: Trái Đất nhìn từ Đông Nam Á lúc bình minh – mặt trời ló ở viền phải, phía tây chìm vào đêm với ánh đèn thành phố vàng.
Các đường cung nối TP.HCM (HCMUT) với các trường đối tác: UTS Sydney, RMIT Melbourne, Singapore Polytechnic,
UNITEN Malaysia, Bennett University (Ấn Độ), Seoul, Tokyo. Vòng quỹ đạo + máy bay giấy lấy từ logo ISC.
Toàn bộ màu lấy từ palette CLB (navy/xanh – kem/peach – cam – vàng đồng).

Chạy lại: `pip install numpy scipy pillow global-land-mask` rồi `python3 render_cover.py 1.0`
(`0.4` để xem nhanh). Đèn thành phố lấy từ gói npm `cities.json`, font từ `@fontsource`.
