# Miền nghiệp vụ LifeMate

Ngày phân tích: 10/11/2026. Base: `e216ad5115229598149ca8c4e3f43554ce065268` (nhánh `codex/009-cross-step-kv-cache`). Chỉ nghiên cứu tĩnh; không chạy tool trên mẫu, GPU, inference, retrieval hay skill thực thi.

Train: **147 tool / 46 app**. Public Test: **122 tool / 36 app**. Giao: **88 tool**; chỉ Train: **59**; chỉ Public Test: **34**. Hợp: **181 tool / 57 app**.

Có **17 miền chính**, phân theo hành vi thật thay vì coi mỗi namespace là một miền. Mỗi tool có đúng một miền chính; công cụ dùng chéo được ghi riêng, không nhân đôi tổng đếm. Metadata `group` gốc được giữ để tham khảo, không quyết định cách ghép skill.

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

## D01 — Nhà ở, thiết bị và việc nhà

Điều khiển thiết bị, chu trình, điện năng và quy tắc hằng ngày.

- App: `smart_home`, `robot_vacuum`, `appliances`, `home_energy`, `home_automation`, `household_chores`.
- Số tool hợp: **19**; Train: 19; Public Test: 6.
- Ý định chính: Bật/tắt theo phòng; chạy cảnh; dọn nhà; giao việc; đặt lịch thiết bị.
- Phụ thuộc thường gặp: Đọc thiết bị/phòng/chu trình/thành viên rồi chọn đúng đối tượng; quy tắc lấy device_id từ smart_home.
- Tool và chứng cứ: [`smart_home.get_status`](tool-catalog-inventory.md#tool-smart_home-get_status), [`smart_home.light_set`](tool-catalog-inventory.md#tool-smart_home-light_set), [`smart_home.fan_set`](tool-catalog-inventory.md#tool-smart_home-fan_set), [`smart_home.climate_set`](tool-catalog-inventory.md#tool-smart_home-climate_set), [`smart_home.switch_set`](tool-catalog-inventory.md#tool-smart_home-switch_set), [`smart_home.scene_run`](tool-catalog-inventory.md#tool-smart_home-scene_run), [`robot_vacuum.get_status`](tool-catalog-inventory.md#tool-robot_vacuum-get_status), [`robot_vacuum.start`](tool-catalog-inventory.md#tool-robot_vacuum-start), [`robot_vacuum.stop`](tool-catalog-inventory.md#tool-robot_vacuum-stop), [`appliances.list`](tool-catalog-inventory.md#tool-appliances-list), [`appliances.start_cycle`](tool-catalog-inventory.md#tool-appliances-start_cycle), [`appliances.stop`](tool-catalog-inventory.md#tool-appliances-stop), [`home_energy.get_usage`](tool-catalog-inventory.md#tool-home_energy-get_usage), [`home_energy.set_alert`](tool-catalog-inventory.md#tool-home_energy-set_alert), [`home_automation.list_rules`](tool-catalog-inventory.md#tool-home_automation-list_rules), [`home_automation.create_rule`](tool-catalog-inventory.md#tool-home_automation-create_rule), [`home_automation.delete_rule`](tool-catalog-inventory.md#tool-home_automation-delete_rule), [`household_chores.list_chores`](tool-catalog-inventory.md#tool-household_chores-list_chores), [`household_chores.assign`](tool-catalog-inventory.md#tool-household_chores-assign).

## D02 — An ninh và ra vào

Cảnh báo, camera, chế độ bảo vệ và khoá cửa.

- App: `home_security`, `door_lock`.
- Số tool hợp: **7**; Train: 7; Public Test: 0.
- Ý định chính: Xem cảnh báo; xác nhận đã xem; khoá cửa; cấp mã khách.
- Phụ thuộc thường gặp: list_alerts → alert_id; list_locks → lock_id; arm nhận mode trực tiếp.
- Tool và chứng cứ: [`home_security.list_alerts`](tool-catalog-inventory.md#tool-home_security-list_alerts), [`home_security.get_camera`](tool-catalog-inventory.md#tool-home_security-get_camera), [`home_security.arm`](tool-catalog-inventory.md#tool-home_security-arm), [`home_security.acknowledge_alert`](tool-catalog-inventory.md#tool-home_security-acknowledge_alert), [`door_lock.list_locks`](tool-catalog-inventory.md#tool-door_lock-list_locks), [`door_lock.set_lock`](tool-catalog-inventory.md#tool-door_lock-set_lock), [`door_lock.grant_guest_code`](tool-catalog-inventory.md#tool-door_lock-grant_guest_code).

## D03 — Lịch, nhắc việc và ghi chép

Quản lý thời gian và bản ghi cá nhân.

- App: `alarm`, `reminders`, `calendar`, `notes`, `tasks`.
- Số tool hợp: **18**; Train: 18; Public Test: 18.
- Ý định chính: Tạo/sửa/huỷ hẹn, báo thức; hoàn thành việc; nối ghi chú.
- Phụ thuộc thường gặp: List để tìm ID khi sửa/xoá; tạo mới với đủ dữ kiện không cần list trước.
- Tool và chứng cứ: [`alarm.list`](tool-catalog-inventory.md#tool-alarm-list), [`alarm.create`](tool-catalog-inventory.md#tool-alarm-create), [`alarm.update`](tool-catalog-inventory.md#tool-alarm-update), [`alarm.delete`](tool-catalog-inventory.md#tool-alarm-delete), [`reminders.list`](tool-catalog-inventory.md#tool-reminders-list), [`reminders.create`](tool-catalog-inventory.md#tool-reminders-create), [`reminders.complete`](tool-catalog-inventory.md#tool-reminders-complete), [`reminders.delete`](tool-catalog-inventory.md#tool-reminders-delete), [`calendar.list_events`](tool-catalog-inventory.md#tool-calendar-list_events), [`calendar.create_event`](tool-catalog-inventory.md#tool-calendar-create_event), [`calendar.update_event`](tool-catalog-inventory.md#tool-calendar-update_event), [`calendar.cancel_event`](tool-catalog-inventory.md#tool-calendar-cancel_event), [`notes.list`](tool-catalog-inventory.md#tool-notes-list), [`notes.create`](tool-catalog-inventory.md#tool-notes-create), [`notes.append`](tool-catalog-inventory.md#tool-notes-append), [`tasks.list`](tool-catalog-inventory.md#tool-tasks-list), [`tasks.add`](tool-catalog-inventory.md#tool-tasks-add), [`tasks.complete`](tool-catalog-inventory.md#tool-tasks-complete).

## D04 — Liên lạc và hội họp

Danh bạ, điện thoại, SMS, OTT, email và phòng họp.

- App: `contacts`, `phone`, `sms`, `chat_ott`, `email`, `video_meeting`.
- Số tool hợp: **21**; Train: 21; Public Test: 18.
- Ý định chính: Tìm người; gọi/nhắn; trả lời email; tham gia họp.
- Phụ thuộc thường gặp: contacts.search → contact_id/phone/email; list_chats → chat_id; email.list → email_id; list_meetings → meeting_id.
- Tool và chứng cứ: [`contacts.search`](tool-catalog-inventory.md#tool-contacts-search), [`contacts.get`](tool-catalog-inventory.md#tool-contacts-get), [`contacts.update`](tool-catalog-inventory.md#tool-contacts-update), [`phone.call`](tool-catalog-inventory.md#tool-phone-call), [`phone.recent_calls`](tool-catalog-inventory.md#tool-phone-recent_calls), [`sms.send`](tool-catalog-inventory.md#tool-sms-send), [`sms.read_recent`](tool-catalog-inventory.md#tool-sms-read_recent), [`chat_ott.list_chats`](tool-catalog-inventory.md#tool-chat_ott-list_chats), [`chat_ott.read_chat`](tool-catalog-inventory.md#tool-chat_ott-read_chat), [`chat_ott.send_message`](tool-catalog-inventory.md#tool-chat_ott-send_message), [`chat_ott.send_location`](tool-catalog-inventory.md#tool-chat_ott-send_location), [`chat_ott.call`](tool-catalog-inventory.md#tool-chat_ott-call), [`email.list`](tool-catalog-inventory.md#tool-email-list), [`email.read`](tool-catalog-inventory.md#tool-email-read), [`email.send`](tool-catalog-inventory.md#tool-email-send), [`email.create_draft`](tool-catalog-inventory.md#tool-email-create_draft), [`email.reply`](tool-catalog-inventory.md#tool-email-reply), [`email.archive`](tool-catalog-inventory.md#tool-email-archive), [`video_meeting.list_meetings`](tool-catalog-inventory.md#tool-video_meeting-list_meetings), [`video_meeting.create`](tool-catalog-inventory.md#tool-video_meeting-create), [`video_meeting.join`](tool-catalog-inventory.md#tool-video_meeting-join).

## D05 — Ngân hàng, ví và hoá đơn

Tài khoản, người thụ hưởng, chuyển tiền và thanh toán.

- App: `banking`, `ewallet`, `bill_payment`.
- Số tool hợp: **12**; Train: 12; Public Test: 12.
- Ý định chính: Chuyển tiền; gửi tiết kiệm; trả hoá đơn; trả QR; nạp điện thoại.
- Phụ thuộc thường gặp: Tài khoản + người thụ hưởng → transfer; bills → pay; merchant_id từ food_delivery; ví có thể bị trừ bởi bill_payment.
- Tool và chứng cứ: [`banking.get_balance`](tool-catalog-inventory.md#tool-banking-get_balance), [`banking.list_transactions`](tool-catalog-inventory.md#tool-banking-list_transactions), [`banking.list_beneficiaries`](tool-catalog-inventory.md#tool-banking-list_beneficiaries), [`banking.transfer`](tool-catalog-inventory.md#tool-banking-transfer), [`banking.open_savings`](tool-catalog-inventory.md#tool-banking-open_savings), [`ewallet.get_balance`](tool-catalog-inventory.md#tool-ewallet-get_balance), [`ewallet.transfer`](tool-catalog-inventory.md#tool-ewallet-transfer), [`ewallet.topup_mobile`](tool-catalog-inventory.md#tool-ewallet-topup_mobile), [`ewallet.pay_qr`](tool-catalog-inventory.md#tool-ewallet-pay_qr), [`bill_payment.list_bills`](tool-catalog-inventory.md#tool-bill_payment-list_bills), [`bill_payment.pay`](tool-catalog-inventory.md#tool-bill_payment-pay), [`bill_payment.schedule_autopay`](tool-catalog-inventory.md#tool-bill_payment-schedule_autopay).

## D06 — Điểm thưởng và gói định kỳ

Đổi ưu đãi và quản lý gói dịch vụ đã có.

- App: `loyalty`, `subscriptions`.
- Số tool hợp: **5**; Train: 5; Public Test: 0.
- Ý định chính: Xem điểm/voucher; đổi thưởng; huỷ gói định kỳ.
- Phụ thuộc thường gặp: get_points trả programs/rewards → redeem; subscriptions.list → cancel. Không có tool áp voucher khi checkout.
- Tool và chứng cứ: [`loyalty.list_vouchers`](tool-catalog-inventory.md#tool-loyalty-list_vouchers), [`loyalty.get_points`](tool-catalog-inventory.md#tool-loyalty-get_points), [`loyalty.redeem`](tool-catalog-inventory.md#tool-loyalty-redeem), [`subscriptions.list`](tool-catalog-inventory.md#tool-subscriptions-list), [`subscriptions.cancel`](tool-catalog-inventory.md#tool-subscriptions-cancel).

## D07 — Tra cứu thông tin và tin tức

Dữ liệu mô phỏng thời tiết, giá, tỷ giá, xổ số và bài báo.

- App: `weather`, `gold_price`, `fuel_price`, `lottery`, `exchange_rate`, `news`.
- Số tool hợp: **11**; Train: 11; Public Test: 4.
- Ý định chính: Hỏi thời tiết/giá/tỷ giá; dò vé; tìm và lưu tin.
- Phụ thuộc thường gặp: Tra cứu thường một tool; news.headlines/search → article_id → save; thời tiết có thể làm điều kiện cho D01.
- Tool và chứng cứ: [`weather.get_current`](tool-catalog-inventory.md#tool-weather-get_current), [`weather.get_forecast`](tool-catalog-inventory.md#tool-weather-get_forecast), [`gold_price.get_price`](tool-catalog-inventory.md#tool-gold_price-get_price), [`fuel_price.get_price`](tool-catalog-inventory.md#tool-fuel_price-get_price), [`lottery.get_results`](tool-catalog-inventory.md#tool-lottery-get_results), [`lottery.check_ticket`](tool-catalog-inventory.md#tool-lottery-check_ticket), [`exchange_rate.get_rate`](tool-catalog-inventory.md#tool-exchange_rate-get_rate), [`exchange_rate.convert`](tool-catalog-inventory.md#tool-exchange_rate-convert), [`news.headlines`](tool-catalog-inventory.md#tool-news-headlines), [`news.search`](tool-catalog-inventory.md#tool-news-search), [`news.save`](tool-catalog-inventory.md#tool-news-save).

## D08 — Di chuyển và địa điểm

Bản đồ, xe công nghệ, xe đạp, vận tải công cộng và chỗ đỗ.

- App: `maps`, `ride_hailing`, `bike_rental`, `public_transit`, `parking`.
- Số tool hợp: **16**; Train: 9; Public Test: 14.
- Ý định chính: Tìm đường; đặt/huỷ xe; thuê xe đạp; tìm tuyến; đặt chỗ đỗ.
- Phụ thuộc thường gặp: search_place → địa chỉ/place_id; get_ride → ride_id; find_bikes → bike_id; parking.find → lot_id; list_sessions → session_id.
- Tool và chứng cứ: [`maps.search_place`](tool-catalog-inventory.md#tool-maps-search_place), [`maps.get_route`](tool-catalog-inventory.md#tool-maps-get_route), [`maps.save_place`](tool-catalog-inventory.md#tool-maps-save_place), [`ride_hailing.get_quotes`](tool-catalog-inventory.md#tool-ride_hailing-get_quotes), [`ride_hailing.book`](tool-catalog-inventory.md#tool-ride_hailing-book), [`ride_hailing.cancel`](tool-catalog-inventory.md#tool-ride_hailing-cancel), [`ride_hailing.get_ride`](tool-catalog-inventory.md#tool-ride_hailing-get_ride), [`bike_rental.find_bikes`](tool-catalog-inventory.md#tool-bike_rental-find_bikes), [`bike_rental.reserve`](tool-catalog-inventory.md#tool-bike_rental-reserve), [`public_transit.find_routes`](tool-catalog-inventory.md#tool-public_transit-find_routes), [`public_transit.next_departures`](tool-catalog-inventory.md#tool-public_transit-next_departures), [`public_transit.topup_card`](tool-catalog-inventory.md#tool-public_transit-topup_card), [`parking.find`](tool-catalog-inventory.md#tool-parking-find), [`parking.list_sessions`](tool-catalog-inventory.md#tool-parking-list_sessions), [`parking.reserve`](tool-catalog-inventory.md#tool-parking-reserve), [`parking.end_session`](tool-catalog-inventory.md#tool-parking-end_session).

## D09 — Vé di chuyển liên tỉnh

Chuyến bay và vé tàu/xe khách.

- App: `flights`, `train_bus_tickets`.
- Số tool hợp: **9**; Train: 5; Public Test: 9.
- Ý định chính: Tìm/đặt/huỷ vé; làm thủ tục bay.
- Phụ thuộc thường gặp: Search → flight_id/trip_id; my_bookings → booking_id. Hai loại ID không hoán đổi.
- Tool và chứng cứ: [`flights.search`](tool-catalog-inventory.md#tool-flights-search), [`flights.book`](tool-catalog-inventory.md#tool-flights-book), [`flights.my_bookings`](tool-catalog-inventory.md#tool-flights-my_bookings), [`flights.cancel`](tool-catalog-inventory.md#tool-flights-cancel), [`flights.check_in`](tool-catalog-inventory.md#tool-flights-check_in), [`train_bus_tickets.search`](tool-catalog-inventory.md#tool-train_bus_tickets-search), [`train_bus_tickets.book`](tool-catalog-inventory.md#tool-train_bus_tickets-book), [`train_bus_tickets.my_bookings`](tool-catalog-inventory.md#tool-train_bus_tickets-my_bookings), [`train_bus_tickets.cancel`](tool-catalog-inventory.md#tool-train_bus_tickets-cancel).

## D10 — Ăn uống và tủ bếp

Đặt món, công thức và ghi nhận nguyên liệu đã dùng.

- App: `food_delivery`, `recipes`, `pantry`.
- Số tool hợp: **10**; Train: 5; Public Test: 10.
- Ý định chính: Chọn quán/món; huỷ đơn; tra công thức; ghi giảm đồ bếp.
- Phụ thuộc thường gặp: Quán → menu → items; recipes.search → recipe_id; pantry.list_items → item_id; nguyên liệu có thể nối D11.
- Tool và chứng cứ: [`food_delivery.list_restaurants`](tool-catalog-inventory.md#tool-food_delivery-list_restaurants), [`food_delivery.get_menu`](tool-catalog-inventory.md#tool-food_delivery-get_menu), [`food_delivery.order_history`](tool-catalog-inventory.md#tool-food_delivery-order_history), [`food_delivery.place_order`](tool-catalog-inventory.md#tool-food_delivery-place_order), [`food_delivery.cancel_order`](tool-catalog-inventory.md#tool-food_delivery-cancel_order), [`recipes.search`](tool-catalog-inventory.md#tool-recipes-search), [`recipes.get`](tool-catalog-inventory.md#tool-recipes-get), [`recipes.save`](tool-catalog-inventory.md#tool-recipes-save), [`pantry.list_items`](tool-catalog-inventory.md#tool-pantry-list_items), [`pantry.consume`](tool-catalog-inventory.md#tool-pantry-consume).

## D11 — Mua sắm và giao nhận

Danh sách mua, giỏ hàng, hậu mãi và vận đơn.

- App: `shopping_list`, `package_tracking`, `ecommerce`, `grocery`.
- Số tool hợp: **16**; Train: 7; Public Test: 13.
- Ý định chính: Thêm/check món; đặt hàng; huỷ/trả hàng; hẹn giao/lấy hàng.
- Phụ thuộc thường gặp: Search → product_id → cart → checkout; order_status → order_id; track → tracking_id; không đồng nhất ID giữa các app.
- Tool và chứng cứ: [`shopping_list.get`](tool-catalog-inventory.md#tool-shopping_list-get), [`shopping_list.add`](tool-catalog-inventory.md#tool-shopping_list-add), [`shopping_list.remove`](tool-catalog-inventory.md#tool-shopping_list-remove), [`shopping_list.check`](tool-catalog-inventory.md#tool-shopping_list-check), [`package_tracking.track`](tool-catalog-inventory.md#tool-package_tracking-track), [`package_tracking.reschedule_delivery`](tool-catalog-inventory.md#tool-package_tracking-reschedule_delivery), [`package_tracking.schedule_pickup`](tool-catalog-inventory.md#tool-package_tracking-schedule_pickup), [`grocery.search`](tool-catalog-inventory.md#tool-grocery-search), [`grocery.add_to_cart`](tool-catalog-inventory.md#tool-grocery-add_to_cart), [`grocery.checkout`](tool-catalog-inventory.md#tool-grocery-checkout), [`ecommerce.search`](tool-catalog-inventory.md#tool-ecommerce-search), [`ecommerce.order_status`](tool-catalog-inventory.md#tool-ecommerce-order_status), [`ecommerce.add_to_cart`](tool-catalog-inventory.md#tool-ecommerce-add_to_cart), [`ecommerce.checkout`](tool-catalog-inventory.md#tool-ecommerce-checkout), [`ecommerce.cancel_order`](tool-catalog-inventory.md#tool-ecommerce-cancel_order), [`ecommerce.request_return`](tool-catalog-inventory.md#tool-ecommerce-request_return).

## D12 — Giải trí và vé sự kiện

Nhạc, podcast/radio, TV và sự kiện.

- App: `music`, `tv`, `podcast_radio`, `event_tickets`.
- Số tool hợp: **14**; Train: 12; Public Test: 10.
- Ý định chính: Phát nội dung; sửa playlist; chuyển/ghi kênh; đặt vé sự kiện.
- Phụ thuộc thường gặp: Thư viện/search/guide → ID/channels → phát/ghi/đặt; điều khiển pause/volume thường trực tiếp.
- Tool và chứng cứ: [`music.list_tracks`](tool-catalog-inventory.md#tool-music-list_tracks), [`music.play`](tool-catalog-inventory.md#tool-music-play), [`music.control`](tool-catalog-inventory.md#tool-music-control), [`music.add_to_playlist`](tool-catalog-inventory.md#tool-music-add_to_playlist), [`tv.guide`](tool-catalog-inventory.md#tool-tv-guide), [`tv.tune`](tool-catalog-inventory.md#tool-tv-tune), [`tv.control`](tool-catalog-inventory.md#tool-tv-control), [`tv.record`](tool-catalog-inventory.md#tool-tv-record), [`podcast_radio.search`](tool-catalog-inventory.md#tool-podcast_radio-search), [`podcast_radio.play`](tool-catalog-inventory.md#tool-podcast_radio-play), [`podcast_radio.subscribe`](tool-catalog-inventory.md#tool-podcast_radio-subscribe), [`podcast_radio.queue`](tool-catalog-inventory.md#tool-podcast_radio-queue), [`event_tickets.search`](tool-catalog-inventory.md#tool-event_tickets-search), [`event_tickets.book`](tool-catalog-inventory.md#tool-event_tickets-book).

## D13 — Sức khoẻ và thói quen

Ghi lịch thuốc, hoạt động và thói quen do người dùng chỉ định.

- App: `medication`, `fitness`, `habit_tracker`.
- Số tool hợp: **9**; Train: 7; Public Test: 2.
- Ý định chính: Ghi đã uống/đã tập; đổi mục tiêu; đánh dấu thói quen.
- Phụ thuộc thường gặp: List lịch/habit → ID; fitness.get_activity dùng cho yêu cầu có điều kiện. Không có khả năng tư vấn liều thuốc.
- Tool và chứng cứ: [`medication.list`](tool-catalog-inventory.md#tool-medication-list), [`medication.add`](tool-catalog-inventory.md#tool-medication-add), [`medication.log_taken`](tool-catalog-inventory.md#tool-medication-log_taken), [`medication.remove`](tool-catalog-inventory.md#tool-medication-remove), [`fitness.get_activity`](tool-catalog-inventory.md#tool-fitness-get_activity), [`fitness.log_workout`](tool-catalog-inventory.md#tool-fitness-log_workout), [`fitness.set_goal`](tool-catalog-inventory.md#tool-fitness-set_goal), [`habit_tracker.list_habits`](tool-catalog-inventory.md#tool-habit_tracker-list_habits), [`habit_tracker.log`](tool-catalog-inventory.md#tool-habit_tracker-log).

## D14 — Học tập và thư viện

Khoá học, tiến độ và giữ sách.

- App: `learning`, `library`.
- Số tool hợp: **6**; Train: 6; Public Test: 0.
- Ý định chính: Đăng ký/lên lịch học; ghi tiến độ; tìm và giữ sách.
- Phụ thuộc thường gặp: list_courses → course_id/enrolled; library.search → book_id.
- Tool và chứng cứ: [`learning.list_courses`](tool-catalog-inventory.md#tool-learning-list_courses), [`learning.enroll`](tool-catalog-inventory.md#tool-learning-enroll), [`learning.schedule_lesson`](tool-catalog-inventory.md#tool-learning-schedule_lesson), [`learning.log_progress`](tool-catalog-inventory.md#tool-learning-log_progress), [`library.search`](tool-catalog-inventory.md#tool-library-search), [`library.reserve`](tool-catalog-inventory.md#tool-library-reserve).

## D15 — Tiện ích tính toán và ngôn ngữ

Phép tính, đổi đơn vị và dịch văn bản.

- App: `calculator`, `translator`.
- Số tool hợp: **3**; Train: 2; Public Test: 1.
- Ý định chính: Tính toán; đổi đơn vị; dịch câu để đọc hoặc gửi.
- Phụ thuộc thường gặp: Các yêu cầu đơn thường một tool; translation có thể làm nội dung gửi tại D04, là suy luận phối hợp.
- Tool và chứng cứ: [`calculator.calculate`](tool-catalog-inventory.md#tool-calculator-calculate), [`calculator.convert_unit`](tool-catalog-inventory.md#tool-calculator-convert_unit), [`translator.translate`](tool-catalog-inventory.md#tool-translator-translate).

## D16 — Chứng khoán mô phỏng

Báo giá, danh mục, lệnh và cảnh báo giá.

- App: `stocks`.
- Số tool hợp: **4**; Train: 0; Public Test: 4.
- Ý định chính: Xem mã/danh mục; đặt lệnh theo điều kiện; đặt cảnh báo.
- Phụ thuộc thường gặp: get_quote/portfolio → kiểm tra điều kiện → place_order hoặc set_price_alert; không mặc định cần đọc trước mọi lệnh.
- Tool và chứng cứ: [`stocks.get_quote`](tool-catalog-inventory.md#tool-stocks-get_quote), [`stocks.get_portfolio`](tool-catalog-inventory.md#tool-stocks-get_portfolio), [`stocks.place_order`](tool-catalog-inventory.md#tool-stocks-place_order), [`stocks.set_price_alert`](tool-catalog-inventory.md#tool-stocks-set_price_alert).

## D17 — Điều phối thông tin thiếu

Cơ chế meta dùng chung cho mọi nghiệp vụ.

- App: `sys`.
- Số tool hợp: **1**; Train: 1; Public Test: 1.
- Ý định chính: Báo thiếu tham số cần thiết để tiếp tục.
- Phụ thuộc thường gặp: Chỉ hỏi sau khi tận dụng dữ kiện sẵn có và các tool đọc phù hợp; không sinh thêm câu trả lời người dùng.
- Tool và chứng cứ: [`sys.ask_missing_info`](tool-catalog-inventory.md#tool-sys-ask_missing_info).

## Công cụ dùng chung giữa nhiều miền

| Tool | Miền chính → miền dùng lại | Vai trò / mức chứng cứ |
| --- | --- | --- |
| sys.ask_missing_info | D17 → mọi miền | Meta luôn có; chỉ báo thiếu tham số của tool đích. E: README, executor và sys.py. |
| contacts.search, contacts.get | D04 → D05, D03 | Recipient cho ewallet là E qua x-ref; attendees/email từ contact là S, phải đúng cấu trúc đối số. |
| food_delivery.list_restaurants | D10 → D05 | E: merchant_id cho ewallet.pay_qr được nêu trong catalog. |
| ewallet.get_balance | D05 → D10, D11 (khi yêu cầu có điều kiện số dư) | Đọc có thể hỗ trợ quyết định; payment=ewallet của order không chứng minh tự trừ ví. Không thêm transfer/pay_qr mặc định. |
| maps.search_place, maps.get_route | D08 → D09, D03, D12 | S: địa chỉ/ETA phục vụ chuyến, nhắc giờ, đến sự kiện. Không có ánh xạ ID trực tiếp. |
| calendar.list_events | D03 → D04, D08 | S: giờ/địa điểm thành nội dung tin hoặc điểm đến. |
| weather.get_current, weather.get_forecast | D07 → D01, D08 | S: đọc điều kiện hiện tại/dự báo rồi quyết định; không phải engine tự động chạy tương lai. |
| shopping_list.add, grocery.search | D11 → D10 | S/H: nguyên liệu thiếu sang hàng cần mua; kiểm đơn vị/đóng gói, không dùng recipe_id làm product_id. |
| translator.translate | D15 → D04 | S: translation dùng làm nội dung gửi nếu người dùng yêu cầu. |
| calculator.calculate, calculator.convert_unit | D15 → D01, D05, D10 | S: chỉ khi cần phép tính/đơn vị không xử lý chắc từ dữ kiện; kiểm đơn vị hỗ trợ, không thêm call cho mọi phép tính. |

E/S/H được định nghĩa trong [workflow-analysis.md](workflow-analysis.md). Chưa đo số lần đồng cài hoặc tần suất các yêu cầu liên miền; đây là khả năng phối hợp từ catalog, không phải thống kê tập test.
