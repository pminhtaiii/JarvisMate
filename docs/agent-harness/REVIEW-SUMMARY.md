# Tổng hợp review Tool Catalog, miền và Agent Skill

Ngày phân tích: **10/11/2026**. Nhánh tài liệu: `codex/010-tool-domain-skill-analysis`, tạo từ commit `e216ad5115229598149ca8c4e3f43554ce065268` của nhánh 009. Nhánh 009 được giữ nguyên. Đây là nghiên cứu tĩnh để con người review; chưa triển khai skill/retrieval hoặc sửa inference.

## A. Số tool và nguồn đã kiểm

Train: **147 tool / 46 app**. Public Test: **122 tool / 36 app**. Giao: **88 tool**; chỉ Train: **59**; chỉ Public Test: **34**. Hợp: **181 tool / 57 app**.

Catalog gốc nằm trong `train+public_test/train+public_test/{train,public_test}/` theo chỉ dẫn của người dùng. Hai bản có trong repository khớp sâu nội dung JSON với dataset. Cả hai schema version `2.7.0`. Toàn bộ **88 entry chung bằng nhau**, không có khác mô tả/schema; **25 module app chung khớp mã nguồn** sau chuẩn hoá xuống dòng. Chỉ Train: 59 tool; chỉ Public Test: 34 tool. Đây là số lượng catalog, không phải số tool của mỗi mẫu.

Từng tên, mô tả, required, optional, type/enum, schema đầy đủ, returns, split, JSON Pointer và liên kết implementation nằm tại [tool-catalog-inventory.md](tool-catalog-inventory.md). Inventory cũng ghi SHA-256 của cả catalog gốc và bản repo để tái kiểm tra.

## B–C. Miền nghiệp vụ và danh sách tool

**17 miền chính**; mỗi tool thuộc đúng một miền chính, công cụ dùng chung được giải thích riêng tại [business-domains.md](business-domains.md). Số tool bên dưới đếm trên hợp catalog, không cộng trùng hai split.

| Miền | Mô tả | Số tool (hợp) | Tên tool |
| --- | --- | --- | --- |
| D01 — Nhà ở, thiết bị và việc nhà | Điều khiển thiết bị, chu trình, điện năng và quy tắc hằng ngày. | 19 | `smart_home.get_status`, `smart_home.light_set`, `smart_home.fan_set`, `smart_home.climate_set`, `smart_home.switch_set`, `smart_home.scene_run`, `robot_vacuum.get_status`, `robot_vacuum.start`, `robot_vacuum.stop`, `appliances.list`, `appliances.start_cycle`, `appliances.stop`, `home_energy.get_usage`, `home_energy.set_alert`, `home_automation.list_rules`, `home_automation.create_rule`, `home_automation.delete_rule`, `household_chores.list_chores`, `household_chores.assign` |
| D02 — An ninh và ra vào | Cảnh báo, camera, chế độ bảo vệ và khoá cửa. | 7 | `home_security.list_alerts`, `home_security.get_camera`, `home_security.arm`, `home_security.acknowledge_alert`, `door_lock.list_locks`, `door_lock.set_lock`, `door_lock.grant_guest_code` |
| D03 — Lịch, nhắc việc và ghi chép | Quản lý thời gian và bản ghi cá nhân. | 18 | `alarm.list`, `alarm.create`, `alarm.update`, `alarm.delete`, `reminders.list`, `reminders.create`, `reminders.complete`, `reminders.delete`, `calendar.list_events`, `calendar.create_event`, `calendar.update_event`, `calendar.cancel_event`, `notes.list`, `notes.create`, `notes.append`, `tasks.list`, `tasks.add`, `tasks.complete` |
| D04 — Liên lạc và hội họp | Danh bạ, điện thoại, SMS, OTT, email và phòng họp. | 21 | `contacts.search`, `contacts.get`, `contacts.update`, `phone.call`, `phone.recent_calls`, `sms.send`, `sms.read_recent`, `chat_ott.list_chats`, `chat_ott.read_chat`, `chat_ott.send_message`, `chat_ott.send_location`, `chat_ott.call`, `email.list`, `email.read`, `email.send`, `email.create_draft`, `email.reply`, `email.archive`, `video_meeting.list_meetings`, `video_meeting.create`, `video_meeting.join` |
| D05 — Ngân hàng, ví và hoá đơn | Tài khoản, người thụ hưởng, chuyển tiền và thanh toán. | 12 | `banking.get_balance`, `banking.list_transactions`, `banking.list_beneficiaries`, `banking.transfer`, `banking.open_savings`, `ewallet.get_balance`, `ewallet.transfer`, `ewallet.topup_mobile`, `ewallet.pay_qr`, `bill_payment.list_bills`, `bill_payment.pay`, `bill_payment.schedule_autopay` |
| D06 — Điểm thưởng và gói định kỳ | Đổi ưu đãi và quản lý gói dịch vụ đã có. | 5 | `loyalty.list_vouchers`, `loyalty.get_points`, `loyalty.redeem`, `subscriptions.list`, `subscriptions.cancel` |
| D07 — Tra cứu thông tin và tin tức | Dữ liệu mô phỏng thời tiết, giá, tỷ giá, xổ số và bài báo. | 11 | `weather.get_current`, `weather.get_forecast`, `gold_price.get_price`, `fuel_price.get_price`, `lottery.get_results`, `lottery.check_ticket`, `exchange_rate.get_rate`, `exchange_rate.convert`, `news.headlines`, `news.search`, `news.save` |
| D08 — Di chuyển và địa điểm | Bản đồ, xe công nghệ, xe đạp, vận tải công cộng và chỗ đỗ. | 16 | `maps.search_place`, `maps.get_route`, `maps.save_place`, `ride_hailing.get_quotes`, `ride_hailing.book`, `ride_hailing.cancel`, `ride_hailing.get_ride`, `bike_rental.find_bikes`, `bike_rental.reserve`, `public_transit.find_routes`, `public_transit.next_departures`, `public_transit.topup_card`, `parking.find`, `parking.list_sessions`, `parking.reserve`, `parking.end_session` |
| D09 — Vé di chuyển liên tỉnh | Chuyến bay và vé tàu/xe khách. | 9 | `flights.search`, `flights.book`, `flights.my_bookings`, `flights.cancel`, `flights.check_in`, `train_bus_tickets.search`, `train_bus_tickets.book`, `train_bus_tickets.my_bookings`, `train_bus_tickets.cancel` |
| D10 — Ăn uống và tủ bếp | Đặt món, công thức và ghi nhận nguyên liệu đã dùng. | 10 | `food_delivery.list_restaurants`, `food_delivery.get_menu`, `food_delivery.order_history`, `food_delivery.place_order`, `food_delivery.cancel_order`, `recipes.search`, `recipes.get`, `recipes.save`, `pantry.list_items`, `pantry.consume` |
| D11 — Mua sắm và giao nhận | Danh sách mua, giỏ hàng, hậu mãi và vận đơn. | 16 | `shopping_list.get`, `shopping_list.add`, `shopping_list.remove`, `shopping_list.check`, `package_tracking.track`, `package_tracking.reschedule_delivery`, `package_tracking.schedule_pickup`, `grocery.search`, `grocery.add_to_cart`, `grocery.checkout`, `ecommerce.search`, `ecommerce.order_status`, `ecommerce.add_to_cart`, `ecommerce.checkout`, `ecommerce.cancel_order`, `ecommerce.request_return` |
| D12 — Giải trí và vé sự kiện | Nhạc, podcast/radio, TV và sự kiện. | 14 | `music.list_tracks`, `music.play`, `music.control`, `music.add_to_playlist`, `tv.guide`, `tv.tune`, `tv.control`, `tv.record`, `podcast_radio.search`, `podcast_radio.play`, `podcast_radio.subscribe`, `podcast_radio.queue`, `event_tickets.search`, `event_tickets.book` |
| D13 — Sức khoẻ và thói quen | Ghi lịch thuốc, hoạt động và thói quen do người dùng chỉ định. | 9 | `medication.list`, `medication.add`, `medication.log_taken`, `medication.remove`, `fitness.get_activity`, `fitness.log_workout`, `fitness.set_goal`, `habit_tracker.list_habits`, `habit_tracker.log` |
| D14 — Học tập và thư viện | Khoá học, tiến độ và giữ sách. | 6 | `learning.list_courses`, `learning.enroll`, `learning.schedule_lesson`, `learning.log_progress`, `library.search`, `library.reserve` |
| D15 — Tiện ích tính toán và ngôn ngữ | Phép tính, đổi đơn vị và dịch văn bản. | 3 | `calculator.calculate`, `calculator.convert_unit`, `translator.translate` |
| D16 — Chứng khoán mô phỏng | Báo giá, danh mục, lệnh và cảnh báo giá. | 4 | `stocks.get_quote`, `stocks.get_portfolio`, `stocks.place_order`, `stocks.set_price_alert` |
| D17 — Điều phối thông tin thiếu | Cơ chế meta dùng chung cho mọi nghiệp vụ. | 1 | `sys.ask_missing_info` |


## D. Workflow

**37 họ workflow**, gồm những nhánh thay thế theo loại đối tượng hoặc split; không phải 37 chuỗi call cố định. Mỗi mục có intent, tool, thứ tự, dữ liệu trung gian, điều kiện, missing, completion và evidence trong [workflow-analysis.md](workflow-analysis.md). Có thêm bảng **82 tham chiếu x-ref** được trích từ toàn catalog, giữ đúng đường dẫn tham số.

Mức chứng cứ: **E** tường minh từ catalog/mã; **S** suy luận kết nối dữ liệu; **H** giả thuyết cần xác minh. W22 công thức→mua và W34 vé→nhắc/đặt xe có phần H, không được coi là khả năng end-to-end đã chứng minh. Ngay cả workflow E cũng mới được kiểm tĩnh, chưa chạy trên ToolEnv.

## E–F. Skill ứng viên

**24 candidate skills**. Danh sách required bên dưới là **hợp tool theo các nhánh**, không có nghĩa tất cả phải cùng cài hay luôn gọi. Chọn nhánh mới xác định được tool cần; bước đọc có thể bỏ nếu dữ kiện hợp lệ đã đủ, trừ chỉ dẫn tường minh. Chi tiết precondition, optional tools, workflow, missing, completion và constraints tại [candidate-skills.md](candidate-skills.md).

| Skill ID | Tên skill | Miền | Tool bắt buộc theo nhánh |
| --- | --- | --- | --- |
| S01 | Điều khiển nhà theo đối tượng | D01 | `smart_home.get_status`, `smart_home.light_set`, `smart_home.fan_set`, `smart_home.climate_set`, `smart_home.switch_set`, `smart_home.scene_run` |
| S02 | Điều phối chu trình gia dụng | D01 | `robot_vacuum.get_status`, `robot_vacuum.start`, `appliances.list`, `appliances.start_cycle` |
| S03 | Quản lý quy tắc thiết bị hằng ngày | D01 | `smart_home.get_status`, `home_automation.create_rule`, `home_automation.list_rules`, `home_automation.delete_rule` |
| S04 | Xử lý an ninh và quyền ra vào | D02 | `home_security.list_alerts`, `home_security.acknowledge_alert`, `door_lock.list_locks`, `door_lock.set_lock`, `door_lock.grant_guest_code` |
| S05 | Thay đổi bản ghi cá nhân đang có | D03 | `alarm.list`, `alarm.update`, `alarm.delete`, `reminders.list`, `reminders.complete`, `reminders.delete`, `calendar.list_events`, `calendar.update_event`, `calendar.cancel_event`, `notes.list`, `notes.append`, `tasks.list`, `tasks.complete` |
| S06 | Phân giải người nhận và kênh liên lạc | D04 | `contacts.search`, `phone.call`, `sms.send`, `contacts.update`, `chat_ott.list_chats`, `chat_ott.send_message`, `chat_ott.send_location`, `chat_ott.call` |
| S07 | Xử lý email theo nội dung | D04 | `email.list`, `email.reply`, `email.archive`, `email.create_draft` |
| S08 | Chọn tài khoản và thực hiện giao dịch | D05 | `banking.get_balance`, `banking.transfer`, `banking.open_savings` |
| S09 | Thanh toán ví theo đúng đối tượng | D05, D04, D10 | `ewallet.transfer`, `ewallet.topup_mobile`, `ewallet.pay_qr` |
| S10 | Chọn và thanh toán hoá đơn | D05 | `bill_payment.list_bills`, `bill_payment.pay` |
| S11 | Quản lý ưu đãi và gói định kỳ | D06 | `loyalty.get_points`, `loyalty.redeem`, `subscriptions.list`, `subscriptions.cancel` |
| S12 | Chọn điểm đến và dịch vụ di chuyển | D08 | `ride_hailing.book`, `ride_hailing.get_ride`, `ride_hailing.cancel`, `bike_rental.find_bikes`, `bike_rental.reserve`, `parking.find`, `parking.reserve`, `parking.list_sessions`, `parking.end_session`, `public_transit.find_routes`, `public_transit.next_departures` |
| S13 | Quản lý vé liên tỉnh theo vòng đời | D09 | `flights.search`, `flights.book`, `flights.my_bookings`, `flights.cancel`, `flights.check_in`, `train_bus_tickets.search`, `train_bus_tickets.book`, `train_bus_tickets.my_bookings`, `train_bus_tickets.cancel` |
| S14 | Chọn quán, món và quản lý đơn ăn | D10 | `food_delivery.list_restaurants`, `food_delivery.get_menu`, `food_delivery.place_order`, `food_delivery.order_history`, `food_delivery.cancel_order` |
| S15 | Chuẩn bị nguyên liệu theo công thức | D10, D11 | `recipes.search`, `pantry.list_items`, `shopping_list.add` |
| S16 | Mua hàng theo giỏ | D11 | `ecommerce.search`, `ecommerce.add_to_cart`, `ecommerce.checkout`, `grocery.search`, `grocery.add_to_cart`, `grocery.checkout` |
| S17 | Xử lý đơn hàng và giao nhận | D11 | `ecommerce.order_status`, `ecommerce.cancel_order`, `ecommerce.request_return`, `package_tracking.track`, `package_tracking.reschedule_delivery` |
| S18 | Chọn và lưu nội dung giải trí | D12 | `music.list_tracks`, `music.play`, `music.add_to_playlist`, `podcast_radio.search`, `podcast_radio.play`, `podcast_radio.subscribe`, `podcast_radio.queue`, `tv.guide`, `tv.tune`, `tv.record`, `event_tickets.search`, `event_tickets.book` |
| S19 | Ghi nhận sức khoẻ và học tập theo đối tượng | D13, D14 | `medication.list`, `medication.log_taken`, `medication.remove`, `habit_tracker.list_habits`, `habit_tracker.log`, `learning.list_courses`, `learning.enroll`, `learning.schedule_lesson`, `learning.log_progress`, `library.search`, `library.reserve` |
| S20 | Thực hiện điều kiện chứng khoán mô phỏng | D16 | `stocks.get_quote`, `stocks.place_order`, `stocks.set_price_alert` |
| S21 | Thông báo thông tin từ lịch | D03, D04 | `calendar.list_events`, `sms.send`, `chat_ott.send_message` |
| S22 | Điều khiển nhà theo điều kiện hiện tại | D07, D01 | `weather.get_current`, `weather.get_forecast`, `smart_home.get_status`, `smart_home.climate_set`, `smart_home.switch_set`, `home_energy.get_usage`, `home_energy.set_alert` |
| S23 | Lập giờ nhắc/đón theo chuyến bay | D09, D08, D03 | `flights.my_bookings`, `maps.get_route`, `reminders.create`, `ride_hailing.book` |
| S24 | Dịch rồi gửi đúng kênh | D15, D04 | `translator.translate`, `sms.send`, `chat_ott.send_message`, `email.send` |


Không có hai candidate trùng hoàn toàn tập required tools. Đã chỉ rõ các cặp có thể trùng hướng dẫn: S01/S22 (thiết bị), S06/S21/S24 (người nhận), S12/S23 (xe), S15/S16 (giỏ). Nên tham chiếu đoạn chung, không nhân đôi action hoặc tạo skill cho từng tool. Các yêu cầu đủ dữ kiện chỉ cần một call được liệt kê riêng và thường không cần dedicated skill. W36 xử lý thiếu là quy tắc dùng chung, không cộng thành candidate thứ 25.

## G. Phối hợp nhiều miền

| Ví dụ năng lực được catalog hỗ trợ | Miền / skill phối hợp | Mức và giới hạn |
| --- | --- | --- |
| Tìm quán rồi trả QR theo yêu cầu | D10→D05; S09 | E: merchant_id từ food_delivery.list_restaurants cho ewallet.pay_qr; không phải restaurant_id, không trả QR tự động sau đặt món |
| Đọc lịch rồi nhắn giờ/địa điểm | D03→D04; S21 + đoạn recipient S06 | S: calendar.list_events cung cấp thông tin; SMS hoặc OTT cần đích đúng loại; chưa đo đồng cài trên mẫu |
| Nếu thời tiết đạt điều kiện thì chỉnh thiết bị | D07→D01; S22 + S01 | S: weather.get_current/get_forecast rồi setter; không tạo automation thời tiết tương lai |
| So công thức với đồ bếp, thêm món thiếu vào danh sách hoặc giỏ | D10→D11; S15 + S16 | H ở phần quy đổi đơn vị/SKU; cạnh recipe_id/item_id nội bộ là E; không consume chỉ vì tra công thức |
| Dựa vé và thời gian đi để nhắc rời nhà hoặc đặt xe | D09→D08/D03; S23, nhánh S13/S12 | H: cần địa chỉ sân bay và quy tắc giờ đệm; nhắc và đặt xe là lựa chọn theo ý định |
| Dịch câu rồi gửi vào kênh yêu cầu | D15→D04; S24 + đoạn recipient S06 | S: translator.translate trả translation; không gửi nếu chỉ xin bản dịch |

Trả hoá đơn bằng ví là tác động nhiều app trong cùng D05: bill_payment.pay tự trừ ví; không gọi thêm ewallet.transfer. Các ví dụ trên là tổng hợp từ năng lực tool, **không khẳng định tần suất phổ biến trong dữ liệu**. Ghép skill theo mục tiêu, điều kiện và dữ kiện thiếu, không nối mọi danh sách required thành một chuỗi.

## H. Chứng cứ thiếu, bất định và điểm cần review

- Hai catalog Train/Public Test và mã app tương ứng đều có, không thiếu nguồn chính cho kiểm kê. Chưa có catalog private test trong nguồn được phân tích; không suy khả năng split chưa phát hành.
- Không mở input JSONL, gold labels, predictions, audio hoặc bất kỳ file trong `*_environment/`; không tạo ToolEnv. Do đó chưa có thống kê intent, tần suất đồng cài, chất lượng ASR, số call thực, chất lượng planner hoặc thời gian chạy.
- Các mô tả `returns` không phải output schema đầy đủ; nhiều write có returns rỗng. Một sai lệch cụ thể: loyalty.get_points ghi points[] nhưng mã trả programs[] chứa rewards. Ở inference tương lai phải đọc kết quả thực, không đoán cấu trúc từ returns.
- Validator không thực thi hết ràng buộc object lồng nhau và x-ref. Phải giữ đúng hợp đồng items của food_delivery.place_order, enum và nguồn ID. `ok:true` không chứng minh hoàn tất: có thể `done:false`, không có kết quả hoặc thiếu số dư.
- Checkout lấy **toàn bộ giỏ hiện có**, làm trống giỏ; add_to_cart cộng số lượng nếu đã có. Không có get_cart/remove_cart trong hai catalog; không giả khả năng sửa giỏ. payment=ewallet/bank trên order không tự chứng minh giao dịch ví/ngân hàng tương ứng.
- Không có tool nạp tiền vào ví dù mô tả app nói “nạp”; reminders.create không có trigger vị trí; home_automation chỉ hẹn giờ bật/tắt mỗi ngày. Không triển khai workflow dựa trên mô tả app rộng hơn schema.
- S15/S23 cần người review ánh xạ tên/đơn vị/địa chỉ/khẩu phần/giờ. S18/S19 và S04/S11 có nhiều nhánh; cần review độ rộng, ưu tiên chỉ retrieve đoạn nhánh cần dùng thay vì tách mỗi tool thành một skill.
- Năng lực model và giới hạn 16 bước / soft 28 s / hard 30 s là ngữ cảnh và cấu hình thiết kế đã đọc, chưa kiểm checkpoint fine-tuned thực hoặc đo GPU. Chưa chứng minh tổng tham số thực, quality gain, latency gain hoặc an toàn token budget của retrieval.
- Renderer hiện tại chỉ đưa request/context/history vào input: chưa có điểm nhập skill hoạt động. Thêm metadata skill không tự ảnh hưởng inference. Mọi tích hợp renderer/prompt phải là thay đổi sau review, có version/fingerprint và kiểm native protocol/KV.

## I. Ưu tiên và kiến trúc đề nghị

1. D04/D03: S06, S05 cho phân giải người nhận và ID bản ghi; bao phủ mẫu lỗi tên/ID/x-one-of, có tool chung giữa hai split.
2. D01/D05/D10/D09: S01, S08, S09, S10, S14, S13 cho thiết bị, nguồn tiền, merchant/menu và vòng đời booking. Giữ nhánh đọc có điều kiện, phân biệt lỗi schema và no-op.
3. D11: S16 và sau đó S17 do Public Test có giỏ và hậu mãi mới; cần review toàn giỏ, cộng quantity và status trước mutation.
4. Sau đó S21/S22/S24 để ghép miền bằng các đoạn ngắn. S15/S23 và S20 ở P3, cần xác minh riêng trước runtime. Thứ tự này dựa rủi ro cấu trúc catalog, chưa phải xếp hạng theo phân bố intent hoặc kết quả benchmark.

Khuyến nghị **một planner tổng quát + thư viện hướng dẫn theo nhánh nhiệm vụ + retrieval từ khoá/luật offline CPU**. Tên tool, cụm intent và metadata nhiều miền hỗ trợ chọn 2–4 đoạn trong budget dự kiến; giữ nguyên toàn bộ eligible tools, native Qwen calling và một ToolEnv. Đóng băng hướng dẫn đầu mẫu để prefix ổn định cho cơ chế KV hiện có; không hứa speedup. TF-IDF/BM25 là bước thử sau nếu cần; không thêm model lớn hoặc external API. Chi tiết, trọng số/budget giả thuyết và kế hoạch đo tại [skill-retrieval-proposal.md](skill-retrieval-proposal.md).

## Kiểm tra tài liệu

Kiểm tĩnh bằng Node.js, chỉ đọc catalog/mã và sáu Markdown:

- Đếm 147/122 entry, giao 88, hợp 181; so sánh mọi entry chung; so sâu catalog repo với dataset, đối chiếu module app.
- Parse schema JSON trong inventory và so sâu với cả 181 tool; kiểm mô tả, required/optional, nguồn catalog và method tương ứng.
- Đối chiếu 17 miền phủ đủ 181 tool đúng một lần, không miền rỗng; 37 workflow và 24 skill ID duy nhất; mọi tool được nhắc trong workflow/skill có trong catalog; kiểm trùng required tool sets.
- Kiểm liên kết file/anchor nội bộ, schema references và các bảng summary; `git diff --check`; đối chiếu diff từ base chỉ gồm sáu báo cáo dưới đây.

Không chạy test runtime/model vì không thay mã thực thi. Các kiểm tra trên xác minh tính nhất quán tài liệu, không chứng minh workflow chạy thành công hay retrieval cải thiện điểm.

## Các báo cáo được bàn giao

- [tool-catalog-inventory.md](tool-catalog-inventory.md)
- [business-domains.md](business-domains.md)
- [workflow-analysis.md](workflow-analysis.md)
- [candidate-skills.md](candidate-skills.md)
- [skill-retrieval-proposal.md](skill-retrieval-proposal.md)
- [REVIEW-SUMMARY.md](REVIEW-SUMMARY.md)

Điểm dừng: **chờ con người review tài liệu và phạm vi skill; không tiếp tục implementation**.
