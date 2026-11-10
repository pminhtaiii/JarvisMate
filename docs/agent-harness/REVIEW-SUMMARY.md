# Tổng hợp review Agent Skills — phân nhánh nhiệm vụ

Rà soát ngày **10/11/2026** trên `codex/010-tool-domain-skill-analysis`, base `dfbaa0416a45c25e402c98594ea63f5c220f8042`. Chỉ sáu báo cáo Markdown; không thay Planner, KV cache, ToolEnv, schema catalog hoặc model. Không triển khai Skill Library/retrieval, không chạy GPU/inference.

## A. Inventory giữ nguyên

Train: **147 tool / 46 app**. Public Test: **122 tool / 36 app**. Giao: **88 tool**; chỉ Train: **59**; chỉ Public Test: **34**. Hợp: **181 tool / 57 app**.

Giữ đủ **181 tool và toàn bộ schema**, gồm mô tả/required/optional/type/enum/constraint/returns và nguồn. 88 tool chung vẫn không khác entry; 59 chỉ Train, 34 chỉ Public Test. Catalog repo khớp JSON với dữ liệu gốc tại train+public_test; 25 module app chung khớp sau chuẩn hoá xuống dòng. Các hash nguồn và JSON Pointer giữ nguyên tại [inventory](tool-catalog-inventory.md).

## B–C. 16 miền nghiệp vụ + 1 năng lực hệ thống

**D01–D16 có 180 tool nghiệp vụ; SC01 có 1 tool hệ thống = 181.** D17 cũ chuyển thành SC01, không đếm như business domain. Không xoá sys.ask_missing_info khỏi inventory hoặc eligible tools.

| Miền | Mô tả | Số tool | Tên tool |
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

| Năng lực dùng chung | Tool | Hợp đồng |
| --- | --- | --- |
| [SC01](business-domains.md#sc01), trước đây D17 | sys.ask_missing_info | tool_name và params theo catalog; dùng cho dữ kiện bắt buộc còn thiếu, không mở tool bị cấm; kết thúc waiting_for_user |

W36 và C02 tham chiếu SC01. Năng lực này không được tính thêm thành skill hoặc nhánh.

## D. 37 workflow giữ nguyên

Giữ **W01–W37**, nguyên evidence E/S/H và dependency nghiệp vụ; chỉ đổi nhãn D17 của W36 sang SC01, sửa tên viết tắt robot.start thành tên thật robot_vacuum.start. Không thêm/xoá workflow. Bảng 82 x-ref giữ nguyên. [workflow-analysis.md](workflow-analysis.md) thêm ánh xạ điều hướng từ workflow sang nhánh, không biến các nhánh thay thế thành chuỗi bắt buộc.

## E–F. 24 kỹ năng ứng viên / 80 nhánh nhiệm vụ

Giữ 24 ID cha S01–S24 để truy vết. **80 branch_id là đơn vị retrieval**, cha chỉ là chỉ mục. Có **63 E, 13 S, 4 H**; E/S đều chưa được duyệt runtime hay benchmark. H của S15.B01/B02 và S23.B01/B02 bị loại khỏi retrieval runtime dự kiến cho tới khi xác minh, không phải skill confirmed. Số 80 bao gồm 4 nhánh H nghiên cứu; 76 nhánh E/S chỉ là ứng viên bước review tiếp.

| Skill ID | Tên nhóm kỹ năng | Miền | Số nhánh | Nhánh có thể retrieve sau review |
| --- | --- | --- | --- | --- |
| S01 | Điều khiển nhà theo đối tượng | D01 | 2 | [S01.B01](candidate-skills.md#s01-b01), [S01.B02](candidate-skills.md#s01-b02) |
| S02 | Điều phối chu trình gia dụng | D01 | 3 | [S02.B01](candidate-skills.md#s02-b01), [S02.B02](candidate-skills.md#s02-b02), [S02.B03](candidate-skills.md#s02-b03) |
| S03 | Quản lý quy tắc thiết bị hằng ngày | D01 | 2 | [S03.B01](candidate-skills.md#s03-b01), [S03.B02](candidate-skills.md#s03-b02) |
| S04 | Xử lý an ninh và quyền ra vào | D02 | 3 | [S04.B01](candidate-skills.md#s04-b01), [S04.B02](candidate-skills.md#s04-b02), [S04.B03](candidate-skills.md#s04-b03) |
| S05 | Thay đổi bản ghi cá nhân đang có | D03 | 5 | [S05.B01](candidate-skills.md#s05-b01), [S05.B02](candidate-skills.md#s05-b02), [S05.B03](candidate-skills.md#s05-b03), [S05.B04](candidate-skills.md#s05-b04), [S05.B05](candidate-skills.md#s05-b05) |
| S06 | Phân giải người nhận và kênh liên lạc | D04 | 6 | [S06.B01](candidate-skills.md#s06-b01), [S06.B02](candidate-skills.md#s06-b02), [S06.B03](candidate-skills.md#s06-b03), [S06.B04](candidate-skills.md#s06-b04), [S06.B05](candidate-skills.md#s06-b05), [S06.B06](candidate-skills.md#s06-b06) |
| S07 | Xử lý email theo nội dung | D04 | 3 | [S07.B01](candidate-skills.md#s07-b01), [S07.B02](candidate-skills.md#s07-b02), [S07.B03](candidate-skills.md#s07-b03) |
| S08 | Chọn tài khoản và thực hiện giao dịch | D05 | 2 | [S08.B01](candidate-skills.md#s08-b01), [S08.B02](candidate-skills.md#s08-b02) |
| S09 | Thanh toán ví theo đúng đối tượng | D05, D04, D10 | 3 | [S09.B01](candidate-skills.md#s09-b01), [S09.B02](candidate-skills.md#s09-b02), [S09.B03](candidate-skills.md#s09-b03) |
| S10 | Chọn và thanh toán hoá đơn | D05 | 1 | [S10.B01](candidate-skills.md#s10-b01) |
| S11 | Quản lý ưu đãi và gói định kỳ | D06 | 2 | [S11.B01](candidate-skills.md#s11-b01), [S11.B02](candidate-skills.md#s11-b02) |
| S12 | Chọn điểm đến và dịch vụ di chuyển | D08 | 6 | [S12.B01](candidate-skills.md#s12-b01), [S12.B02](candidate-skills.md#s12-b02), [S12.B03](candidate-skills.md#s12-b03), [S12.B04](candidate-skills.md#s12-b04), [S12.B05](candidate-skills.md#s12-b05), [S12.B06](candidate-skills.md#s12-b06) |
| S13 | Quản lý vé liên tỉnh theo vòng đời | D09 | 5 | [S13.B01](candidate-skills.md#s13-b01), [S13.B02](candidate-skills.md#s13-b02), [S13.B03](candidate-skills.md#s13-b03), [S13.B04](candidate-skills.md#s13-b04), [S13.B05](candidate-skills.md#s13-b05) |
| S14 | Chọn quán, món và quản lý đơn ăn | D10 | 2 | [S14.B01](candidate-skills.md#s14-b01), [S14.B02](candidate-skills.md#s14-b02) |
| S15 | Chuẩn bị nguyên liệu theo công thức | D10, D11 | 2 | [S15.B01](candidate-skills.md#s15-b01), [S15.B02](candidate-skills.md#s15-b02) |
| S16 | Mua hàng theo giỏ | D11 | 2 | [S16.B01](candidate-skills.md#s16-b01), [S16.B02](candidate-skills.md#s16-b02) |
| S17 | Xử lý đơn hàng và giao nhận | D11 | 3 | [S17.B01](candidate-skills.md#s17-b01), [S17.B02](candidate-skills.md#s17-b02), [S17.B03](candidate-skills.md#s17-b03) |
| S18 | Chọn và lưu nội dung giải trí | D12 | 9 | [S18.B01](candidate-skills.md#s18-b01), [S18.B02](candidate-skills.md#s18-b02), [S18.B03](candidate-skills.md#s18-b03), [S18.B04](candidate-skills.md#s18-b04), [S18.B05](candidate-skills.md#s18-b05), [S18.B06](candidate-skills.md#s18-b06), [S18.B07](candidate-skills.md#s18-b07), [S18.B08](candidate-skills.md#s18-b08), [S18.B09](candidate-skills.md#s18-b09) |
| S19 | Ghi nhận sức khoẻ và học tập theo đối tượng | D13, D14 | 8 | [S19.B01](candidate-skills.md#s19-b01), [S19.B02](candidate-skills.md#s19-b02), [S19.B03](candidate-skills.md#s19-b03), [S19.B04](candidate-skills.md#s19-b04), [S19.B05](candidate-skills.md#s19-b05), [S19.B06](candidate-skills.md#s19-b06), [S19.B07](candidate-skills.md#s19-b07), [S19.B08](candidate-skills.md#s19-b08) |
| S20 | Thực hiện điều kiện chứng khoán mô phỏng | D16 | 2 | [S20.B01](candidate-skills.md#s20-b01), [S20.B02](candidate-skills.md#s20-b02) |
| S21 | Thông báo thông tin từ lịch | D03, D04 | 2 | [S21.B01](candidate-skills.md#s21-b01), [S21.B02](candidate-skills.md#s21-b02) |
| S22 | Điều khiển nhà theo điều kiện hiện tại | D07, D01 | 2 | [S22.B01](candidate-skills.md#s22-b01), [S22.B02](candidate-skills.md#s22-b02) |
| S23 | Lập giờ nhắc/đón theo chuyến bay | D09, D08, D03 | 2 | [S23.B01](candidate-skills.md#s23-b01), [S23.B02](candidate-skills.md#s23-b02) |
| S24 | Dịch rồi gửi đúng kênh | D15, D04 | 3 | [S24.B01](candidate-skills.md#s24-b01), [S24.B02](candidate-skills.md#s24-b02), [S24.B03](candidate-skills.md#s24-b03) |


Tool action bắt buộc, OR alternatives, reader/phụ trợ có điều kiện, tham số chính xác, dependency, trigger, condition, completion, evidence và common references đều ở [candidate-skills.md](candidate-skills.md). Không dùng một tập tool hợp của cha làm điều kiện AND. Chỉ tên tool có trong installed_apps[app].tools của mẫu cộng sys mới eligible; việc tool có trong catalog hoặc app có cài chưa đủ.

| Skill ưu tiên | Tách/tổ chức lại | Số nhánh |
| --- | --- | --- |
| S11 | Đổi thưởng; huỷ gói — hai nhiệm vụ riêng, không retrieve cùng nhau mặc định. | 2 |
| S12 | Đặt xe, huỷ xe, thuê xe đạp, đặt đỗ, kết thúc đỗ, xem chuyến công cộng. | 6 |
| S18 | Phát nhạc, sửa playlist, nghe tập, nghe đài, subscribe, queue, chuyển kênh, ghi TV, đặt vé sự kiện. | 9 |
| S19 | Ghi thuốc, bỏ lịch thuốc, log habit, fitness goal theo điều kiện, enroll, hẹn học, ghi tiến độ, giữ sách. | 8 |
| 20 nhóm còn lại | Chuẩn hoá hợp đồng branch; giữ workflow, tách kênh/đối tượng/giai đoạn và H gate. | 55 |


S07.B03 và S19.B04 ghi S cho phần ánh xạ nội dung/tính mục tiêu, dù workflow cha có các cạnh E. Không coi tool thành phần thật là bằng chứng đủ cho phối hợp H. Các nhánh một call đủ dữ kiện không cần dedicated skill riêng; tồn tại 37 workflow không yêu cầu mỗi workflow/tool phải có một skill.

## G. Retrieval nhiều mục tiêu và tái sử dụng

| Request minh hoạ từ catalog | Nhánh ứng viên | Phần loại khỏi hướng dẫn |
| --- | --- | --- |
| Huỷ gói rồi phát playlist | S11.B02 + S18.B01 | Đổi điểm, podcast, TV |
| Ghi đã học N phút rồi nghe podcast | S19.B07 + S18.B03 | Thuốc, habit, subscribe, queue |
| Đọc lịch rồi nhắn mẹ | S21.B01 + C05 | Không chạy S06.B02 lần nữa cho cùng tin |
| Dịch rồi gửi vào nhóm | S24.B02 + C05 | Không lấy thêm email/SMS |
| Nếu thời tiết đạt điều kiện thì chỉnh thiết bị | S22.B01, dùng phần phân giải S01.B01 | Không gọi setter hai lần hoặc tạo automation tương lai |
| Công thức/tủ bếp → mua phần thiếu | S15.B01/B02 vẫn H | Không lọt gate bằng cách ghép với nhánh giỏ E |
| Vé bay/ETA → nhắc hoặc đặt xe | S23.B01/B02 vẫn H | Chưa đủ ánh xạ địa chỉ/giờ đệm để coi confirmed |

Ví dụ không phải thống kê tần suất test. Một mục tiêu có thể nhiều miền, nhiều mục tiêu có thể cùng miền. Xếp hạng từng nhánh theo hành động/đối tượng; domain chỉ là tín hiệu phụ. ASR dùng bản sao NFC/có dấu/bỏ dấu, alias cụm từ và character n-gram/fuzzy có giới hạn; không sửa ID/số/enum theo phỏng đoán, không làm mất phủ định hoặc điều kiện. Mơ hồ không đủ để tự kích hoạt write.

C01–C06 là các hướng dẫn tái sử dụng về eligibility, resolve/missing, condition/completion, thời gian, recipient và giỏ. Chèn mỗi reference cần thiết một lần. Không dedup chỉ bằng tên tool vì hai mục tiêu có thể yêu cầu hai tin; phân quyền sở hữu action theo mục tiêu/đích để tránh gửi, add hoặc checkout hai lần.

Đề xuất giữ một planner tổng quát, chọn nhánh offline CPU và toàn bộ native eligible schemas; chốt hướng dẫn đầu mẫu để tương thích kiểm token-prefix KV hiện có. Renderer hiện chưa có điểm nhập skill hoạt động. Nội dung này không sửa prompt/renderer/KV hoặc tự chạy nhánh. Budget 600–1.000 token và retrieval p95 <5 ms chỉ là mốc dự kiến chưa đo. Chi tiết tại [skill-retrieval-proposal.md](skill-retrieval-proposal.md).

## H. Bất định còn cần review

- Bốn nhánh H: lượng nguyên liệu/đơn vị/khẩu phần/quy cách SKU (S15), địa chỉ sân bay/timezone/giờ đệm (S23). Không nâng thành confirmed; cần bằng chứng mới trước thay gate.
- 13 nhánh S suy luận phối hợp, gồm nội dung lịch/dịch/nháp và điều kiện hoạt động/giá/thời tiết; cần review ánh xạ output→input và điều kiện hoàn tất. E chỉ xác nhận tĩnh, không chứng minh end-to-end hoặc mọi app đồng cài.
- Catalog private test chưa được kiểm. Không đọc input JSONL, gold labels, dự đoán, audio hoặc state ẩn để thiết kế nhánh; chưa có số liệu intent/ASR/đồng cài.
- returns là mô tả tóm tắt, nhiều tool write để trống; loyalty.get_points có chênh points[]/programs[] giữa catalog và mã. Dựa output thật và mã được link ở workflow; ok:true không đủ hoàn tất.
- Giỏ cũ, không có get_cart/remove_cart, cộng quantity và checkout toàn giỏ cần xử lý theo C06; không dùng sys để hỏi một slot optional tự tạo hoặc mở khả năng tool không có. payment trên đơn không chứng minh trừ tiền ví/ngân hàng tương ứng.
- 80 nhánh là đơn vị review; cần kiểm chi phí metadata/prompt, branch recall/precision, ASR ambiguity, missing goals và duplicate actions. Chưa đo latency/quality, chưa có runtime library hoặc model/GPU run. Tổng tham số checkpoint thực chưa được kiểm lại.

## I. Ưu tiên tiếp theo sau review

Tài liệu ưu tiên tách S11/S12/S18/S19 đã hoàn tất. Triển khai tương lai có thể bắt đầu với nhánh ID/mutation rõ của S05/S06/S01, tài khoản/merchant/hoá đơn S08–S10, menu/booking/giỏ S13/S14/S16; chọn nhánh có ích dựa lỗi Train Validation đo được. Các nhánh H giữ ngoài runtime. Không dùng bảng ưu tiên cấu trúc này như kết quả chất lượng thực nghiệm.

## Kiểm tra và phạm vi thay đổi

Kiểm tĩnh từ base chỉ đọc catalog, mã và Markdown: 181 entry/schema inventory không đổi; coverage 180 nghiệp vụ + 1 SC01; 37 workflow ID/evidence/tool lists giữ nguyên; 24 parent / 80 branch IDs duy nhất; mọi tên tool và các required/optional/x-one-of trích ở branch khớp catalog; S15/S23 không mất H; bảng summary, anchors và links nội bộ nhất quán. Đối chiếu hai catalog repo với dataset, kiểm module/method tương ứng và schema references. git diff --check và diff từ base chỉ gồm sáu báo cáo. Các phép kiểm này không chứng minh quality/latency hoặc workflow chạy thành công.

## Báo cáo bàn giao

- [tool-catalog-inventory.md](tool-catalog-inventory.md)
- [business-domains.md](business-domains.md)
- [workflow-analysis.md](workflow-analysis.md)
- [candidate-skills.md](candidate-skills.md)
- [skill-retrieval-proposal.md](skill-retrieval-proposal.md)
- [REVIEW-SUMMARY.md](REVIEW-SUMMARY.md)

Dừng ở tài liệu để con người review; không tiếp tục implementation.
