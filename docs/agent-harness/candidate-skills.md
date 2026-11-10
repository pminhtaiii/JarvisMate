# Thư viện Agent Skill ứng viên

Ngày phân tích: 10/11/2026. Base: `e216ad5115229598149ca8c4e3f43554ce065268` (nhánh `codex/009-cross-step-kv-cache`). Chỉ nghiên cứu tĩnh; không chạy tool trên mẫu, GPU, inference, retrieval hay skill thực thi.

Đề xuất **24 skill ứng viên** là hướng dẫn nhiệm vụ có thể tái sử dụng; chưa phải file `SKILL.md`, prompt hay cấu hình thực thi. Thư viện có cả ứng viên cần review, không phải cam kết triển khai cả 24.

## Cách hiểu danh sách tool

“Bắt buộc theo nhánh” là hợp tool ở các nhánh được mô tả; **không yêu cầu mọi tool cùng có mặt hay luôn được gọi**. Khi chọn nhánh, thao tác đích bắt buộc; bước đọc ID chỉ cần khi dữ kiện thiếu, trừ quy tắc tường minh trong workflow. “Tuỳ chọn” là phụ trợ có điều kiện; khi nhánh cần dữ liệu ấy mà chưa có, tool đọc tương ứng trở thành cần thiết. `sys.ask_missing_info` là công cụ meta chung theo W36, không sao chép vào mọi danh sách.

Mỗi skill kế thừa nguyên văn các trường workflow được liên kết: thứ tự, dữ liệu trung gian, điều kiện, missing và completion. Các trường này cũng được nhắc riêng dưới từng skill để review được độc lập. Không dùng tool đọc như nghi thức bắt buộc vì extra call ảnh hưởng điểm và thời gian.

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

<a id="s01"></a>

## S01 — Điều khiển nhà theo đối tượng

- skill_id: `S01`; miền: D01; ưu tiên: P1.
- Mô tả: Điều phối điều khiển thiết bị theo phòng/tầng; chạy cảnh nhà đã lưu theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Tắt đèn tầng hai; chỉnh điều hoà; chạy cảnh đi ngủ.
- Tool bắt buộc theo nhánh: `smart_home.get_status`, `smart_home.light_set`, `smart_home.fan_set`, `smart_home.climate_set`, `smart_home.switch_set`, `smart_home.scene_run`.
- Tool phụ trợ: Không có.
- Tiền điều kiện: Có bộ lọc/ý định chọn thiết bị hoặc cảnh; chỉ cần setter ứng với yêu cầu.
- Workflow khuyến nghị: [W01](workflow-analysis.md#w01), [W02](workflow-analysis.md#w02). get_status với bộ lọc cần thiết → chọn devices[] → gọi setter đúng type cho từng thiết bị được yêu cầu. get_status không lọc → chọn scenes[] → scene_run.
- Hoàn tất: Kết quả setter phản ánh các thuộc tính cần đổi; done:false không đạt. Kết quả scene_run thành công theo nội dung trả về.
- Thông tin thiếu: Thiếu device_id sau tra cứu hoặc thiếu mode thì hỏi đúng tham số của setter. Thiếu scene_id hoặc không phân biệt được cảnh → hỏi scene_id. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Không biến cảnh đã lưu thành một chuỗi setter tự tạo; get_status không lọc cho scenes.
- Chứng cứ: mức E tại workflow trên; [`smart_home.get_status`](tool-catalog-inventory.md#tool-smart_home-get_status), [`smart_home.light_set`](tool-catalog-inventory.md#tool-smart_home-light_set), [`smart_home.fan_set`](tool-catalog-inventory.md#tool-smart_home-fan_set), [`smart_home.climate_set`](tool-catalog-inventory.md#tool-smart_home-climate_set), [`smart_home.switch_set`](tool-catalog-inventory.md#tool-smart_home-switch_set), [`smart_home.scene_run`](tool-catalog-inventory.md#tool-smart_home-scene_run). Mã và nguồn output được liên kết ở từng workflow.

<a id="s02"></a>

## S02 — Điều phối chu trình gia dụng

- skill_id: `S02`; miền: D01; ưu tiên: P2.
- Mô tả: Điều phối chạy robot hoặc chu trình gia dụng theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Hút bụi một phòng; đổi/chạy chu trình giặt.
- Tool bắt buộc theo nhánh: `robot_vacuum.get_status`, `robot_vacuum.start`, `appliances.list`, `appliances.start_cycle`.
- Tool phụ trợ: `robot_vacuum.stop`, `appliances.stop`.
- Tiền điều kiện: Có app nhánh robot hoặc gia dụng; xác định khu vực/thiết bị/chu trình.
- Workflow khuyến nghị: [W03](workflow-analysis.md#w03). Nhánh robot: get_status → start khi cần kiểm tra phòng/pin. Nhánh gia dụng: list → chọn appliance/cycle → start_cycle; stop chỉ khi cần theo yêu cầu.
- Hoàn tất: Robot cleaning/current_job hoặc appliance running/scheduled đúng yêu cầu.
- Thông tin thiếu: Hỏi appliance_id/cycle nếu chưa xác định; robot.start không có required nên không tự đặt trường bắt buộc mới. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Các nhánh độc lập; chỉ stop chu trình hiện tại nếu yêu cầu cho phép; không tạo skill riêng cho stop.
- Chứng cứ: mức E tại workflow trên; [`robot_vacuum.get_status`](tool-catalog-inventory.md#tool-robot_vacuum-get_status), [`robot_vacuum.start`](tool-catalog-inventory.md#tool-robot_vacuum-start), [`appliances.list`](tool-catalog-inventory.md#tool-appliances-list), [`appliances.start_cycle`](tool-catalog-inventory.md#tool-appliances-start_cycle), [`robot_vacuum.stop`](tool-catalog-inventory.md#tool-robot_vacuum-stop), [`appliances.stop`](tool-catalog-inventory.md#tool-appliances-stop). Mã và nguồn output được liên kết ở từng workflow.

<a id="s03"></a>

## S03 — Quản lý quy tắc thiết bị hằng ngày

- skill_id: `S03`; miền: D01; ưu tiên: P2.
- Mô tả: Điều phối lập/xoá quy tắc thiết bị hằng ngày theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Hằng ngày bật đèn lúc 19 giờ; xoá lịch bật đèn.
- Tool bắt buộc theo nhánh: `smart_home.get_status`, `home_automation.create_rule`, `home_automation.list_rules`, `home_automation.delete_rule`.
- Tool phụ trợ: Không có.
- Tiền điều kiện: Train; nhánh tạo cần device_id/action/time, nhánh xoá cần rule_id.
- Workflow khuyến nghị: [W04](workflow-analysis.md#w04). Tạo: get_status → chọn device_id → create_rule; xoá: list_rules → delete_rule.
- Hoàn tất: Trả rule với enabled hoặc xoá đúng rule.
- Thông tin thiếu: Thiếu action/time/device_id hoặc rule_id chưa phân giải → ask_missing_info. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Chỉ hẹn giờ on/off mỗi ngày; không nhận trigger thời tiết/cảm biến.
- Chứng cứ: mức E tại workflow trên; [`smart_home.get_status`](tool-catalog-inventory.md#tool-smart_home-get_status), [`home_automation.create_rule`](tool-catalog-inventory.md#tool-home_automation-create_rule), [`home_automation.list_rules`](tool-catalog-inventory.md#tool-home_automation-list_rules), [`home_automation.delete_rule`](tool-catalog-inventory.md#tool-home_automation-delete_rule). Mã và nguồn output được liên kết ở từng workflow.

<a id="s04"></a>

## S04 — Xử lý an ninh và quyền ra vào

- skill_id: `S04`; miền: D02; ưu tiên: P2.
- Mô tả: Điều phối xử lý cảnh báo và khoá cửa theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Đánh dấu cảnh báo đã xem; khoá cửa sau; tạo mã khách hết hạn tối nay.
- Tool bắt buộc theo nhánh: `home_security.list_alerts`, `home_security.acknowledge_alert`, `door_lock.list_locks`, `door_lock.set_lock`, `door_lock.grant_guest_code`.
- Tool phụ trợ: `home_security.get_camera`, `home_security.arm`.
- Tiền điều kiện: Train; xác định đối tượng và hành động mong muốn.
- Workflow khuyến nghị: [W06](workflow-analysis.md#w06). Nhánh cảnh báo: list_alerts → acknowledge_alert. Nhánh khoá: list_locks → set_lock hoặc grant_guest_code. get_camera/arm chỉ khi có ý định tương ứng.
- Hoàn tất: Kết quả thay đổi đúng khoá/cảnh báo hoặc guest_code được trả.
- Thông tin thiếu: Thiếu lock_id/valid_until, alert_id hoặc mode chưa xác định → hỏi tool đích. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Camera, chế độ bảo vệ và khoá là các nhánh; không tự gửi mã khách qua messaging.
- Chứng cứ: mức E tại workflow trên; [`home_security.list_alerts`](tool-catalog-inventory.md#tool-home_security-list_alerts), [`home_security.acknowledge_alert`](tool-catalog-inventory.md#tool-home_security-acknowledge_alert), [`door_lock.list_locks`](tool-catalog-inventory.md#tool-door_lock-list_locks), [`door_lock.set_lock`](tool-catalog-inventory.md#tool-door_lock-set_lock), [`door_lock.grant_guest_code`](tool-catalog-inventory.md#tool-door_lock-grant_guest_code), [`home_security.get_camera`](tool-catalog-inventory.md#tool-home_security-get_camera), [`home_security.arm`](tool-catalog-inventory.md#tool-home_security-arm). Mã và nguồn output được liên kết ở từng workflow.

<a id="s05"></a>

## S05 — Thay đổi bản ghi cá nhân đang có

- skill_id: `S05`; miền: D03; ưu tiên: P1.
- Mô tả: Điều phối sửa/hoàn thành bản ghi cá nhân theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Dời cuộc hẹn; xoá báo thức; hoàn thành việc; nối ghi chú.
- Tool bắt buộc theo nhánh: `alarm.list`, `alarm.update`, `alarm.delete`, `reminders.list`, `reminders.complete`, `reminders.delete`, `calendar.list_events`, `calendar.update_event`, `calendar.cancel_event`, `notes.list`, `notes.append`, `tasks.list`, `tasks.complete`.
- Tool phụ trợ: Không có.
- Tiền điều kiện: Có loại bản ghi và tiêu chí nhận diện; chỉ nhánh app tương ứng bắt buộc.
- Workflow khuyến nghị: [W07](workflow-analysis.md#w07). Chọn app theo loại đối tượng → list phù hợp → lọc bản ghi → update/delete/complete/append.
- Hoàn tất: Kết quả ghi/xoá/hoàn thành cho đúng bản ghi.
- Thông tin thiếu: ID còn mơ hồ hoặc thiếu content khi notes.append → hỏi đúng tham số. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Một mẫu hướng dẫn list→select→mutate dùng chung; không tách skill cho từng app/CRUD; không list cho create mới đủ dữ kiện.
- Chứng cứ: mức E tại workflow trên; [`alarm.list`](tool-catalog-inventory.md#tool-alarm-list), [`alarm.update`](tool-catalog-inventory.md#tool-alarm-update), [`alarm.delete`](tool-catalog-inventory.md#tool-alarm-delete), [`reminders.list`](tool-catalog-inventory.md#tool-reminders-list), [`reminders.complete`](tool-catalog-inventory.md#tool-reminders-complete), [`reminders.delete`](tool-catalog-inventory.md#tool-reminders-delete), [`calendar.list_events`](tool-catalog-inventory.md#tool-calendar-list_events), [`calendar.update_event`](tool-catalog-inventory.md#tool-calendar-update_event), [`calendar.cancel_event`](tool-catalog-inventory.md#tool-calendar-cancel_event), [`notes.list`](tool-catalog-inventory.md#tool-notes-list), [`notes.append`](tool-catalog-inventory.md#tool-notes-append), [`tasks.list`](tool-catalog-inventory.md#tool-tasks-list), [`tasks.complete`](tool-catalog-inventory.md#tool-tasks-complete). Mã và nguồn output được liên kết ở từng workflow.

<a id="s06"></a>

## S06 — Phân giải người nhận và kênh liên lạc

- skill_id: `S06`; miền: D04; ưu tiên: P1.
- Mô tả: Điều phối tìm người rồi gọi, nhắn hoặc sửa danh bạ; chọn cuộc chat và thao tác ott theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Nhắn mẹ; gọi sếp; gửi vị trí vào nhóm; sửa email của một người.
- Tool bắt buộc theo nhánh: `contacts.search`, `phone.call`, `sms.send`, `contacts.update`, `chat_ott.list_chats`, `chat_ott.send_message`, `chat_ott.send_location`, `chat_ott.call`.
- Tool phụ trợ: `contacts.get`, `chat_ott.read_chat`, `email.send`.
- Tiền điều kiện: Có kênh và hành động; chỉ cần search khi đích chưa được phân giải.
- Workflow khuyến nghị: [W08](workflow-analysis.md#w08), [W09](workflow-analysis.md#w09). Nếu chỉ có tên/quan hệ: search → chọn contact; get chỉ khi cần thêm chi tiết → call/send/update theo yêu cầu. list_chats → chọn chat_id → read_chat nếu ý định cần nội dung → send_message/send_location/call.
- Hoàn tất: Có kết quả cuộc gọi/tin gửi hoặc cập nhật liên hệ. Tin/vị trí/cuộc gọi được ghi đúng chat.
- Thông tin thiếu: Thiếu một nhánh x-one-of recipient hoặc thiếu nội dung bắt buộc → hỏi theo schema tool đích. Thiếu chat_id/content cần hỏi; không cần hỏi tọa độ cho send_location. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: contact_id, chat_id, phone_number và phone khác nhau; không tra danh bạ khi số người nhận đã đủ rõ.
- Chứng cứ: mức E tại workflow trên; [`contacts.search`](tool-catalog-inventory.md#tool-contacts-search), [`phone.call`](tool-catalog-inventory.md#tool-phone-call), [`sms.send`](tool-catalog-inventory.md#tool-sms-send), [`contacts.update`](tool-catalog-inventory.md#tool-contacts-update), [`chat_ott.list_chats`](tool-catalog-inventory.md#tool-chat_ott-list_chats), [`chat_ott.send_message`](tool-catalog-inventory.md#tool-chat_ott-send_message), [`chat_ott.send_location`](tool-catalog-inventory.md#tool-chat_ott-send_location), [`chat_ott.call`](tool-catalog-inventory.md#tool-chat_ott-call), [`contacts.get`](tool-catalog-inventory.md#tool-contacts-get), [`chat_ott.read_chat`](tool-catalog-inventory.md#tool-chat_ott-read_chat), [`email.send`](tool-catalog-inventory.md#tool-email-send). Mã và nguồn output được liên kết ở từng workflow.

<a id="s07"></a>

## S07 — Xử lý email theo nội dung

- skill_id: `S07`; miền: D04; ưu tiên: P2.
- Mô tả: Điều phối đọc và xử lý email có sẵn theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Trả lời thư gần nhất của đồng nghiệp; lưu trữ thư; soạn nháp trả lời.
- Tool bắt buộc theo nhánh: `email.list`, `email.reply`, `email.archive`, `email.create_draft`.
- Tool phụ trợ: `email.read`, `contacts.search`.
- Tiền điều kiện: Có tiêu chí thư hoặc dữ kiện nháp.
- Workflow khuyến nghị: [W10](workflow-analysis.md#w10). list → chọn email_id → read nếu nội dung cần thiết → reply hoặc archive; create_draft là nhánh riêng khi người dùng chỉ muốn nháp.
- Hoàn tất: Reply/archive đúng email hoặc draft được trả, theo ý định.
- Thông tin thiếu: Thiếu email_id/body/action hoặc trường nháp → hỏi tool đúng. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Đọc chỉ khi cần nội dung; create_draft khác send; không gộp xác nhận nháp thành gửi.
- Chứng cứ: mức E tại workflow trên; [`email.list`](tool-catalog-inventory.md#tool-email-list), [`email.reply`](tool-catalog-inventory.md#tool-email-reply), [`email.archive`](tool-catalog-inventory.md#tool-email-archive), [`email.create_draft`](tool-catalog-inventory.md#tool-email-create_draft), [`email.read`](tool-catalog-inventory.md#tool-email-read), [`contacts.search`](tool-catalog-inventory.md#tool-contacts-search). Mã và nguồn output được liên kết ở từng workflow.

<a id="s08"></a>

## S08 — Chọn tài khoản và thực hiện giao dịch

- skill_id: `S08`; miền: D05; ưu tiên: P1.
- Mô tả: Điều phối chuyển khoản hoặc gửi tiết kiệm theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Chuyển từ tài khoản lương cho người thụ hưởng; gửi tiết kiệm kỳ hạn đã chọn.
- Tool bắt buộc theo nhánh: `banking.get_balance`, `banking.transfer`, `banking.open_savings`.
- Tool phụ trợ: `banking.list_beneficiaries`.
- Tiền điều kiện: Có amount và ý định chuyển/gửi; tài khoản/đối tượng phải phân giải từ dữ kiện hợp lệ.
- Workflow khuyến nghị: [W12](workflow-analysis.md#w12). get_balance khi cần tài khoản/số dư; list_beneficiaries khi cần chọn người nhận → transfer. open_savings dùng tài khoản đã xác định.
- Hoàn tất: Kết quả giao dịch/tiết kiệm thành công, không phải chỉ ok:true.
- Thông tin thiếu: Thiếu from_account_id/beneficiary_id/amount/term_months sau đọc → hỏi đúng tool. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: list_beneficiaries cần ở nhánh transfer khi chưa có beneficiary_id; không thay bằng contact_id.
- Chứng cứ: mức E tại workflow trên; [`banking.get_balance`](tool-catalog-inventory.md#tool-banking-get_balance), [`banking.transfer`](tool-catalog-inventory.md#tool-banking-transfer), [`banking.open_savings`](tool-catalog-inventory.md#tool-banking-open_savings), [`banking.list_beneficiaries`](tool-catalog-inventory.md#tool-banking-list_beneficiaries). Mã và nguồn output được liên kết ở từng workflow.

<a id="s09"></a>

## S09 — Thanh toán ví theo đúng đối tượng

- skill_id: `S09`; miền: D05, D04, D10; ưu tiên: P1.
- Mô tả: Điều phối chuyển ví, nạp điện thoại hoặc trả qr theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Chuyển ví cho người thân; nạp điện thoại; trả QR tại quán.
- Tool bắt buộc theo nhánh: `ewallet.transfer`, `ewallet.topup_mobile`, `ewallet.pay_qr`.
- Tool phụ trợ: `ewallet.get_balance`, `contacts.search`, `food_delivery.list_restaurants`.
- Tiền điều kiện: Chọn một nhánh với recipient/merchant và amount.
- Workflow khuyến nghị: [W13](workflow-analysis.md#w13). Chọn nhánh: tên người → contacts.search → transfer/topup_mobile; tên quán → list_restaurants → pay_qr. get_balance khi người dùng yêu cầu/điều kiện số dư cần kiểm tra.
- Hoàn tất: Transaction và balance được trả; số dư thiếu gây done:false.
- Thông tin thiếu: Hỏi amount và recipient/merchant_id còn thiếu; không tự nạp thêm tiền ví vì không có tool đó. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: contacts.search bắt buộc theo nhánh khi chưa có người nhận; list_restaurants bắt buộc khi chưa có merchant_id; không gọi pay_qr chỉ vì vừa đặt món.
- Chứng cứ: mức E tại workflow trên; [`ewallet.transfer`](tool-catalog-inventory.md#tool-ewallet-transfer), [`ewallet.topup_mobile`](tool-catalog-inventory.md#tool-ewallet-topup_mobile), [`ewallet.pay_qr`](tool-catalog-inventory.md#tool-ewallet-pay_qr), [`ewallet.get_balance`](tool-catalog-inventory.md#tool-ewallet-get_balance), [`contacts.search`](tool-catalog-inventory.md#tool-contacts-search), [`food_delivery.list_restaurants`](tool-catalog-inventory.md#tool-food_delivery-list_restaurants). Mã và nguồn output được liên kết ở từng workflow.

<a id="s10"></a>

## S10 — Chọn và thanh toán hoá đơn

- skill_id: `S10`; miền: D05; ưu tiên: P1.
- Mô tả: Điều phối trả hoá đơn và kiểm tra nguồn ví theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Trả hoá đơn điện bằng ví; trả các hoá đơn đúng điều kiện đã nêu.
- Tool bắt buộc theo nhánh: `bill_payment.list_bills`, `bill_payment.pay`.
- Tool phụ trợ: `ewallet.get_balance`, `bill_payment.schedule_autopay`.
- Tiền điều kiện: Hoá đơn phù hợp và source đã xác định hoặc có thể hỏi.
- Workflow khuyến nghị: [W14](workflow-analysis.md#w14). list_bills → chọn bill_id → nếu điều kiện yêu cầu thì get_balance → pay với source; autopay là nhánh độc lập type/enabled.
- Hoàn tất: Bill paid:true; hoặc autopay đúng enabled.
- Thông tin thiếu: Thiếu bill_id/source hoặc type/enabled của autopay thì hỏi; không tự đổi nguồn tiền khi thiếu số dư. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Không thêm banking.transfer cho source=bank; autopay độc lập; không tự đổi nguồn khi thiếu số dư.
- Chứng cứ: mức E tại workflow trên; [`bill_payment.list_bills`](tool-catalog-inventory.md#tool-bill_payment-list_bills), [`bill_payment.pay`](tool-catalog-inventory.md#tool-bill_payment-pay), [`ewallet.get_balance`](tool-catalog-inventory.md#tool-ewallet-get_balance), [`bill_payment.schedule_autopay`](tool-catalog-inventory.md#tool-bill_payment-schedule_autopay). Mã và nguồn output được liên kết ở từng workflow.

<a id="s11"></a>

## S11 — Quản lý ưu đãi và gói định kỳ

- skill_id: `S11`; miền: D06; ưu tiên: P2.
- Mô tả: Điều phối đổi thưởng hoặc huỷ gói định kỳ theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Đổi điểm thành phần thưởng; huỷ gói có giá hoặc kỳ gia hạn phù hợp.
- Tool bắt buộc theo nhánh: `loyalty.get_points`, `loyalty.redeem`, `subscriptions.list`, `subscriptions.cancel`.
- Tool phụ trợ: `loyalty.list_vouchers`.
- Tiền điều kiện: Train; chọn nhánh điểm hoặc gói, không yêu cầu cài cả hai app.
- Workflow khuyến nghị: [W15](workflow-analysis.md#w15). Nhánh điểm: get_points → chọn program/rewards → redeem. Nhánh gói: subscriptions.list → chọn subscription_id → cancel.
- Hoàn tất: Voucher mới và điểm cập nhật hoặc gói đã huỷ.
- Thông tin thiếu: Thiếu program/reward_id/subscription_id sau đọc → hỏi. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Cấu trúc programs/rewards theo mã và kết quả thực; không giả có áp voucher.
- Chứng cứ: mức E tại workflow trên; [`loyalty.get_points`](tool-catalog-inventory.md#tool-loyalty-get_points), [`loyalty.redeem`](tool-catalog-inventory.md#tool-loyalty-redeem), [`subscriptions.list`](tool-catalog-inventory.md#tool-subscriptions-list), [`subscriptions.cancel`](tool-catalog-inventory.md#tool-subscriptions-cancel), [`loyalty.list_vouchers`](tool-catalog-inventory.md#tool-loyalty-list_vouchers). Mã và nguồn output được liên kết ở từng workflow.

<a id="s12"></a>

## S12 — Chọn điểm đến và dịch vụ di chuyển

- skill_id: `S12`; miền: D08; ưu tiên: P2.
- Mô tả: Điều phối chọn điểm đến và đặt/huỷ xe; thuê xe đạp hoặc đặt/kết thúc chỗ đỗ; tìm tuyến công cộng hoặc nạp thẻ theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Đặt xe đến địa điểm tìm được; thuê xe đạp gần nhất; đặt/kết thúc chỗ đỗ; xem chuyến bus kế.
- Tool bắt buộc theo nhánh: `ride_hailing.book`, `ride_hailing.get_ride`, `ride_hailing.cancel`, `bike_rental.find_bikes`, `bike_rental.reserve`, `parking.find`, `parking.reserve`, `parking.list_sessions`, `parking.end_session`, `public_transit.find_routes`, `public_transit.next_departures`.
- Tool phụ trợ: `maps.search_place`, `maps.get_route`, `maps.save_place`, `ride_hailing.get_quotes`.
- Tiền điều kiện: Chọn nhánh phương tiện; đủ điểm đi/đến và tiêu chí lựa chọn nếu cần.
- Workflow khuyến nghị: [W17](workflow-analysis.md#w17), [W18](workflow-analysis.md#w18), [W19](workflow-analysis.md#w19). Nếu cần phân giải địa điểm: search_place → lấy địa chỉ; nếu cần ETA/giá: get_route/get_quotes → đánh giá → book. Huỷ: get_ride → cancel. save_place chỉ khi có yêu cầu lưu. Xe đạp: find_bikes → reserve. Đỗ xe: find → reserve; kết thúc: list_sessions → end_session. find_routes → chọn tuyến/trạm → next_departures nếu cần giờ; topup_card là yêu cầu trực tiếp với amount.
- Hoàn tất: Ride booked/cancelled hoặc địa điểm được lưu theo ý định. Xe được giữ hoặc parking.session có trạng thái đích. Trả tuyến/giờ hoặc số dư thẻ đã nạp.
- Thông tin thiếu: Thiếu pickup/dropoff/vehicle hoặc ride_id → hỏi; không tự giả định loại xe. Thiếu bike_id/lot_id/from_time/hours/session_id → hỏi. Thiếu origin/destination/stop/amount theo tool cần gọi → hỏi. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Các nhánh bike/parking khác split; không ép lấy báo giá trước book; không gộp tất cả thành một tuyến cố định.
- Chứng cứ: mức S/E tại workflow trên; [`ride_hailing.book`](tool-catalog-inventory.md#tool-ride_hailing-book), [`ride_hailing.get_ride`](tool-catalog-inventory.md#tool-ride_hailing-get_ride), [`ride_hailing.cancel`](tool-catalog-inventory.md#tool-ride_hailing-cancel), [`bike_rental.find_bikes`](tool-catalog-inventory.md#tool-bike_rental-find_bikes), [`bike_rental.reserve`](tool-catalog-inventory.md#tool-bike_rental-reserve), [`parking.find`](tool-catalog-inventory.md#tool-parking-find), [`parking.reserve`](tool-catalog-inventory.md#tool-parking-reserve), [`parking.list_sessions`](tool-catalog-inventory.md#tool-parking-list_sessions), [`parking.end_session`](tool-catalog-inventory.md#tool-parking-end_session), [`public_transit.find_routes`](tool-catalog-inventory.md#tool-public_transit-find_routes), [`public_transit.next_departures`](tool-catalog-inventory.md#tool-public_transit-next_departures), [`maps.search_place`](tool-catalog-inventory.md#tool-maps-search_place), [`maps.get_route`](tool-catalog-inventory.md#tool-maps-get_route), [`maps.save_place`](tool-catalog-inventory.md#tool-maps-save_place), [`ride_hailing.get_quotes`](tool-catalog-inventory.md#tool-ride_hailing-get_quotes). Mã và nguồn output được liên kết ở từng workflow.

<a id="s13"></a>

## S13 — Quản lý vé liên tỉnh theo vòng đời

- skill_id: `S13`; miền: D09; ưu tiên: P1.
- Mô tả: Điều phối đặt, huỷ hoặc check-in vé liên tỉnh theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Tìm và đặt chuyến phù hợp; huỷ vé đã đặt; check-in máy bay.
- Tool bắt buộc theo nhánh: `flights.search`, `flights.book`, `flights.my_bookings`, `flights.cancel`, `flights.check_in`, `train_bus_tickets.search`, `train_bus_tickets.book`, `train_bus_tickets.my_bookings`, `train_bus_tickets.cancel`.
- Tool phụ trợ: Không có.
- Tiền điều kiện: Có loại vé và ý định vòng đời; nhánh đặt cần ngày/điểm đi/đến/số người hoặc ghế.
- Workflow khuyến nghị: [W20](workflow-analysis.md#w20). Đặt: search → chọn flight_id/trip_id → book; quản lý: my_bookings → chọn booking_id → cancel/check_in (bay).
- Hoàn tất: Booking confirmed/cancelled hoặc checked_in:true.
- Thông tin thiếu: Thiếu origin/destination/date/passengers/seats/booking_id → hỏi theo nhánh. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Không dùng flight_id cho cancel; không giả có check-in tàu/xe; không tự đặt vé mới thay cho huỷ.
- Chứng cứ: mức E tại workflow trên; [`flights.search`](tool-catalog-inventory.md#tool-flights-search), [`flights.book`](tool-catalog-inventory.md#tool-flights-book), [`flights.my_bookings`](tool-catalog-inventory.md#tool-flights-my_bookings), [`flights.cancel`](tool-catalog-inventory.md#tool-flights-cancel), [`flights.check_in`](tool-catalog-inventory.md#tool-flights-check_in), [`train_bus_tickets.search`](tool-catalog-inventory.md#tool-train_bus_tickets-search), [`train_bus_tickets.book`](tool-catalog-inventory.md#tool-train_bus_tickets-book), [`train_bus_tickets.my_bookings`](tool-catalog-inventory.md#tool-train_bus_tickets-my_bookings), [`train_bus_tickets.cancel`](tool-catalog-inventory.md#tool-train_bus_tickets-cancel). Mã và nguồn output được liên kết ở từng workflow.

<a id="s14"></a>

## S14 — Chọn quán, món và quản lý đơn ăn

- skill_id: `S14`; miền: D10; ưu tiên: P1.
- Mô tả: Điều phối đặt hoặc huỷ món giao tận nơi theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Đặt món cụ thể tại quán; huỷ đơn đồ ăn gần đây.
- Tool bắt buộc theo nhánh: `food_delivery.list_restaurants`, `food_delivery.get_menu`, `food_delivery.place_order`, `food_delivery.order_history`, `food_delivery.cancel_order`.
- Tool phụ trợ: Không có.
- Tiền điều kiện: Có món/quán hoặc tiêu chí đơn cần huỷ.
- Workflow khuyến nghị: [W21](workflow-analysis.md#w21). Đặt: list_restaurants → get_menu → chọn items → place_order. Huỷ: order_history → chọn order_id → cancel_order.
- Hoàn tất: Có order đúng món hoặc status cancelled; không coi menu trả rỗng là thành công đặt.
- Thông tin thiếu: Thiếu restaurant_id/items hoặc order_id; không tự bịa quantity khi người dùng chưa rõ. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Đặt cần menu đúng quán; huỷ không cần gọi lại menu; không trừ ví thủ công theo payment.
- Chứng cứ: mức E tại workflow trên; [`food_delivery.list_restaurants`](tool-catalog-inventory.md#tool-food_delivery-list_restaurants), [`food_delivery.get_menu`](tool-catalog-inventory.md#tool-food_delivery-get_menu), [`food_delivery.place_order`](tool-catalog-inventory.md#tool-food_delivery-place_order), [`food_delivery.order_history`](tool-catalog-inventory.md#tool-food_delivery-order_history), [`food_delivery.cancel_order`](tool-catalog-inventory.md#tool-food_delivery-cancel_order). Mã và nguồn output được liên kết ở từng workflow.

<a id="s15"></a>

## S15 — Chuẩn bị nguyên liệu theo công thức

- skill_id: `S15`; miền: D10, D11; ưu tiên: P3.
- Mô tả: Điều phối công thức, tủ bếp và danh sách cần mua theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Nấu cho bốn người, xem thiếu gì rồi thêm danh sách mua.
- Tool bắt buộc theo nhánh: `recipes.search`, `pantry.list_items`, `shopping_list.add`.
- Tool phụ trợ: `recipes.get`, `recipes.save`, `pantry.consume`, `grocery.search`, `grocery.add_to_cart`, `grocery.checkout`.
- Tiền điều kiện: Public Test; công thức, đơn vị và số khẩu phần đủ rõ; chỉ bật nhánh mua khi người dùng yêu cầu.
- Workflow khuyến nghị: [W22](workflow-analysis.md#w22). search(query,servings) → chọn công thức → get nếu cần bước; list_items → so nguyên liệu cùng đơn vị → shopping_list.add phần thiếu hoặc nhánh grocery. consume chỉ khi người dùng nói đã dùng.
- Hoàn tất: Công thức đã lấy/lưu; danh sách hoặc order chỉ gồm phần xác định được; consume xác nhận trừ đúng món.
- Thông tin thiếu: Thiếu recipe_id/query hoặc name/quantity khi dùng công cụ mua/consume → hỏi đúng tên; không đưa trường tự chế như missing_ingredients vào sys. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Đây là candidate cần review: không ép quantity phân số vào integer; không đồng nhất pantry.item_id với product_id; không tự consume.
- Chứng cứ: mức H tại workflow trên; [`recipes.search`](tool-catalog-inventory.md#tool-recipes-search), [`pantry.list_items`](tool-catalog-inventory.md#tool-pantry-list_items), [`shopping_list.add`](tool-catalog-inventory.md#tool-shopping_list-add), [`recipes.get`](tool-catalog-inventory.md#tool-recipes-get), [`recipes.save`](tool-catalog-inventory.md#tool-recipes-save), [`pantry.consume`](tool-catalog-inventory.md#tool-pantry-consume), [`grocery.search`](tool-catalog-inventory.md#tool-grocery-search), [`grocery.add_to_cart`](tool-catalog-inventory.md#tool-grocery-add_to_cart), [`grocery.checkout`](tool-catalog-inventory.md#tool-grocery-checkout). Mã và nguồn output được liên kết ở từng workflow.

<a id="s16"></a>

## S16 — Mua hàng theo giỏ

- skill_id: `S16`; miền: D11; ưu tiên: P1.
- Mô tả: Điều phối tìm hàng, thêm giỏ và checkout theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Mua sản phẩm hoặc thực phẩm và đặt giao; thêm món vào giỏ.
- Tool bắt buộc theo nhánh: `ecommerce.search`, `ecommerce.add_to_cart`, `ecommerce.checkout`, `grocery.search`, `grocery.add_to_cart`, `grocery.checkout`.
- Tool phụ trợ: Không có.
- Tiền điều kiện: Public Test; chọn đúng app, sản phẩm và số lượng; checkout chỉ khi được yêu cầu.
- Workflow khuyến nghị: [W23](workflow-analysis.md#w23). Chọn app → search → chọn sản phẩm và quantity → add_to_cart → đọc cart trả về → checkout chỉ khi người dùng muốn đặt toàn bộ giỏ.
- Hoàn tất: Order trả đúng giỏ đã được người dùng yêu cầu đặt; không checkout lại.
- Thông tin thiếu: Thiếu query/product_id/quantity cần hỏi; address là optional, không tự nâng thành required. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Giỏ cũ có thể chứa món khác; add_to_cart trả toàn giỏ; không có get_cart/remove_cart để sửa giỏ.
- Chứng cứ: mức E tại workflow trên; [`ecommerce.search`](tool-catalog-inventory.md#tool-ecommerce-search), [`ecommerce.add_to_cart`](tool-catalog-inventory.md#tool-ecommerce-add_to_cart), [`ecommerce.checkout`](tool-catalog-inventory.md#tool-ecommerce-checkout), [`grocery.search`](tool-catalog-inventory.md#tool-grocery-search), [`grocery.add_to_cart`](tool-catalog-inventory.md#tool-grocery-add_to_cart), [`grocery.checkout`](tool-catalog-inventory.md#tool-grocery-checkout). Mã và nguồn output được liên kết ở từng workflow.

<a id="s17"></a>

## S17 — Xử lý đơn hàng và giao nhận

- skill_id: `S17`; miền: D11; ưu tiên: P2.
- Mô tả: Điều phối huỷ đơn hoặc trả hàng online; cập nhật danh sách mua hoặc lịch giao nhận theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Trả đơn bị hỏng; huỷ đơn chưa giao; dời lịch giao một kiện.
- Tool bắt buộc theo nhánh: `ecommerce.order_status`, `ecommerce.cancel_order`, `ecommerce.request_return`, `package_tracking.track`, `package_tracking.reschedule_delivery`.
- Tool phụ trợ: `package_tracking.schedule_pickup`.
- Tiền điều kiện: Chọn nhánh e-commerce hoặc vận đơn theo split/installed tools.
- Workflow khuyến nghị: [W24](workflow-analysis.md#w24), [W25](workflow-analysis.md#w25). order_status → chọn order_id và kiểm status → cancel_order hoặc request_return. Danh sách: get → item_id → remove/check. Kiện hàng: track → tracking_id → reschedule_delivery. schedule_pickup đủ address/date thì trực tiếp.
- Hoàn tất: Order cancelled hoặc return.status=requested; chưa khẳng định refund completed. Món được check/xoá hoặc lịch shipment/pickup được trả.
- Thông tin thiếu: Thiếu order_id/reason theo nhánh → hỏi. Thiếu item_id/tracking_id/time/address/date → hỏi theo nhánh. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: request_return là tạo yêu cầu, chưa phải đã hoàn tiền; không giả có ánh xạ order_id→tracking_id.
- Chứng cứ: mức E tại workflow trên; [`ecommerce.order_status`](tool-catalog-inventory.md#tool-ecommerce-order_status), [`ecommerce.cancel_order`](tool-catalog-inventory.md#tool-ecommerce-cancel_order), [`ecommerce.request_return`](tool-catalog-inventory.md#tool-ecommerce-request_return), [`package_tracking.track`](tool-catalog-inventory.md#tool-package_tracking-track), [`package_tracking.reschedule_delivery`](tool-catalog-inventory.md#tool-package_tracking-reschedule_delivery), [`package_tracking.schedule_pickup`](tool-catalog-inventory.md#tool-package_tracking-schedule_pickup). Mã và nguồn output được liên kết ở từng workflow.

<a id="s18"></a>

## S18 — Chọn và lưu nội dung giải trí

- skill_id: `S18`; miền: D12; ưu tiên: P2.
- Mô tả: Điều phối chọn nội dung nghe và quản lý thư viện; chọn kênh hoặc ghi hình tv; đặt vé sự kiện theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Phát playlist; xếp podcast nghe sau; ghi chương trình; đặt vé buổi diễn.
- Tool bắt buộc theo nhánh: `music.list_tracks`, `music.play`, `music.add_to_playlist`, `podcast_radio.search`, `podcast_radio.play`, `podcast_radio.subscribe`, `podcast_radio.queue`, `tv.guide`, `tv.tune`, `tv.record`, `event_tickets.search`, `event_tickets.book`.
- Tool phụ trợ: `music.control`, `tv.control`.
- Tiền điều kiện: Chọn nhánh nội dung và đối tượng; event_tickets chỉ Public Test, podcast chỉ Train.
- Workflow khuyến nghị: [W26](workflow-analysis.md#w26), [W27](workflow-analysis.md#w27), [W28](workflow-analysis.md#w28). Nhạc: list_tracks → chọn track_id/playlist_id → play/add_to_playlist. Podcast: search → episode_id/station/show_id → play/queue/subscribe. guide → chọn channels/programs → tune hoặc record; control on/off/mute trực tiếp khi đủ yêu cầu. search → chọn event_id → book(quantity).
- Hoàn tất: Nội dung/playlist/hàng đợi/theo dõi được cập nhật đúng. Kênh đang phát hoặc lịch recording đúng chương trình. Booking vé sự kiện được trả.
- Thông tin thiếu: Thiếu một nhánh ID hoặc volume khi action cần số nhưng schema chưa bắt buộc: không bịa giá trị; chỉ sys với tham số bắt buộc, còn hành vi volume cần review. Thiếu channel/program_id → hỏi; không suy chương trình thành ID. Thiếu event_id/quantity → hỏi. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Gộp mẫu search/list→select→act, giữ chỉ dẫn TV guide và x-one-of từng app; nếu quá dài cần retrieval theo đoạn nhánh.
- Chứng cứ: mức E tại workflow trên; [`music.list_tracks`](tool-catalog-inventory.md#tool-music-list_tracks), [`music.play`](tool-catalog-inventory.md#tool-music-play), [`music.add_to_playlist`](tool-catalog-inventory.md#tool-music-add_to_playlist), [`podcast_radio.search`](tool-catalog-inventory.md#tool-podcast_radio-search), [`podcast_radio.play`](tool-catalog-inventory.md#tool-podcast_radio-play), [`podcast_radio.subscribe`](tool-catalog-inventory.md#tool-podcast_radio-subscribe), [`podcast_radio.queue`](tool-catalog-inventory.md#tool-podcast_radio-queue), [`tv.guide`](tool-catalog-inventory.md#tool-tv-guide), [`tv.tune`](tool-catalog-inventory.md#tool-tv-tune), [`tv.record`](tool-catalog-inventory.md#tool-tv-record), [`event_tickets.search`](tool-catalog-inventory.md#tool-event_tickets-search), [`event_tickets.book`](tool-catalog-inventory.md#tool-event_tickets-book), [`music.control`](tool-catalog-inventory.md#tool-music-control), [`tv.control`](tool-catalog-inventory.md#tool-tv-control). Mã và nguồn output được liên kết ở từng workflow.

<a id="s19"></a>

## S19 — Ghi nhận sức khoẻ và học tập theo đối tượng

- skill_id: `S19`; miền: D13, D14; ưu tiên: P2.
- Mô tả: Điều phối ghi lịch thuốc, vận động hoặc thói quen; đăng ký/lên lịch học hoặc giữ sách theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Ghi đã uống thuốc; đánh dấu thói quen; ghi tiến độ khoá học; giữ sách.
- Tool bắt buộc theo nhánh: `medication.list`, `medication.log_taken`, `medication.remove`, `habit_tracker.list_habits`, `habit_tracker.log`, `learning.list_courses`, `learning.enroll`, `learning.schedule_lesson`, `learning.log_progress`, `library.search`, `library.reserve`.
- Tool phụ trợ: `medication.add`, `fitness.get_activity`, `fitness.log_workout`, `fitness.set_goal`.
- Tiền điều kiện: Có đối tượng và hành vi ghi nhận rõ; từng nhánh phải có tool tương ứng.
- Workflow khuyến nghị: [W29](workflow-analysis.md#w29), [W30](workflow-analysis.md#w30). Lịch thuốc: list → log_taken/remove; thêm lịch dùng add nếu name/times đã đủ. Habit: list_habits → log. Fitness: đọc activity nếu có điều kiện rồi log_workout/set_goal theo ý định. Khoá: list_courses → chọn course_id → enroll/schedule_lesson/log_progress. Sách: search → book_id → reserve.
- Hoàn tất: Bản ghi hoạt động/lịch/habit hoặc goal đúng ý định; không coi đây là kết quả sức khoẻ. Khoá/tiến độ/buổi học hoặc giữ sách được trả.
- Thông tin thiếu: Thiếu schedule_id/habit_id/date/name/times/type/minutes/steps → hỏi đúng tool. Thiếu course_id/time/minutes/book_id → hỏi. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Dùng mẫu resolve ID→record dùng chung; nội dung nhánh sức khoẻ không được suy liều/khuyến nghị y khoa. Cần review độ rộng trước khi tách.
- Chứng cứ: mức E tại workflow trên; [`medication.list`](tool-catalog-inventory.md#tool-medication-list), [`medication.log_taken`](tool-catalog-inventory.md#tool-medication-log_taken), [`medication.remove`](tool-catalog-inventory.md#tool-medication-remove), [`habit_tracker.list_habits`](tool-catalog-inventory.md#tool-habit_tracker-list_habits), [`habit_tracker.log`](tool-catalog-inventory.md#tool-habit_tracker-log), [`learning.list_courses`](tool-catalog-inventory.md#tool-learning-list_courses), [`learning.enroll`](tool-catalog-inventory.md#tool-learning-enroll), [`learning.schedule_lesson`](tool-catalog-inventory.md#tool-learning-schedule_lesson), [`learning.log_progress`](tool-catalog-inventory.md#tool-learning-log_progress), [`library.search`](tool-catalog-inventory.md#tool-library-search), [`library.reserve`](tool-catalog-inventory.md#tool-library-reserve), [`medication.add`](tool-catalog-inventory.md#tool-medication-add), [`fitness.get_activity`](tool-catalog-inventory.md#tool-fitness-get_activity), [`fitness.log_workout`](tool-catalog-inventory.md#tool-fitness-log_workout), [`fitness.set_goal`](tool-catalog-inventory.md#tool-fitness-set_goal). Mã và nguồn output được liên kết ở từng workflow.

<a id="s20"></a>

## S20 — Thực hiện điều kiện chứng khoán mô phỏng

- skill_id: `S20`; miền: D16; ưu tiên: P3.
- Mô tả: Điều phối lệnh/cảnh báo chứng khoán theo điều kiện theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Nếu giá dưới ngưỡng thì mua; bán một phần danh mục; đặt cảnh báo giá.
- Tool bắt buộc theo nhánh: `stocks.get_quote`, `stocks.place_order`, `stocks.set_price_alert`.
- Tool phụ trợ: `stocks.get_portfolio`.
- Tiền điều kiện: Public Test; có symbol, hành động và điều kiện do người dùng chỉ định.
- Workflow khuyến nghị: [W31](workflow-analysis.md#w31). Nếu ý định có điều kiện giá/danh mục: get_quote/get_portfolio → so sánh → place_order hoặc set_price_alert.
- Hoàn tất: Order.status=placed hoặc alert.active=true; đặt lệnh không đồng nghĩa khớp lệnh.
- Thông tin thiếu: Thiếu symbol/side/quantity hay price/direction của cảnh báo → hỏi đúng nhánh. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Không tự đề xuất giao dịch; không bắt buộc read với lệnh trực tiếp đủ dữ kiện; không khẳng định đã khớp.
- Chứng cứ: mức S tại workflow trên; [`stocks.get_quote`](tool-catalog-inventory.md#tool-stocks-get_quote), [`stocks.place_order`](tool-catalog-inventory.md#tool-stocks-place_order), [`stocks.set_price_alert`](tool-catalog-inventory.md#tool-stocks-set_price_alert), [`stocks.get_portfolio`](tool-catalog-inventory.md#tool-stocks-get_portfolio). Mã và nguồn output được liên kết ở từng workflow.

<a id="s21"></a>

## S21 — Thông báo thông tin từ lịch

- skill_id: `S21`; miền: D03, D04; ưu tiên: P2.
- Mô tả: Điều phối xem lịch rồi báo qua liên lạc theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Xem cuộc họp ngày mai rồi nhắn thông tin cho đồng nghiệp.
- Tool bắt buộc theo nhánh: `calendar.list_events`, `sms.send`, `chat_ott.send_message`.
- Tool phụ trợ: `contacts.search`, `chat_ott.list_chats`.
- Tiền điều kiện: Có yêu cầu lấy lịch và gửi; cần một kênh gửi hợp lệ, không phải cả hai.
- Workflow khuyến nghị: [W32](workflow-analysis.md#w32). list_events → chọn sự kiện và trích giờ/địa điểm → phân giải recipient/chat → gửi đúng kênh.
- Hoàn tất: Tin chứa thông tin sự kiện đúng đã gửi đến đúng đối tượng.
- Thông tin thiếu: Thiếu người nhận hoặc sự kiện mơ hồ → hỏi ID/recipient của tool liên quan, không tự chọn. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Dùng S06 cho recipient, chỉ dẫn riêng là ánh xạ thông tin lịch thành content; không lặp nội dung danh bạ.
- Chứng cứ: mức S tại workflow trên; [`calendar.list_events`](tool-catalog-inventory.md#tool-calendar-list_events), [`sms.send`](tool-catalog-inventory.md#tool-sms-send), [`chat_ott.send_message`](tool-catalog-inventory.md#tool-chat_ott-send_message), [`contacts.search`](tool-catalog-inventory.md#tool-contacts-search), [`chat_ott.list_chats`](tool-catalog-inventory.md#tool-chat_ott-list_chats). Mã và nguồn output được liên kết ở từng workflow.

<a id="s22"></a>

## S22 — Điều khiển nhà theo điều kiện hiện tại

- skill_id: `S22`; miền: D07, D01; ưu tiên: P2.
- Mô tả: Điều phối theo thời tiết rồi điều khiển nhà; đặt ngưỡng điện năng từ số liệu theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Nếu dự báo đạt điều kiện thì chỉnh thiết bị; đặt ngưỡng điện theo quy tắc được nêu.
- Tool bắt buộc theo nhánh: `weather.get_current`, `weather.get_forecast`, `smart_home.get_status`, `smart_home.climate_set`, `smart_home.switch_set`, `home_energy.get_usage`, `home_energy.set_alert`.
- Tool phụ trợ: Không có.
- Tiền điều kiện: Có điều kiện và hành động rõ; chỉ một nhánh weather hoặc energy cần được dùng.
- Workflow khuyến nghị: [W33](workflow-analysis.md#w33), [W37](workflow-analysis.md#w37). Lấy current hoặc forecast theo thời điểm yêu cầu → đánh giá điều kiện do người dùng nêu → get_status → setter nếu điều kiện đúng. get_usage(period) khi yêu cầu phụ thuộc số liệu → tính threshold theo quy tắc người dùng → set_alert; ngưỡng nói rõ có thể set_alert trực tiếp.
- Hoàn tất: Điều kiện sai: kết thúc không ghi; điều kiện đúng: setter thành công. alert_threshold_kwh đúng ngưỡng; không tuyên bố tiêu thụ đã giảm.
- Thông tin thiếu: Thiếu date cho forecast hoặc mode/device_id chưa rõ → hỏi đúng tool. Thiếu period hoặc threshold_kwh không xác định được → hỏi đúng tool. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Ghép S01 với đọc điều kiện, không thêm mọi setter; không hứa automation lâu dài theo weather.
- Chứng cứ: mức S tại workflow trên; [`weather.get_current`](tool-catalog-inventory.md#tool-weather-get_current), [`weather.get_forecast`](tool-catalog-inventory.md#tool-weather-get_forecast), [`smart_home.get_status`](tool-catalog-inventory.md#tool-smart_home-get_status), [`smart_home.climate_set`](tool-catalog-inventory.md#tool-smart_home-climate_set), [`smart_home.switch_set`](tool-catalog-inventory.md#tool-smart_home-switch_set), [`home_energy.get_usage`](tool-catalog-inventory.md#tool-home_energy-get_usage), [`home_energy.set_alert`](tool-catalog-inventory.md#tool-home_energy-set_alert). Mã và nguồn output được liên kết ở từng workflow.

<a id="s23"></a>

## S23 — Lập giờ nhắc/đón theo chuyến bay

- skill_id: `S23`; miền: D09, D08, D03; ưu tiên: P3.
- Mô tả: Điều phối vé, thời gian di chuyển và nhắc/đặt xe theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Dựa vé bay và đường đi để nhắc rời nhà hoặc đặt xe.
- Tool bắt buộc theo nhánh: `flights.my_bookings`, `maps.get_route`, `reminders.create`, `ride_hailing.book`.
- Tool phụ trợ: Không có.
- Tiền điều kiện: Có chuyến cụ thể, địa điểm và quy tắc giờ đệm; reminders/ride là nhánh theo ý định.
- Workflow khuyến nghị: [W34](workflow-analysis.md#w34). my_bookings → chọn chuyến → get_route nếu cần ước lượng → tính giờ từ quy tắc người dùng → reminders.create và/hoặc ride_hailing.book.
- Hoàn tất: Nhắc hoặc ride được tạo đúng lựa chọn và thời gian.
- Thông tin thiếu: Thiếu content/time của reminder hoặc pickup/dropoff/vehicle của book → hỏi; không bịa airport_address. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Candidate giả thuyết; cần kiểm chứng địa chỉ sân bay, giờ khởi hành và timezone; không tự đặt xe trong yêu cầu chỉ nhắc.
- Chứng cứ: mức H tại workflow trên; [`flights.my_bookings`](tool-catalog-inventory.md#tool-flights-my_bookings), [`maps.get_route`](tool-catalog-inventory.md#tool-maps-get_route), [`reminders.create`](tool-catalog-inventory.md#tool-reminders-create), [`ride_hailing.book`](tool-catalog-inventory.md#tool-ride_hailing-book). Mã và nguồn output được liên kết ở từng workflow.

<a id="s24"></a>

## S24 — Dịch rồi gửi đúng kênh

- skill_id: `S24`; miền: D15, D04; ưu tiên: P2.
- Mô tả: Điều phối dịch nội dung rồi gửi theo nhánh phù hợp với yêu cầu.
- Intent kích hoạt: Dịch câu sang tiếng Anh rồi gửi cho người nhận.
- Tool bắt buộc theo nhánh: `translator.translate`, `sms.send`, `chat_ott.send_message`, `email.send`.
- Tool phụ trợ: `contacts.search`, `chat_ott.list_chats`.
- Tiền điều kiện: Public Test; có nội dung, ngôn ngữ đích và yêu cầu gửi rõ; chỉ một kênh cần dùng.
- Workflow khuyến nghị: [W35](workflow-analysis.md#w35). translate(text,to_lang) → lấy translation → phân giải đích nếu cần → gửi bằng kênh yêu cầu.
- Hoàn tất: Bản dịch được trả và, khi có yêu cầu, được gửi đúng đích.
- Thông tin thiếu: Thiếu text/to_lang hoặc recipient/content/subject/body chưa xác định → hỏi tool tương ứng. Áp dụng W36 chỉ với tên tham số thật của tool hợp lệ.
- Ràng buộc quan trọng: Dùng S06 để phân giải đích; không lặp hướng dẫn recipient; không gửi nếu chỉ xin dịch.
- Chứng cứ: mức S tại workflow trên; [`translator.translate`](tool-catalog-inventory.md#tool-translator-translate), [`sms.send`](tool-catalog-inventory.md#tool-sms-send), [`chat_ott.send_message`](tool-catalog-inventory.md#tool-chat_ott-send_message), [`email.send`](tool-catalog-inventory.md#tool-email-send), [`contacts.search`](tool-catalog-inventory.md#tool-contacts-search), [`chat_ott.list_chats`](tool-catalog-inventory.md#tool-chat_ott-list_chats). Mã và nguồn output được liên kết ở từng workflow.

## Yêu cầu đơn giản không cần skill riêng

| Loại | Ví dụ tool có thật | Lý do / ngoại lệ |
| --- | --- | --- |
| Tra cứu độc lập | weather.get_current, gold_price.get_price, fuel_price.get_price, lottery.get_results, lottery.check_ticket, exchange_rate.get_rate, exchange_rate.convert | Đủ đối số thì gọi trực tiếp; không bắt buộc đọc thêm trước convert/check_ticket. |
| Tiện ích độc lập | calculator.calculate, calculator.convert_unit, translator.translate | Một thao tác; chỉ phối hợp dịch→gửi mới cần S24. |
| Tạo bản ghi đủ dữ kiện | alarm.create, reminders.create, calendar.create_event, notes.create, tasks.add, medication.add, fitness.log_workout, fitness.set_goal | Không cần skill chỉ để bọc một tool. Tách hướng dẫn chung diễn giải thời gian nếu lỗi đo được cho thấy cần. |
| Điều khiển trực tiếp | music.control, tv.control, home_security.arm, robot_vacuum.stop | Có action/mode rõ thì không list trước theo thói quen. |
| Thao tác đơn đủ dữ kiện | shopping_list.add, package_tracking.schedule_pickup, public_transit.topup_card, bill_payment.schedule_autopay, video_meeting.create | Không có phụ thuộc ID bắt buộc phải tìm. |
| Tra cứu/lựa chọn ngắn | news.search → news.save; household_chores.list_chores → household_chores.assign; video_meeting.list_meetings → video_meeting.join; shopping_list.get → check/remove | W05/W11/W16/W25 có thật nhưng ban đầu có thể dùng quy tắc resolve ID chung, chưa cần mỗi nhánh một skill. |
| Thông tin thiếu | sys.ask_missing_info | W36 là quy tắc điều phối dùng chung, không tính là skill thứ 25. |

## Trùng lặp và ranh giới cần review

- Không có hai skill có cùng tập required tool (đã đối chiếu); khác tập không tự chứng minh khác ý nghĩa.
- S01/S22: S01 sở hữu phân giải thiết bị; S22 chỉ bổ sung đọc/đánh giá điều kiện. Ghép tham chiếu thay vì chép lại phần setter.
- S06/S21/S24: cùng đích gửi nhưng khác nguồn nội dung; một đoạn hướng dẫn recipient dùng chung, một đoạn lịch hoặc dịch. Không tạo skill riêng cho SMS của từng nguồn.
- S12/S23: chỉ S23 chịu trách nhiệm suy thời điểm từ chuyến; giao phần phương tiện cho nhánh S12 khi cần.
- S15/S16: S15 giải quyết nguyên liệu thiếu, S16 sở hữu giỏ/checkout; không cả hai cùng add cùng món.
- S05/S17: cùng mẫu list→ID→mutate nhưng đơn hàng có điều kiện trạng thái và giỏ riêng; giữ hướng dẫn nghiệp vụ đó.
- S18/S19 rộng: retrieval nên chọn đoạn đúng app; chỉ tách thành skill nhỏ hơn khi có bằng chứng nhầm lẫn hoặc vượt token budget. Không tách theo từng tool.
- S04 gộp hai nhiệm vụ an ninh có chung đối tượng nhà nhưng không ép khoá sau acknowledge; S11 có nhánh điểm/gói độc lập. Cần review tính gọn trước triển khai.

## Ưu tiên

- **P1:** S01, S05, S06, S08, S09, S10, S13, S14, S16: phụ thuộc ID/nested items/giỏ/nguồn tiền rõ, rủi ro lỗi đối số cao; ưu tiên theo cấu trúc catalog, chưa có số liệu tần suất/quality gain.
- **P2:** các nhánh còn lại sau khi mẫu resolve ID và phân biệt no-op ổn; S21/S22/S24 chỉ cần ghép hướng dẫn hẹp, không tạo planner riêng.
- **P3:** S15/S23 còn thiếu ánh xạ; S20 có ràng buộc trạng thái và chưa có đo hành vi điều kiện. Xác minh trước khi dùng trong inference.
