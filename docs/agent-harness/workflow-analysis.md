# Phân tích workflow và phụ thuộc

Ngày phân tích: 10/11/2026. Base: `e216ad5115229598149ca8c4e3f43554ce065268` (nhánh `codex/009-cross-step-kv-cache`). Chỉ nghiên cứu tĩnh; không chạy tool trên mẫu, GPU, inference, retrieval hay skill thực thi.

Review từ `dfbaa0416a45c25e402c98594ea63f5c220f8042`: giữ nguyên ID, công cụ, dependency và phân loại E/S/H của cả 37 workflow; chỉ tái phân loại W36 sang SC01. Thư viện nay có 24 nhóm skill / 80 nhánh, xem [candidate-skills.md](candidate-skills.md).

Có **37 họ workflow** (một họ có thể có các nhánh loại trừ); không đếm mỗi chuỗi biến thể như một workflow độc lập.

## Mức chứng cứ và quy ước

- **E — tường minh:** mô tả tham số/tool nêu nguồn ID hoặc thứ tự, `x-ref` xác định bộ sưu tập, hoặc mã mô phỏng xác nhận điều kiện. X-ref không đồng nghĩa luôn bắt buộc gọi lại tool đọc nếu ID đã có từ dữ kiện hợp lệ.
- **S — suy luận:** kết nối trường trả về với đối số/điều kiện của tool khác; chưa có hợp đồng workflow hay đo chạy end-to-end.
- **H — giả thuyết cần xác minh:** có tool thành phần, nhưng còn thiếu ánh xạ/đơn vị/địa chỉ hoặc giả định để hoàn tất. Không tuyên bố đã hỗ trợ trọn vẹn.

Mức của họ là mức yếu nhất trong đường phối hợp chính; các cạnh mạnh hơn được ghi riêng. Tập tool mỗi họ là hợp các nhánh, **không phải tất cả đều bắt buộc trong một lần chạy**. Có thể bỏ bước đọc khi thông tin đã đủ, trừ chỉ dẫn rõ như `tv.guide` trước `tv.tune`. Mọi nhánh chỉ chạy khi tên tool có trong tập eligible của mẫu. Các bước độc lập không có thứ tự cứng; planner vẫn thực thi tuần tự.

| ID | Ý định / workflow | Miền | Mức |
| --- | --- | --- | --- |
| W01 | Điều khiển thiết bị theo phòng/tầng | D01 | E |
| W02 | Chạy cảnh nhà đã lưu | D01 | E |
| W03 | Chạy robot hoặc chu trình gia dụng | D01 | E |
| W04 | Lập/xoá quy tắc thiết bị hằng ngày | D01 | E |
| W05 | Phân công việc nhà | D01 | E |
| W06 | Xử lý cảnh báo và khoá cửa | D02 | E |
| W07 | Sửa/hoàn thành bản ghi cá nhân | D03 | E |
| W08 | Tìm người rồi gọi, nhắn hoặc sửa danh bạ | D04 | E |
| W09 | Chọn cuộc chat và thao tác OTT | D04 | E |
| W10 | Đọc và xử lý email có sẵn | D04 | E |
| W11 | Tham gia hoặc tạo phòng họp | D04 | E |
| W12 | Chuyển khoản hoặc gửi tiết kiệm | D05 | E |
| W13 | Chuyển ví, nạp điện thoại hoặc trả QR | D05, D04, D10 | E |
| W14 | Trả hoá đơn và kiểm tra nguồn ví | D05 | E |
| W15 | Đổi thưởng hoặc huỷ gói định kỳ | D06 | E |
| W16 | Tìm và lưu bài báo | D07 | E |
| W17 | Chọn điểm đến và đặt/huỷ xe | D08 | S |
| W18 | Thuê xe đạp hoặc đặt/kết thúc chỗ đỗ | D08 | E |
| W19 | Tìm tuyến công cộng hoặc nạp thẻ | D08 | S |
| W20 | Đặt, huỷ hoặc check-in vé liên tỉnh | D09 | E |
| W21 | Đặt hoặc huỷ món giao tận nơi | D10 | E |
| W22 | Công thức, tủ bếp và danh sách cần mua | D10, D11 | H |
| W23 | Tìm hàng, thêm giỏ và checkout | D11 | E |
| W24 | Huỷ đơn hoặc trả hàng online | D11 | E |
| W25 | Cập nhật danh sách mua hoặc lịch giao nhận | D11 | E |
| W26 | Chọn nội dung nghe và quản lý thư viện | D12 | E |
| W27 | Chọn kênh hoặc ghi hình TV | D12 | E |
| W28 | Đặt vé sự kiện | D12 | E |
| W29 | Ghi lịch thuốc, vận động hoặc thói quen | D13 | E |
| W30 | Đăng ký/lên lịch học hoặc giữ sách | D14 | E |
| W31 | Lệnh/cảnh báo chứng khoán theo điều kiện | D16 | S |
| W32 | Xem lịch rồi báo qua liên lạc | D03, D04 | S |
| W33 | Theo thời tiết rồi điều khiển nhà | D07, D01 | S |
| W34 | Vé, thời gian di chuyển và nhắc/đặt xe | D09, D08, D03 | H |
| W35 | Dịch nội dung rồi gửi | D15, D04 | S |
| W36 | Dừng tại thông tin bắt buộc còn thiếu | SC01 (hệ thống) | E |
| W37 | Đặt ngưỡng điện năng từ số liệu | D01 | S |

<a id="w01"></a>

## W01 — Điều khiển thiết bị theo phòng/tầng

- Miền: D01; mức: **E**.
- Ý định: Điều khiển thiết bị theo phòng/tầng.
- Tool cần theo nhánh: `smart_home.get_status`, `smart_home.light_set`, `smart_home.fan_set`, `smart_home.climate_set`, `smart_home.switch_set`.
- Thứ tự điển hình: get_status với bộ lọc cần thiết → chọn devices[] → gọi setter đúng type cho từng thiết bị được yêu cầu.
- Dữ liệu trung gian: devices[].id/type/room/floor và trạng thái.
- Điều kiện/quyết định: Có thể nhiều thiết bị cùng phòng; chỉ thao tác phạm vi người dùng nói. climate_set bắt buộc mode.
- Xử lý thiếu: Thiếu device_id sau tra cứu hoặc thiếu mode thì hỏi đúng tham số của setter.
- Điều kiện hoàn tất: Kết quả setter phản ánh các thuộc tính cần đổi; done:false không đạt.
- Chứng cứ catalog: [`smart_home.get_status`](tool-catalog-inventory.md#tool-smart_home-get_status), [`smart_home.light_set`](tool-catalog-inventory.md#tool-smart_home-light_set), [`smart_home.fan_set`](tool-catalog-inventory.md#tool-smart_home-fan_set), [`smart_home.climate_set`](tool-catalog-inventory.md#tool-smart_home-climate_set), [`smart_home.switch_set`](tool-catalog-inventory.md#tool-smart_home-switch_set).
- Chứng cứ mã, đúng split: [train/apps/smart_home.py:11](../../tools/train/apps/smart_home.py#L11); [train/apps/smart_home.py:18](../../tools/train/apps/smart_home.py#L18); [train/apps/smart_home.py:22](../../tools/train/apps/smart_home.py#L22); [train/apps/smart_home.py:26](../../tools/train/apps/smart_home.py#L26); [train/apps/smart_home.py:30](../../tools/train/apps/smart_home.py#L30).
- Giới hạn/chú giải: Mô tả và x-ref ghi rõ nguồn device_id; không tạo lệnh cho mọi loại thiết bị.

<a id="w02"></a>

## W02 — Chạy cảnh nhà đã lưu

- Miền: D01; mức: **E**.
- Ý định: Chạy cảnh nhà đã lưu.
- Tool cần theo nhánh: `smart_home.get_status`, `smart_home.scene_run`.
- Thứ tự điển hình: get_status không lọc → chọn scenes[] → scene_run.
- Dữ liệu trung gian: scenes[].id và tên cảnh.
- Điều kiện/quyết định: Bộ lọc có thể không trả scenes; không suy tên cảnh thành ID.
- Xử lý thiếu: Thiếu scene_id hoặc không phân biệt được cảnh → hỏi scene_id.
- Điều kiện hoàn tất: Kết quả scene_run thành công theo nội dung trả về.
- Chứng cứ catalog: [`smart_home.get_status`](tool-catalog-inventory.md#tool-smart_home-get_status), [`smart_home.scene_run`](tool-catalog-inventory.md#tool-smart_home-scene_run).
- Chứng cứ mã, đúng split: [train/apps/smart_home.py:11](../../tools/train/apps/smart_home.py#L11); [train/apps/smart_home.py:34](../../tools/train/apps/smart_home.py#L34).

<a id="w03"></a>

## W03 — Chạy robot hoặc chu trình gia dụng

- Miền: D01; mức: **E**.
- Ý định: Chạy robot hoặc chu trình gia dụng.
- Tool cần theo nhánh: `robot_vacuum.get_status`, `robot_vacuum.start`, `robot_vacuum.stop`, `appliances.list`, `appliances.start_cycle`, `appliances.stop`.
- Thứ tự điển hình: Nhánh robot: get_status → start khi cần kiểm tra phòng/pin. Nhánh gia dụng: list → chọn appliance/cycle → start_cycle; stop chỉ khi cần theo yêu cầu.
- Dữ liệu trung gian: Tên rooms; battery; appliance.id, cycles, state.status.
- Điều kiện/quyết định: Robot cần pin ≥15%; thiết bị đang running/scheduled không khởi chạy chu trình khác. Đây là nhánh, không phải chuỗi dùng cả hai app.
- Xử lý thiếu: Hỏi appliance_id/cycle nếu chưa xác định; robot_vacuum.start không có required nên không tự đặt trường bắt buộc mới.
- Điều kiện hoàn tất: Robot cleaning/current_job hoặc appliance running/scheduled đúng yêu cầu.
- Chứng cứ catalog: [`robot_vacuum.get_status`](tool-catalog-inventory.md#tool-robot_vacuum-get_status), [`robot_vacuum.start`](tool-catalog-inventory.md#tool-robot_vacuum-start), [`robot_vacuum.stop`](tool-catalog-inventory.md#tool-robot_vacuum-stop), [`appliances.list`](tool-catalog-inventory.md#tool-appliances-list), [`appliances.start_cycle`](tool-catalog-inventory.md#tool-appliances-start_cycle), [`appliances.stop`](tool-catalog-inventory.md#tool-appliances-stop).
- Chứng cứ mã, đúng split: [train/apps/robot_vacuum.py:17](../../tools/train/apps/robot_vacuum.py#L17); [train/apps/robot_vacuum.py:23](../../tools/train/apps/robot_vacuum.py#L23); [train/apps/robot_vacuum.py:42](../../tools/train/apps/robot_vacuum.py#L42); [train/apps/appliances.py:12](../../tools/train/apps/appliances.py#L12); [train/apps/appliances.py:16](../../tools/train/apps/appliances.py#L16); [train/apps/appliances.py:32](../../tools/train/apps/appliances.py#L32).
- Giới hạn/chú giải: Mã robot_vacuum.start và appliances.start_cycle bổ sung điều kiện ngoài schema.

<a id="w04"></a>

## W04 — Lập/xoá quy tắc thiết bị hằng ngày

- Miền: D01; mức: **E**.
- Ý định: Lập/xoá quy tắc thiết bị hằng ngày.
- Tool cần theo nhánh: `smart_home.get_status`, `home_automation.create_rule`, `home_automation.list_rules`, `home_automation.delete_rule`.
- Thứ tự điển hình: Tạo: get_status → chọn device_id → create_rule; xoá: list_rules → delete_rule.
- Dữ liệu trung gian: device_id hoặc rule_id; action; time HH:MM.
- Điều kiện/quyết định: Chỉ quy tắc giờ cố định hằng ngày on/off; không có trigger cảm biến hoặc thời tiết.
- Xử lý thiếu: Thiếu action/time/device_id hoặc rule_id chưa phân giải → ask_missing_info.
- Điều kiện hoàn tất: Trả rule với enabled hoặc xoá đúng rule.
- Chứng cứ catalog: [`smart_home.get_status`](tool-catalog-inventory.md#tool-smart_home-get_status), [`home_automation.create_rule`](tool-catalog-inventory.md#tool-home_automation-create_rule), [`home_automation.list_rules`](tool-catalog-inventory.md#tool-home_automation-list_rules), [`home_automation.delete_rule`](tool-catalog-inventory.md#tool-home_automation-delete_rule).
- Chứng cứ mã, đúng split: [train/apps/smart_home.py:11](../../tools/train/apps/smart_home.py#L11); [train/apps/home_automation.py:15](../../tools/train/apps/home_automation.py#L15); [train/apps/home_automation.py:11](../../tools/train/apps/home_automation.py#L11); [train/apps/home_automation.py:26](../../tools/train/apps/home_automation.py#L26).

<a id="w05"></a>

## W05 — Phân công việc nhà

- Miền: D01; mức: **E**.
- Ý định: Phân công việc nhà.
- Tool cần theo nhánh: `household_chores.list_chores`, `household_chores.assign`.
- Thứ tự điển hình: list_chores → chọn việc và thành viên → assign.
- Dữ liệu trung gian: chores[].id; members[] chính xác.
- Điều kiện/quyết định: assignee phải là một tên có trong members.
- Xử lý thiếu: Thiếu chore_id/assignee sau khi đọc thì hỏi.
- Điều kiện hoàn tất: Bản ghi việc có người phụ trách đúng.
- Chứng cứ catalog: [`household_chores.list_chores`](tool-catalog-inventory.md#tool-household_chores-list_chores), [`household_chores.assign`](tool-catalog-inventory.md#tool-household_chores-assign).
- Chứng cứ mã, đúng split: [train/apps/household_chores.py:12](../../tools/train/apps/household_chores.py#L12); [train/apps/household_chores.py:16](../../tools/train/apps/household_chores.py#L16).

<a id="w06"></a>

## W06 — Xử lý cảnh báo và khoá cửa

- Miền: D02; mức: **E**.
- Ý định: Xử lý cảnh báo và khoá cửa.
- Tool cần theo nhánh: `home_security.list_alerts`, `home_security.acknowledge_alert`, `home_security.get_camera`, `home_security.arm`, `door_lock.list_locks`, `door_lock.set_lock`, `door_lock.grant_guest_code`.
- Thứ tự điển hình: Nhánh cảnh báo: list_alerts → acknowledge_alert. Nhánh khoá: list_locks → set_lock hoặc grant_guest_code. get_camera/arm chỉ khi có ý định tương ứng.
- Dữ liệu trung gian: alert_id; lock_id; valid_until có múi giờ; mode.
- Điều kiện/quyết định: Xem camera không tự cho phép mở khoá; cấp mã không đồng nghĩa gửi mã.
- Xử lý thiếu: Thiếu lock_id/valid_until, alert_id hoặc mode chưa xác định → hỏi tool đích.
- Điều kiện hoàn tất: Kết quả thay đổi đúng khoá/cảnh báo hoặc guest_code được trả.
- Chứng cứ catalog: [`home_security.list_alerts`](tool-catalog-inventory.md#tool-home_security-list_alerts), [`home_security.acknowledge_alert`](tool-catalog-inventory.md#tool-home_security-acknowledge_alert), [`home_security.get_camera`](tool-catalog-inventory.md#tool-home_security-get_camera), [`home_security.arm`](tool-catalog-inventory.md#tool-home_security-arm), [`door_lock.list_locks`](tool-catalog-inventory.md#tool-door_lock-list_locks), [`door_lock.set_lock`](tool-catalog-inventory.md#tool-door_lock-set_lock), [`door_lock.grant_guest_code`](tool-catalog-inventory.md#tool-door_lock-grant_guest_code).
- Chứng cứ mã, đúng split: [train/apps/home_security.py:21](../../tools/train/apps/home_security.py#L21); [train/apps/home_security.py:41](../../tools/train/apps/home_security.py#L41); [train/apps/home_security.py:32](../../tools/train/apps/home_security.py#L32); [train/apps/home_security.py:36](../../tools/train/apps/home_security.py#L36); [train/apps/door_lock.py:14](../../tools/train/apps/door_lock.py#L14); [train/apps/door_lock.py:18](../../tools/train/apps/door_lock.py#L18); [train/apps/door_lock.py:24](../../tools/train/apps/door_lock.py#L24).

<a id="w07"></a>

## W07 — Sửa/hoàn thành bản ghi cá nhân

- Miền: D03; mức: **E**.
- Ý định: Sửa/hoàn thành bản ghi cá nhân.
- Tool cần theo nhánh: `alarm.list`, `alarm.update`, `alarm.delete`, `reminders.list`, `reminders.complete`, `reminders.delete`, `calendar.list_events`, `calendar.update_event`, `calendar.cancel_event`, `notes.list`, `notes.append`, `tasks.list`, `tasks.complete`.
- Thứ tự điển hình: Chọn app theo loại đối tượng → list phù hợp → lọc bản ghi → update/delete/complete/append.
- Dữ liệu trung gian: alarm_id/reminder_id/event_id/note_id/task_id và trường cần thay đổi.
- Điều kiện/quyết định: Chỉ một nhánh app cho mỗi đối tượng; tạo mới đủ dữ kiện không phải chạy luồng này.
- Xử lý thiếu: ID còn mơ hồ hoặc thiếu content khi notes.append → hỏi đúng tham số.
- Điều kiện hoàn tất: Kết quả ghi/xoá/hoàn thành cho đúng bản ghi.
- Chứng cứ catalog: [`alarm.list`](tool-catalog-inventory.md#tool-alarm-list), [`alarm.update`](tool-catalog-inventory.md#tool-alarm-update), [`alarm.delete`](tool-catalog-inventory.md#tool-alarm-delete), [`reminders.list`](tool-catalog-inventory.md#tool-reminders-list), [`reminders.complete`](tool-catalog-inventory.md#tool-reminders-complete), [`reminders.delete`](tool-catalog-inventory.md#tool-reminders-delete), [`calendar.list_events`](tool-catalog-inventory.md#tool-calendar-list_events), [`calendar.update_event`](tool-catalog-inventory.md#tool-calendar-update_event), [`calendar.cancel_event`](tool-catalog-inventory.md#tool-calendar-cancel_event), [`notes.list`](tool-catalog-inventory.md#tool-notes-list), [`notes.append`](tool-catalog-inventory.md#tool-notes-append), [`tasks.list`](tool-catalog-inventory.md#tool-tasks-list), [`tasks.complete`](tool-catalog-inventory.md#tool-tasks-complete).
- Chứng cứ mã, đúng split: [train/apps/alarm.py:11](../../tools/train/apps/alarm.py#L11); [train/apps/alarm.py:19](../../tools/train/apps/alarm.py#L19); [train/apps/alarm.py:23](../../tools/train/apps/alarm.py#L23); [train/apps/reminders.py:11](../../tools/train/apps/reminders.py#L11); [train/apps/reminders.py:19](../../tools/train/apps/reminders.py#L19); [train/apps/reminders.py:23](../../tools/train/apps/reminders.py#L23); [train/apps/calendar.py:13](../../tools/train/apps/calendar.py#L13); [train/apps/calendar.py:26](../../tools/train/apps/calendar.py#L26); [train/apps/calendar.py:30](../../tools/train/apps/calendar.py#L30); [train/apps/notes.py:11](../../tools/train/apps/notes.py#L11); [train/apps/notes.py:19](../../tools/train/apps/notes.py#L19); [train/apps/tasks.py:11](../../tools/train/apps/tasks.py#L11); [train/apps/tasks.py:20](../../tools/train/apps/tasks.py#L20).

<a id="w08"></a>

## W08 — Tìm người rồi gọi, nhắn hoặc sửa danh bạ

- Miền: D04; mức: **E**.
- Ý định: Tìm người rồi gọi, nhắn hoặc sửa danh bạ.
- Tool cần theo nhánh: `contacts.search`, `contacts.get`, `contacts.update`, `phone.call`, `sms.send`, `email.send`.
- Thứ tự điển hình: Nếu chỉ có tên/quan hệ: search → chọn contact; get chỉ khi cần thêm chi tiết → call/send/update theo yêu cầu.
- Dữ liệu trung gian: contacts[].id, phone, email; content hoặc subject/body.
- Điều kiện/quyết định: Số điện thoại đã rõ cho phép gọi/SMS trực tiếp; email.send cần to dạng array, không phải contact_id.
- Xử lý thiếu: Thiếu một nhánh x-one-of recipient hoặc thiếu nội dung bắt buộc → hỏi theo schema tool đích.
- Điều kiện hoàn tất: Có kết quả cuộc gọi/tin gửi hoặc cập nhật liên hệ.
- Chứng cứ catalog: [`contacts.search`](tool-catalog-inventory.md#tool-contacts-search), [`contacts.get`](tool-catalog-inventory.md#tool-contacts-get), [`contacts.update`](tool-catalog-inventory.md#tool-contacts-update), [`phone.call`](tool-catalog-inventory.md#tool-phone-call), [`sms.send`](tool-catalog-inventory.md#tool-sms-send), [`email.send`](tool-catalog-inventory.md#tool-email-send).
- Chứng cứ mã, đúng split: [train/apps/contacts.py:11](../../tools/train/apps/contacts.py#L11); [train/apps/contacts.py:16](../../tools/train/apps/contacts.py#L16); [train/apps/contacts.py:20](../../tools/train/apps/contacts.py#L20); [train/apps/phone.py:11](../../tools/train/apps/phone.py#L11); [train/apps/sms.py:11](../../tools/train/apps/sms.py#L11); [train/apps/email.py:53](../../tools/train/apps/email.py#L53).
- Giới hạn/chú giải: Liên kết contacts sang email là S (ánh xạ email sang to), không phải x-ref của email.send.

<a id="w09"></a>

## W09 — Chọn cuộc chat và thao tác OTT

- Miền: D04; mức: **E**.
- Ý định: Chọn cuộc chat và thao tác OTT.
- Tool cần theo nhánh: `chat_ott.list_chats`, `chat_ott.read_chat`, `chat_ott.send_message`, `chat_ott.send_location`, `chat_ott.call`.
- Thứ tự điển hình: list_chats → chọn chat_id → read_chat nếu ý định cần nội dung → send_message/send_location/call.
- Dữ liệu trung gian: chats[].id; messages[] khi cần trích nội dung; content/video.
- Điều kiện/quyết định: Không thay chat_id bằng contact_id; send_location gửi vị trí hiện tại, không có đối số vị trí tuỳ ý.
- Xử lý thiếu: Thiếu chat_id/content cần hỏi; không cần hỏi tọa độ cho send_location.
- Điều kiện hoàn tất: Tin/vị trí/cuộc gọi được ghi đúng chat.
- Chứng cứ catalog: [`chat_ott.list_chats`](tool-catalog-inventory.md#tool-chat_ott-list_chats), [`chat_ott.read_chat`](tool-catalog-inventory.md#tool-chat_ott-read_chat), [`chat_ott.send_message`](tool-catalog-inventory.md#tool-chat_ott-send_message), [`chat_ott.send_location`](tool-catalog-inventory.md#tool-chat_ott-send_location), [`chat_ott.call`](tool-catalog-inventory.md#tool-chat_ott-call).
- Chứng cứ mã, đúng split: [train/apps/chat_ott.py:11](../../tools/train/apps/chat_ott.py#L11); [train/apps/chat_ott.py:15](../../tools/train/apps/chat_ott.py#L15); [train/apps/chat_ott.py:22](../../tools/train/apps/chat_ott.py#L22); [train/apps/chat_ott.py:31](../../tools/train/apps/chat_ott.py#L31); [train/apps/chat_ott.py:40](../../tools/train/apps/chat_ott.py#L40).

<a id="w10"></a>

## W10 — Đọc và xử lý email có sẵn

- Miền: D04; mức: **E**.
- Ý định: Đọc và xử lý email có sẵn.
- Tool cần theo nhánh: `email.list`, `email.read`, `email.reply`, `email.archive`, `email.create_draft`.
- Thứ tự điển hình: list → chọn email_id → read nếu nội dung cần thiết → reply hoặc archive; create_draft là nhánh riêng khi người dùng chỉ muốn nháp.
- Dữ liệu trung gian: email_id; nội dung email; body/action hoặc to/subject/body cho nháp.
- Điều kiện/quyết định: Không gửi nháp thành email; reply không bắt buộc read khi đã có đủ nội dung.
- Xử lý thiếu: Thiếu email_id/body/action hoặc trường nháp → hỏi tool đúng.
- Điều kiện hoàn tất: Reply/archive đúng email hoặc draft được trả, theo ý định.
- Chứng cứ catalog: [`email.list`](tool-catalog-inventory.md#tool-email-list), [`email.read`](tool-catalog-inventory.md#tool-email-read), [`email.reply`](tool-catalog-inventory.md#tool-email-reply), [`email.archive`](tool-catalog-inventory.md#tool-email-archive), [`email.create_draft`](tool-catalog-inventory.md#tool-email-create_draft).
- Chứng cứ mã, đúng split: [train/apps/email.py:29](../../tools/train/apps/email.py#L29); [train/apps/email.py:36](../../tools/train/apps/email.py#L36); [train/apps/email.py:61](../../tools/train/apps/email.py#L61); [train/apps/email.py:72](../../tools/train/apps/email.py#L72); [train/apps/email.py:57](../../tools/train/apps/email.py#L57).

<a id="w11"></a>

## W11 — Tham gia hoặc tạo phòng họp

- Miền: D04; mức: **E**.
- Ý định: Tham gia hoặc tạo phòng họp.
- Tool cần theo nhánh: `video_meeting.list_meetings`, `video_meeting.join`, `video_meeting.create`.
- Thứ tự điển hình: Tham gia: list_meetings → chọn meeting_id → join. Tạo: create trực tiếp nếu title/start đã đủ.
- Dữ liệu trung gian: meeting_id hoặc title/start/attendees.
- Điều kiện/quyết định: Không suy calendar.event_id thành meeting_id.
- Xử lý thiếu: Thiếu meeting_id/title/start → hỏi theo nhánh.
- Điều kiện hoàn tất: Đã join hoặc kết quả create phòng.
- Chứng cứ catalog: [`video_meeting.list_meetings`](tool-catalog-inventory.md#tool-video_meeting-list_meetings), [`video_meeting.join`](tool-catalog-inventory.md#tool-video_meeting-join), [`video_meeting.create`](tool-catalog-inventory.md#tool-video_meeting-create).
- Chứng cứ mã, đúng split: [train/apps/video_meeting.py:20](../../tools/train/apps/video_meeting.py#L20); [train/apps/video_meeting.py:37](../../tools/train/apps/video_meeting.py#L37); [train/apps/video_meeting.py:26](../../tools/train/apps/video_meeting.py#L26).

<a id="w12"></a>

## W12 — Chuyển khoản hoặc gửi tiết kiệm

- Miền: D05; mức: **E**.
- Ý định: Chuyển khoản hoặc gửi tiết kiệm.
- Tool cần theo nhánh: `banking.get_balance`, `banking.list_beneficiaries`, `banking.transfer`, `banking.open_savings`.
- Thứ tự điển hình: get_balance khi cần tài khoản/số dư; list_beneficiaries khi cần chọn người nhận → transfer. open_savings dùng tài khoản đã xác định.
- Dữ liệu trung gian: accounts[].id/balance; beneficiaries[].id; amount; term_months.
- Điều kiện/quyết định: Danh bạ không thay được beneficiary_id; không tự chọn kỳ hạn/nguồn tiền.
- Xử lý thiếu: Thiếu from_account_id/beneficiary_id/amount/term_months sau đọc → hỏi đúng tool.
- Điều kiện hoàn tất: Kết quả giao dịch/tiết kiệm thành công, không phải chỉ ok:true.
- Chứng cứ catalog: [`banking.get_balance`](tool-catalog-inventory.md#tool-banking-get_balance), [`banking.list_beneficiaries`](tool-catalog-inventory.md#tool-banking-list_beneficiaries), [`banking.transfer`](tool-catalog-inventory.md#tool-banking-transfer), [`banking.open_savings`](tool-catalog-inventory.md#tool-banking-open_savings).
- Chứng cứ mã, đúng split: [train/apps/banking.py:11](../../tools/train/apps/banking.py#L11); [train/apps/banking.py:19](../../tools/train/apps/banking.py#L19); [train/apps/banking.py:23](../../tools/train/apps/banking.py#L23); [train/apps/banking.py:36](../../tools/train/apps/banking.py#L36).

<a id="w13"></a>

## W13 — Chuyển ví, nạp điện thoại hoặc trả QR

- Miền: D05, D04, D10; mức: **E**.
- Ý định: Chuyển ví, nạp điện thoại hoặc trả QR.
- Tool cần theo nhánh: `ewallet.get_balance`, `contacts.search`, `ewallet.transfer`, `ewallet.topup_mobile`, `food_delivery.list_restaurants`, `ewallet.pay_qr`.
- Thứ tự điển hình: Chọn nhánh: tên người → contacts.search → transfer/topup_mobile; tên quán → list_restaurants → pay_qr. get_balance khi người dùng yêu cầu/điều kiện số dư cần kiểm tra.
- Dữ liệu trung gian: contact_id/phone; merchant_id của quán; amount; balance.
- Điều kiện/quyết định: pay_qr không dùng restaurant_id; topup_mobile dùng phone, phone.call dùng phone_number.
- Xử lý thiếu: Hỏi amount và recipient/merchant_id còn thiếu; không tự nạp thêm tiền ví vì không có tool đó.
- Điều kiện hoàn tất: Transaction và balance được trả; số dư thiếu gây done:false.
- Chứng cứ catalog: [`ewallet.get_balance`](tool-catalog-inventory.md#tool-ewallet-get_balance), [`contacts.search`](tool-catalog-inventory.md#tool-contacts-search), [`ewallet.transfer`](tool-catalog-inventory.md#tool-ewallet-transfer), [`ewallet.topup_mobile`](tool-catalog-inventory.md#tool-ewallet-topup_mobile), [`food_delivery.list_restaurants`](tool-catalog-inventory.md#tool-food_delivery-list_restaurants), [`ewallet.pay_qr`](tool-catalog-inventory.md#tool-ewallet-pay_qr).
- Chứng cứ mã, đúng split: [train/apps/ewallet.py:11](../../tools/train/apps/ewallet.py#L11); [train/apps/contacts.py:11](../../tools/train/apps/contacts.py#L11); [train/apps/ewallet.py:15](../../tools/train/apps/ewallet.py#L15); [train/apps/ewallet.py:26](../../tools/train/apps/ewallet.py#L26); [train/apps/food_delivery.py:11](../../tools/train/apps/food_delivery.py#L11); [train/apps/ewallet.py:35](../../tools/train/apps/ewallet.py#L35).

<a id="w14"></a>

## W14 — Trả hoá đơn và kiểm tra nguồn ví

- Miền: D05; mức: **E**.
- Ý định: Trả hoá đơn và kiểm tra nguồn ví.
- Tool cần theo nhánh: `bill_payment.list_bills`, `bill_payment.pay`, `ewallet.get_balance`, `bill_payment.schedule_autopay`.
- Thứ tự điển hình: list_bills → chọn bill_id → nếu điều kiện yêu cầu thì get_balance → pay với source; autopay là nhánh độc lập type/enabled.
- Dữ liệu trung gian: bills[].id/type/amount; source bank|ewallet.
- Điều kiện/quyết định: Nguồn ewallet thực sự trừ ví và cần app ví/số dư; nguồn bank trong mô phỏng không chọn/trừ banking.accounts.
- Xử lý thiếu: Thiếu bill_id/source hoặc type/enabled của autopay thì hỏi; không tự đổi nguồn tiền khi thiếu số dư.
- Điều kiện hoàn tất: Bill paid:true; hoặc autopay đúng enabled.
- Chứng cứ catalog: [`bill_payment.list_bills`](tool-catalog-inventory.md#tool-bill_payment-list_bills), [`bill_payment.pay`](tool-catalog-inventory.md#tool-bill_payment-pay), [`ewallet.get_balance`](tool-catalog-inventory.md#tool-ewallet-get_balance), [`bill_payment.schedule_autopay`](tool-catalog-inventory.md#tool-bill_payment-schedule_autopay).
- Chứng cứ mã, đúng split: [train/apps/bill_payment.py:12](../../tools/train/apps/bill_payment.py#L12); [train/apps/bill_payment.py:16](../../tools/train/apps/bill_payment.py#L16); [train/apps/ewallet.py:11](../../tools/train/apps/ewallet.py#L11); [train/apps/bill_payment.py:36](../../tools/train/apps/bill_payment.py#L36).
- Giới hạn/chú giải: Đã đọc bill_payment.pay của cả bản repo và bản dataset; không thêm banking.transfer vào chuỗi trả hoá đơn.

<a id="w15"></a>

## W15 — Đổi thưởng hoặc huỷ gói định kỳ

- Miền: D06; mức: **E**.
- Ý định: Đổi thưởng hoặc huỷ gói định kỳ.
- Tool cần theo nhánh: `loyalty.get_points`, `loyalty.list_vouchers`, `loyalty.redeem`, `subscriptions.list`, `subscriptions.cancel`.
- Thứ tự điển hình: Nhánh điểm: get_points → chọn program/rewards → redeem. Nhánh gói: subscriptions.list → chọn subscription_id → cancel.
- Dữ liệu trung gian: programs[].id/name/points/rewards[].id/cost; subscription_id/status.
- Điều kiện/quyết định: Không áp voucher vào đơn hàng vì tool đặt món/checkout không có voucher_id.
- Xử lý thiếu: Thiếu program/reward_id/subscription_id sau đọc → hỏi.
- Điều kiện hoàn tất: Voucher mới và điểm cập nhật hoặc gói đã huỷ.
- Chứng cứ catalog: [`loyalty.get_points`](tool-catalog-inventory.md#tool-loyalty-get_points), [`loyalty.list_vouchers`](tool-catalog-inventory.md#tool-loyalty-list_vouchers), [`loyalty.redeem`](tool-catalog-inventory.md#tool-loyalty-redeem), [`subscriptions.list`](tool-catalog-inventory.md#tool-subscriptions-list), [`subscriptions.cancel`](tool-catalog-inventory.md#tool-subscriptions-cancel).
- Chứng cứ mã, đúng split: [train/apps/loyalty.py:31](../../tools/train/apps/loyalty.py#L31); [train/apps/loyalty.py:27](../../tools/train/apps/loyalty.py#L27); [train/apps/loyalty.py:40](../../tools/train/apps/loyalty.py#L40); [train/apps/subscriptions.py:11](../../tools/train/apps/subscriptions.py#L11); [train/apps/subscriptions.py:15](../../tools/train/apps/subscriptions.py#L15).
- Giới hạn/chú giải: returns của get_points trong catalog ghi points[] nhưng mã trả programs[]; phải dựa kết quả thực nhận.

<a id="w16"></a>

## W16 — Tìm và lưu bài báo

- Miền: D07; mức: **E**.
- Ý định: Tìm và lưu bài báo.
- Tool cần theo nhánh: `news.headlines`, `news.search`, `news.save`.
- Thứ tự điển hình: headlines hoặc search → chọn article_id → save.
- Dữ liệu trung gian: articles[].id và tiêu đề/nội dung mô tả.
- Điều kiện/quyết định: Chỉ lưu khi người dùng yêu cầu; không lưu mọi kết quả.
- Xử lý thiếu: Thiếu query cho search hoặc article_id chưa xác định → hỏi.
- Điều kiện hoàn tất: Bài được lưu đúng ID.
- Chứng cứ catalog: [`news.headlines`](tool-catalog-inventory.md#tool-news-headlines), [`news.search`](tool-catalog-inventory.md#tool-news-search), [`news.save`](tool-catalog-inventory.md#tool-news-save).
- Chứng cứ mã, đúng split: [train/apps/news.py:12](../../tools/train/apps/news.py#L12); [train/apps/news.py:16](../../tools/train/apps/news.py#L16); [train/apps/news.py:32](../../tools/train/apps/news.py#L32).

<a id="w17"></a>

## W17 — Chọn điểm đến và đặt/huỷ xe

- Miền: D08; mức: **S**.
- Ý định: Chọn điểm đến và đặt/huỷ xe.
- Tool cần theo nhánh: `maps.search_place`, `maps.get_route`, `maps.save_place`, `ride_hailing.get_quotes`, `ride_hailing.book`, `ride_hailing.get_ride`, `ride_hailing.cancel`.
- Thứ tự điển hình: Nếu cần phân giải địa điểm: search_place → lấy địa chỉ; nếu cần ETA/giá: get_route/get_quotes → đánh giá → book. Huỷ: get_ride → cancel. save_place chỉ khi có yêu cầu lưu.
- Dữ liệu trung gian: places[].id/address; route.duration_min; quotes[].vehicle/price; ride.id; pickup/dropoff.
- Điều kiện/quyết định: book không nhận quote_id; get_quotes không là tiền đề bắt buộc. schedule_time ≤ current_time thành đặt ngay.
- Xử lý thiếu: Thiếu pickup/dropoff/vehicle hoặc ride_id → hỏi; không tự giả định loại xe.
- Điều kiện hoàn tất: Ride booked/cancelled hoặc địa điểm được lưu theo ý định.
- Chứng cứ catalog: [`maps.search_place`](tool-catalog-inventory.md#tool-maps-search_place), [`maps.get_route`](tool-catalog-inventory.md#tool-maps-get_route), [`maps.save_place`](tool-catalog-inventory.md#tool-maps-save_place), [`ride_hailing.get_quotes`](tool-catalog-inventory.md#tool-ride_hailing-get_quotes), [`ride_hailing.book`](tool-catalog-inventory.md#tool-ride_hailing-book), [`ride_hailing.get_ride`](tool-catalog-inventory.md#tool-ride_hailing-get_ride), [`ride_hailing.cancel`](tool-catalog-inventory.md#tool-ride_hailing-cancel).
- Chứng cứ mã, đúng split: [train/apps/maps.py:29](../../tools/train/apps/maps.py#L29); [train/apps/maps.py:54](../../tools/train/apps/maps.py#L54); [train/apps/maps.py:75](../../tools/train/apps/maps.py#L75); [train/apps/ride_hailing.py:30](../../tools/train/apps/ride_hailing.py#L30); [train/apps/ride_hailing.py:34](../../tools/train/apps/ride_hailing.py#L34); [train/apps/ride_hailing.py:45](../../tools/train/apps/ride_hailing.py#L45); [train/apps/ride_hailing.py:41](../../tools/train/apps/ride_hailing.py#L41).
- Giới hạn/chú giải: Ghép địa chỉ maps sang book là suy luận; get_ride → cancel có x-ref tường minh.

<a id="w18"></a>

## W18 — Thuê xe đạp hoặc đặt/kết thúc chỗ đỗ

- Miền: D08; mức: **E**.
- Ý định: Thuê xe đạp hoặc đặt/kết thúc chỗ đỗ.
- Tool cần theo nhánh: `bike_rental.find_bikes`, `bike_rental.reserve`, `parking.find`, `parking.reserve`, `parking.list_sessions`, `parking.end_session`.
- Thứ tự điển hình: Xe đạp: find_bikes → reserve. Đỗ xe: find → reserve; kết thúc: list_sessions → end_session.
- Dữ liệu trung gian: bike_id/status; lot_id/available_spots; from_time/hours; session_id.
- Điều kiện/quyết định: Các nhánh độc lập và khác split; parking.reserve cần offset múi giờ theo mã, còn hours phải nguyên >0.
- Xử lý thiếu: Thiếu bike_id/lot_id/from_time/hours/session_id → hỏi.
- Điều kiện hoàn tất: Xe được giữ hoặc parking.session có trạng thái đích.
- Chứng cứ catalog: [`bike_rental.find_bikes`](tool-catalog-inventory.md#tool-bike_rental-find_bikes), [`bike_rental.reserve`](tool-catalog-inventory.md#tool-bike_rental-reserve), [`parking.find`](tool-catalog-inventory.md#tool-parking-find), [`parking.reserve`](tool-catalog-inventory.md#tool-parking-reserve), [`parking.list_sessions`](tool-catalog-inventory.md#tool-parking-list_sessions), [`parking.end_session`](tool-catalog-inventory.md#tool-parking-end_session).
- Chứng cứ mã, đúng split: [train/apps/bike_rental.py:14](../../tools/train/apps/bike_rental.py#L14); [train/apps/bike_rental.py:27](../../tools/train/apps/bike_rental.py#L27); [test/apps/parking.py:15](../../tools/test/apps/parking.py#L15); [test/apps/parking.py:27](../../tools/test/apps/parking.py#L27); [test/apps/parking.py:22](../../tools/test/apps/parking.py#L22); [test/apps/parking.py:46](../../tools/test/apps/parking.py#L46).

<a id="w19"></a>

## W19 — Tìm tuyến công cộng hoặc nạp thẻ

- Miền: D08; mức: **S**.
- Ý định: Tìm tuyến công cộng hoặc nạp thẻ.
- Tool cần theo nhánh: `public_transit.find_routes`, `public_transit.next_departures`, `public_transit.topup_card`.
- Thứ tự điển hình: find_routes → chọn tuyến/trạm → next_departures nếu cần giờ; topup_card là yêu cầu trực tiếp với amount.
- Dữ liệu trung gian: routes[]; stop, route; amount.
- Điều kiện/quyết định: Nối tuyến sang stop cần kiểm tra cấu trúc kết quả thực; nạp thẻ không chứng minh trừ ewallet.
- Xử lý thiếu: Thiếu origin/destination/stop/amount theo tool cần gọi → hỏi.
- Điều kiện hoàn tất: Trả tuyến/giờ hoặc số dư thẻ đã nạp.
- Chứng cứ catalog: [`public_transit.find_routes`](tool-catalog-inventory.md#tool-public_transit-find_routes), [`public_transit.next_departures`](tool-catalog-inventory.md#tool-public_transit-next_departures), [`public_transit.topup_card`](tool-catalog-inventory.md#tool-public_transit-topup_card).
- Chứng cứ mã, đúng split: [test/apps/public_transit.py:33](../../tools/test/apps/public_transit.py#L33); [test/apps/public_transit.py:52](../../tools/test/apps/public_transit.py#L52); [test/apps/public_transit.py:65](../../tools/test/apps/public_transit.py#L65).

<a id="w20"></a>

## W20 — Đặt, huỷ hoặc check-in vé liên tỉnh

- Miền: D09; mức: **E**.
- Ý định: Đặt, huỷ hoặc check-in vé liên tỉnh.
- Tool cần theo nhánh: `flights.search`, `flights.book`, `flights.my_bookings`, `flights.cancel`, `flights.check_in`, `train_bus_tickets.search`, `train_bus_tickets.book`, `train_bus_tickets.my_bookings`, `train_bus_tickets.cancel`.
- Thứ tự điển hình: Đặt: search → chọn flight_id/trip_id → book; quản lý: my_bookings → chọn booking_id → cancel/check_in (bay).
- Dữ liệu trung gian: Chuyến, giá, ngày; passengers hoặc seats; booking_id; trạng thái vé.
- Điều kiện/quyết định: Vé tàu/xe kiểm seats_left; không có check-in tàu/xe. Bay đã huỷ/đã check-in không check-in lại.
- Xử lý thiếu: Thiếu origin/destination/date/passengers/seats/booking_id → hỏi theo nhánh.
- Điều kiện hoàn tất: Booking confirmed/cancelled hoặc checked_in:true.
- Chứng cứ catalog: [`flights.search`](tool-catalog-inventory.md#tool-flights-search), [`flights.book`](tool-catalog-inventory.md#tool-flights-book), [`flights.my_bookings`](tool-catalog-inventory.md#tool-flights-my_bookings), [`flights.cancel`](tool-catalog-inventory.md#tool-flights-cancel), [`flights.check_in`](tool-catalog-inventory.md#tool-flights-check_in), [`train_bus_tickets.search`](tool-catalog-inventory.md#tool-train_bus_tickets-search), [`train_bus_tickets.book`](tool-catalog-inventory.md#tool-train_bus_tickets-book), [`train_bus_tickets.my_bookings`](tool-catalog-inventory.md#tool-train_bus_tickets-my_bookings), [`train_bus_tickets.cancel`](tool-catalog-inventory.md#tool-train_bus_tickets-cancel).
- Chứng cứ mã, đúng split: [train/apps/flights.py:67](../../tools/train/apps/flights.py#L67); [train/apps/flights.py:74](../../tools/train/apps/flights.py#L74); [train/apps/flights.py:84](../../tools/train/apps/flights.py#L84); [train/apps/flights.py:93](../../tools/train/apps/flights.py#L93); [train/apps/flights.py:97](../../tools/train/apps/flights.py#L97); [test/apps/train_bus_tickets.py:14](../../tools/test/apps/train_bus_tickets.py#L14); [test/apps/train_bus_tickets.py:25](../../tools/test/apps/train_bus_tickets.py#L25); [test/apps/train_bus_tickets.py:21](../../tools/test/apps/train_bus_tickets.py#L21); [test/apps/train_bus_tickets.py:37](../../tools/test/apps/train_bus_tickets.py#L37).

<a id="w21"></a>

## W21 — Đặt hoặc huỷ món giao tận nơi

- Miền: D10; mức: **E**.
- Ý định: Đặt hoặc huỷ món giao tận nơi.
- Tool cần theo nhánh: `food_delivery.list_restaurants`, `food_delivery.get_menu`, `food_delivery.place_order`, `food_delivery.order_history`, `food_delivery.cancel_order`.
- Thứ tự điển hình: Đặt: list_restaurants → get_menu → chọn items → place_order. Huỷ: order_history → chọn order_id → cancel_order.
- Dữ liệu trung gian: restaurant_id; menu[].id/price → items[].item_id/quantity/note; order_id.
- Điều kiện/quyết định: Mỗi item thuộc menu đúng quán; payment mặc định cash trong mã. Không thêm lệnh chuyển ví vì payment=ewallet.
- Xử lý thiếu: Thiếu restaurant_id/items hoặc order_id; không tự bịa quantity khi người dùng chưa rõ.
- Điều kiện hoàn tất: Có order đúng món hoặc status cancelled; không coi menu trả rỗng là thành công đặt.
- Chứng cứ catalog: [`food_delivery.list_restaurants`](tool-catalog-inventory.md#tool-food_delivery-list_restaurants), [`food_delivery.get_menu`](tool-catalog-inventory.md#tool-food_delivery-get_menu), [`food_delivery.place_order`](tool-catalog-inventory.md#tool-food_delivery-place_order), [`food_delivery.order_history`](tool-catalog-inventory.md#tool-food_delivery-order_history), [`food_delivery.cancel_order`](tool-catalog-inventory.md#tool-food_delivery-cancel_order).
- Chứng cứ mã, đúng split: [train/apps/food_delivery.py:11](../../tools/train/apps/food_delivery.py#L11); [train/apps/food_delivery.py:15](../../tools/train/apps/food_delivery.py#L15); [train/apps/food_delivery.py:26](../../tools/train/apps/food_delivery.py#L26); [train/apps/food_delivery.py:22](../../tools/train/apps/food_delivery.py#L22); [train/apps/food_delivery.py:46](../../tools/train/apps/food_delivery.py#L46).

<a id="w22"></a>

## W22 — Công thức, tủ bếp và danh sách cần mua

- Miền: D10, D11; mức: **H**.
- Ý định: Công thức, tủ bếp và danh sách cần mua.
- Tool cần theo nhánh: `recipes.search`, `recipes.get`, `recipes.save`, `pantry.list_items`, `pantry.consume`, `shopping_list.add`, `grocery.search`, `grocery.add_to_cart`, `grocery.checkout`.
- Thứ tự điển hình: search(query,servings) → chọn công thức → get nếu cần bước; list_items → so nguyên liệu cùng đơn vị → shopping_list.add phần thiếu hoặc nhánh grocery. consume chỉ khi người dùng nói đã dùng.
- Dữ liệu trung gian: recipe_id; ingredients[].name/quantity/unit; pantry.stock/unit; product_id và quantity mua.
- Điều kiện/quyết định: get trả công thức gốc, không giữ servings đã scale ở search; không trừ tủ bếp chỉ vì tìm công thức. Quy đổi đơn vị/đóng gói có thể chưa đủ chứng cứ.
- Xử lý thiếu: Thiếu recipe_id/query hoặc name/quantity khi dùng công cụ mua/consume → hỏi đúng tên; không đưa trường tự chế như missing_ingredients vào sys.
- Điều kiện hoàn tất: Công thức đã lấy/lưu; danh sách hoặc order chỉ gồm phần xác định được; consume xác nhận trừ đúng món.
- Chứng cứ catalog: [`recipes.search`](tool-catalog-inventory.md#tool-recipes-search), [`recipes.get`](tool-catalog-inventory.md#tool-recipes-get), [`recipes.save`](tool-catalog-inventory.md#tool-recipes-save), [`pantry.list_items`](tool-catalog-inventory.md#tool-pantry-list_items), [`pantry.consume`](tool-catalog-inventory.md#tool-pantry-consume), [`shopping_list.add`](tool-catalog-inventory.md#tool-shopping_list-add), [`grocery.search`](tool-catalog-inventory.md#tool-grocery-search), [`grocery.add_to_cart`](tool-catalog-inventory.md#tool-grocery-add_to_cart), [`grocery.checkout`](tool-catalog-inventory.md#tool-grocery-checkout).
- Chứng cứ mã, đúng split: [test/apps/recipes.py:25](../../tools/test/apps/recipes.py#L25); [test/apps/recipes.py:38](../../tools/test/apps/recipes.py#L38); [test/apps/recipes.py:45](../../tools/test/apps/recipes.py#L45); [test/apps/pantry.py:11](../../tools/test/apps/pantry.py#L11); [test/apps/pantry.py:15](../../tools/test/apps/pantry.py#L15); [train/apps/shopping_list.py:15](../../tools/train/apps/shopping_list.py#L15); [test/apps/grocery.py:13](../../tools/test/apps/grocery.py#L13); [test/apps/grocery.py:17](../../tools/test/apps/grocery.py#L17); [test/apps/grocery.py:21](../../tools/test/apps/grocery.py#L21).
- Giới hạn/chú giải: Các cạnh search→get/save và list_items→consume là E; đối chiếu nguyên liệu→SKU và quantity là S/H cần xác minh đơn vị.

<a id="w23"></a>

## W23 — Tìm hàng, thêm giỏ và checkout

- Miền: D11; mức: **E**.
- Ý định: Tìm hàng, thêm giỏ và checkout.
- Tool cần theo nhánh: `ecommerce.search`, `ecommerce.add_to_cart`, `ecommerce.checkout`, `grocery.search`, `grocery.add_to_cart`, `grocery.checkout`.
- Thứ tự điển hình: Chọn app → search → chọn sản phẩm và quantity → add_to_cart → đọc cart trả về → checkout chỉ khi người dùng muốn đặt toàn bộ giỏ.
- Dữ liệu trung gian: products[].id/price/in_stock; cart[]/cart_total; order.id/items; address/payment hoặc delivery_time.
- Điều kiện/quyết định: Không gọi cả hai app trừ khi yêu cầu thật sự gồm hai giỏ. Checkout lấy toàn giỏ và làm trống; không có tool get_cart/remove_cart.
- Xử lý thiếu: Thiếu query/product_id/quantity cần hỏi; address là optional, không tự nâng thành required.
- Điều kiện hoàn tất: Order trả đúng giỏ đã được người dùng yêu cầu đặt; không checkout lại.
- Chứng cứ catalog: [`ecommerce.search`](tool-catalog-inventory.md#tool-ecommerce-search), [`ecommerce.add_to_cart`](tool-catalog-inventory.md#tool-ecommerce-add_to_cart), [`ecommerce.checkout`](tool-catalog-inventory.md#tool-ecommerce-checkout), [`grocery.search`](tool-catalog-inventory.md#tool-grocery-search), [`grocery.add_to_cart`](tool-catalog-inventory.md#tool-grocery-add_to_cart), [`grocery.checkout`](tool-catalog-inventory.md#tool-grocery-checkout).
- Chứng cứ mã, đúng split: [test/apps/ecommerce.py:16](../../tools/test/apps/ecommerce.py#L16); [test/apps/ecommerce.py:32](../../tools/test/apps/ecommerce.py#L32); [test/apps/ecommerce.py:36](../../tools/test/apps/ecommerce.py#L36); [test/apps/grocery.py:13](../../tools/test/apps/grocery.py#L13); [test/apps/grocery.py:17](../../tools/test/apps/grocery.py#L17); [test/apps/grocery.py:21](../../tools/test/apps/grocery.py#L21).
- Giới hạn/chú giải: add_to_cart cộng quantity nếu sản phẩm đã có; mã _shop_match.py quyết định hành vi.

<a id="w24"></a>

## W24 — Huỷ đơn hoặc trả hàng online

- Miền: D11; mức: **E**.
- Ý định: Huỷ đơn hoặc trả hàng online.
- Tool cần theo nhánh: `ecommerce.order_status`, `ecommerce.cancel_order`, `ecommerce.request_return`.
- Thứ tự điển hình: order_status → chọn order_id và kiểm status → cancel_order hoặc request_return.
- Dữ liệu trung gian: orders[].id/status; reason thuộc enum.
- Điều kiện/quyết định: Huỷ chỉ placed/shipping; trả chỉ delivered và chưa có yêu cầu trả; không hứa hoàn tiền đã vào ví.
- Xử lý thiếu: Thiếu order_id/reason theo nhánh → hỏi.
- Điều kiện hoàn tất: Order cancelled hoặc return.status=requested; chưa khẳng định refund completed.
- Chứng cứ catalog: [`ecommerce.order_status`](tool-catalog-inventory.md#tool-ecommerce-order_status), [`ecommerce.cancel_order`](tool-catalog-inventory.md#tool-ecommerce-cancel_order), [`ecommerce.request_return`](tool-catalog-inventory.md#tool-ecommerce-request_return).
- Chứng cứ mã, đúng split: [test/apps/ecommerce.py:23](../../tools/test/apps/ecommerce.py#L23); [test/apps/ecommerce.py:40](../../tools/test/apps/ecommerce.py#L40); [test/apps/ecommerce.py:50](../../tools/test/apps/ecommerce.py#L50).

<a id="w25"></a>

## W25 — Cập nhật danh sách mua hoặc lịch giao nhận

- Miền: D11; mức: **E**.
- Ý định: Cập nhật danh sách mua hoặc lịch giao nhận.
- Tool cần theo nhánh: `shopping_list.get`, `shopping_list.remove`, `shopping_list.check`, `package_tracking.track`, `package_tracking.reschedule_delivery`, `package_tracking.schedule_pickup`.
- Thứ tự điển hình: Danh sách: get → item_id → remove/check. Kiện hàng: track → tracking_id → reschedule_delivery. schedule_pickup đủ address/date thì trực tiếp.
- Dữ liệu trung gian: item_id; shipments[].tracking_id; time; address/date.
- Điều kiện/quyết định: Không dùng ecommerce.order_id làm tracking_id khi không có ánh xạ; không tự check món chỉ vì checkout giỏ thành công.
- Xử lý thiếu: Thiếu item_id/tracking_id/time/address/date → hỏi theo nhánh.
- Điều kiện hoàn tất: Món được check/xoá hoặc lịch shipment/pickup được trả.
- Chứng cứ catalog: [`shopping_list.get`](tool-catalog-inventory.md#tool-shopping_list-get), [`shopping_list.remove`](tool-catalog-inventory.md#tool-shopping_list-remove), [`shopping_list.check`](tool-catalog-inventory.md#tool-shopping_list-check), [`package_tracking.track`](tool-catalog-inventory.md#tool-package_tracking-track), [`package_tracking.reschedule_delivery`](tool-catalog-inventory.md#tool-package_tracking-reschedule_delivery), [`package_tracking.schedule_pickup`](tool-catalog-inventory.md#tool-package_tracking-schedule_pickup).
- Chứng cứ mã, đúng split: [train/apps/shopping_list.py:11](../../tools/train/apps/shopping_list.py#L11); [train/apps/shopping_list.py:24](../../tools/train/apps/shopping_list.py#L24); [train/apps/shopping_list.py:28](../../tools/train/apps/shopping_list.py#L28); [train/apps/package_tracking.py:20](../../tools/train/apps/package_tracking.py#L20); [train/apps/package_tracking.py:29](../../tools/train/apps/package_tracking.py#L29); [train/apps/package_tracking.py:39](../../tools/train/apps/package_tracking.py#L39).

<a id="w26"></a>

## W26 — Chọn nội dung nghe và quản lý thư viện

- Miền: D12; mức: **E**.
- Ý định: Chọn nội dung nghe và quản lý thư viện.
- Tool cần theo nhánh: `music.list_tracks`, `music.play`, `music.add_to_playlist`, `music.control`, `podcast_radio.search`, `podcast_radio.play`, `podcast_radio.subscribe`, `podcast_radio.queue`.
- Thứ tự điển hình: Nhạc: list_tracks → chọn track_id/playlist_id → play/add_to_playlist. Podcast: search → episode_id/station/show_id → play/queue/subscribe.
- Dữ liệu trung gian: tracks/playlists; shows/episodes/stations; ID đúng loại.
- Điều kiện/quyết định: music.play và podcast_radio.play có x-one-of; station là tên đài, không giả station_id. control có thể gọi trực tiếp.
- Xử lý thiếu: Thiếu một nhánh ID hoặc volume khi action cần số nhưng schema chưa bắt buộc: không bịa giá trị; chỉ sys với tham số bắt buộc, còn hành vi volume cần review.
- Điều kiện hoàn tất: Nội dung/playlist/hàng đợi/theo dõi được cập nhật đúng.
- Chứng cứ catalog: [`music.list_tracks`](tool-catalog-inventory.md#tool-music-list_tracks), [`music.play`](tool-catalog-inventory.md#tool-music-play), [`music.add_to_playlist`](tool-catalog-inventory.md#tool-music-add_to_playlist), [`music.control`](tool-catalog-inventory.md#tool-music-control), [`podcast_radio.search`](tool-catalog-inventory.md#tool-podcast_radio-search), [`podcast_radio.play`](tool-catalog-inventory.md#tool-podcast_radio-play), [`podcast_radio.subscribe`](tool-catalog-inventory.md#tool-podcast_radio-subscribe), [`podcast_radio.queue`](tool-catalog-inventory.md#tool-podcast_radio-queue).
- Chứng cứ mã, đúng split: [train/apps/music.py:11](../../tools/train/apps/music.py#L11); [train/apps/music.py:19](../../tools/train/apps/music.py#L19); [train/apps/music.py:46](../../tools/train/apps/music.py#L46); [train/apps/music.py:35](../../tools/train/apps/music.py#L35); [train/apps/podcast_radio.py:15](../../tools/train/apps/podcast_radio.py#L15); [train/apps/podcast_radio.py:35](../../tools/train/apps/podcast_radio.py#L35); [train/apps/podcast_radio.py:54](../../tools/train/apps/podcast_radio.py#L54); [train/apps/podcast_radio.py:64](../../tools/train/apps/podcast_radio.py#L64).

<a id="w27"></a>

## W27 — Chọn kênh hoặc ghi hình TV

- Miền: D12; mức: **E**.
- Ý định: Chọn kênh hoặc ghi hình TV.
- Tool cần theo nhánh: `tv.guide`, `tv.tune`, `tv.record`, `tv.control`.
- Thứ tự điển hình: guide → chọn channels/programs → tune hoặc record; control on/off/mute trực tiếp khi đủ yêu cầu.
- Dữ liệu trung gian: channels[]; programs[].id; channel/date.
- Điều kiện/quyết định: Catalog nêu gọi guide trước khi chuyển kênh; tune tự bật TV, không thêm control(on) mặc định.
- Xử lý thiếu: Thiếu channel/program_id → hỏi; không suy chương trình thành ID.
- Điều kiện hoàn tất: Kênh đang phát hoặc lịch recording đúng chương trình.
- Chứng cứ catalog: [`tv.guide`](tool-catalog-inventory.md#tool-tv-guide), [`tv.tune`](tool-catalog-inventory.md#tool-tv-tune), [`tv.record`](tool-catalog-inventory.md#tool-tv-record), [`tv.control`](tool-catalog-inventory.md#tool-tv-control).
- Chứng cứ mã, đúng split: [train/apps/tv.py:11](../../tools/train/apps/tv.py#L11); [train/apps/tv.py:19](../../tools/train/apps/tv.py#L19); [train/apps/tv.py:36](../../tools/train/apps/tv.py#L36); [train/apps/tv.py:26](../../tools/train/apps/tv.py#L26).

<a id="w28"></a>

## W28 — Đặt vé sự kiện

- Miền: D12; mức: **E**.
- Ý định: Đặt vé sự kiện.
- Tool cần theo nhánh: `event_tickets.search`, `event_tickets.book`.
- Thứ tự điển hình: search → chọn event_id → book(quantity).
- Dữ liệu trung gian: events[].id, giá/số vé nếu được trả; quantity.
- Điều kiện/quyết định: Chỉ Public Test; event_id của app này không phải calendar.event_id.
- Xử lý thiếu: Thiếu event_id/quantity → hỏi.
- Điều kiện hoàn tất: Booking vé sự kiện được trả.
- Chứng cứ catalog: [`event_tickets.search`](tool-catalog-inventory.md#tool-event_tickets-search), [`event_tickets.book`](tool-catalog-inventory.md#tool-event_tickets-book).
- Chứng cứ mã, đúng split: [test/apps/event_tickets.py:13](../../tools/test/apps/event_tickets.py#L13); [test/apps/event_tickets.py:17](../../tools/test/apps/event_tickets.py#L17).

<a id="w29"></a>

## W29 — Ghi lịch thuốc, vận động hoặc thói quen

- Miền: D13; mức: **E**.
- Ý định: Ghi lịch thuốc, vận động hoặc thói quen.
- Tool cần theo nhánh: `medication.list`, `medication.log_taken`, `medication.remove`, `medication.add`, `fitness.get_activity`, `fitness.log_workout`, `fitness.set_goal`, `habit_tracker.list_habits`, `habit_tracker.log`.
- Thứ tự điển hình: Lịch thuốc: list → log_taken/remove; thêm lịch dùng add nếu name/times đã đủ. Habit: list_habits → log. Fitness: đọc activity nếu có điều kiện rồi log_workout/set_goal theo ý định.
- Dữ liệu trung gian: schedule_id; habit_id/date; name/times; type/minutes; steps; activity.
- Điều kiện/quyết định: Không suy ra liều lượng; không tự ghi đã uống từ việc nhắc thuốc. Ngày/giờ dựa context của sample.
- Xử lý thiếu: Thiếu schedule_id/habit_id/date/name/times/type/minutes/steps → hỏi đúng tool.
- Điều kiện hoàn tất: Bản ghi hoạt động/lịch/habit hoặc goal đúng ý định; không coi đây là kết quả sức khoẻ.
- Chứng cứ catalog: [`medication.list`](tool-catalog-inventory.md#tool-medication-list), [`medication.log_taken`](tool-catalog-inventory.md#tool-medication-log_taken), [`medication.remove`](tool-catalog-inventory.md#tool-medication-remove), [`medication.add`](tool-catalog-inventory.md#tool-medication-add), [`fitness.get_activity`](tool-catalog-inventory.md#tool-fitness-get_activity), [`fitness.log_workout`](tool-catalog-inventory.md#tool-fitness-log_workout), [`fitness.set_goal`](tool-catalog-inventory.md#tool-fitness-set_goal), [`habit_tracker.list_habits`](tool-catalog-inventory.md#tool-habit_tracker-list_habits), [`habit_tracker.log`](tool-catalog-inventory.md#tool-habit_tracker-log).
- Chứng cứ mã, đúng split: [train/apps/medication.py:11](../../tools/train/apps/medication.py#L11); [train/apps/medication.py:19](../../tools/train/apps/medication.py#L19); [train/apps/medication.py:28](../../tools/train/apps/medication.py#L28); [train/apps/medication.py:15](../../tools/train/apps/medication.py#L15); [train/apps/fitness.py:15](../../tools/train/apps/fitness.py#L15); [train/apps/fitness.py:29](../../tools/train/apps/fitness.py#L29); [train/apps/fitness.py:36](../../tools/train/apps/fitness.py#L36); [test/apps/habit_tracker.py:13](../../tools/test/apps/habit_tracker.py#L13); [test/apps/habit_tracker.py:17](../../tools/test/apps/habit_tracker.py#L17).

<a id="w30"></a>

## W30 — Đăng ký/lên lịch học hoặc giữ sách

- Miền: D14; mức: **E**.
- Ý định: Đăng ký/lên lịch học hoặc giữ sách.
- Tool cần theo nhánh: `learning.list_courses`, `learning.enroll`, `learning.schedule_lesson`, `learning.log_progress`, `library.search`, `library.reserve`.
- Thứ tự điển hình: Khoá: list_courses → chọn course_id → enroll/schedule_lesson/log_progress. Sách: search → book_id → reserve.
- Dữ liệu trung gian: courses[].id/enrolled; time/minutes; books[].id/status.
- Điều kiện/quyết định: Không ép enroll trước mọi schedule_lesson; dựa trạng thái thực và mã. Sách đang cho mượn có thể xếp hàng giữ.
- Xử lý thiếu: Thiếu course_id/time/minutes/book_id → hỏi.
- Điều kiện hoàn tất: Khoá/tiến độ/buổi học hoặc giữ sách được trả.
- Chứng cứ catalog: [`learning.list_courses`](tool-catalog-inventory.md#tool-learning-list_courses), [`learning.enroll`](tool-catalog-inventory.md#tool-learning-enroll), [`learning.schedule_lesson`](tool-catalog-inventory.md#tool-learning-schedule_lesson), [`learning.log_progress`](tool-catalog-inventory.md#tool-learning-log_progress), [`library.search`](tool-catalog-inventory.md#tool-library-search), [`library.reserve`](tool-catalog-inventory.md#tool-library-reserve).
- Chứng cứ mã, đúng split: [train/apps/learning.py:11](../../tools/train/apps/learning.py#L11); [train/apps/learning.py:15](../../tools/train/apps/learning.py#L15); [train/apps/learning.py:25](../../tools/train/apps/learning.py#L25); [train/apps/learning.py:32](../../tools/train/apps/learning.py#L32); [train/apps/library.py:11](../../tools/train/apps/library.py#L11); [train/apps/library.py:15](../../tools/train/apps/library.py#L15).

<a id="w31"></a>

## W31 — Lệnh/cảnh báo chứng khoán theo điều kiện

- Miền: D16; mức: **S**.
- Ý định: Lệnh/cảnh báo chứng khoán theo điều kiện.
- Tool cần theo nhánh: `stocks.get_quote`, `stocks.get_portfolio`, `stocks.place_order`, `stocks.set_price_alert`.
- Thứ tự điển hình: Nếu ý định có điều kiện giá/danh mục: get_quote/get_portfolio → so sánh → place_order hoặc set_price_alert.
- Dữ liệu trung gian: symbol; quote.price; holdings.quantity; side/quantity; ngưỡng/direction.
- Điều kiện/quyết định: Giá là dữ liệu mô phỏng; không đặt lệnh chỉ số; bán không vượt holdings; thiếu price là market trong mã, không phải lỗi thiếu dữ kiện.
- Xử lý thiếu: Thiếu symbol/side/quantity hay price/direction của cảnh báo → hỏi đúng nhánh.
- Điều kiện hoàn tất: Order.status=placed hoặc alert.active=true; đặt lệnh không đồng nghĩa khớp lệnh.
- Chứng cứ catalog: [`stocks.get_quote`](tool-catalog-inventory.md#tool-stocks-get_quote), [`stocks.get_portfolio`](tool-catalog-inventory.md#tool-stocks-get_portfolio), [`stocks.place_order`](tool-catalog-inventory.md#tool-stocks-place_order), [`stocks.set_price_alert`](tool-catalog-inventory.md#tool-stocks-set_price_alert).
- Chứng cứ mã, đúng split: [test/apps/stocks.py:27](../../tools/test/apps/stocks.py#L27); [test/apps/stocks.py:34](../../tools/test/apps/stocks.py#L34); [test/apps/stocks.py:40](../../tools/test/apps/stocks.py#L40); [test/apps/stocks.py:55](../../tools/test/apps/stocks.py#L55).
- Giới hạn/chú giải: Các bước đọc phục vụ điều kiện là suy luận; điều kiện từ stocks.py được xác nhận tĩnh.

<a id="w32"></a>

## W32 — Xem lịch rồi báo qua liên lạc

- Miền: D03, D04; mức: **S**.
- Ý định: Xem lịch rồi báo qua liên lạc.
- Tool cần theo nhánh: `calendar.list_events`, `contacts.search`, `sms.send`, `chat_ott.list_chats`, `chat_ott.send_message`.
- Thứ tự điển hình: list_events → chọn sự kiện và trích giờ/địa điểm → phân giải recipient/chat → gửi đúng kênh.
- Dữ liệu trung gian: Event start/location/title; contact_id/phone_number hoặc chat_id; content tổng hợp.
- Điều kiện/quyết định: Chỉ gửi nội dung người dùng yêu cầu; hai nhánh SMS/OTT là lựa chọn, không luôn gửi cả hai.
- Xử lý thiếu: Thiếu người nhận hoặc sự kiện mơ hồ → hỏi ID/recipient của tool liên quan, không tự chọn.
- Điều kiện hoàn tất: Tin chứa thông tin sự kiện đúng đã gửi đến đúng đối tượng.
- Chứng cứ catalog: [`calendar.list_events`](tool-catalog-inventory.md#tool-calendar-list_events), [`contacts.search`](tool-catalog-inventory.md#tool-contacts-search), [`sms.send`](tool-catalog-inventory.md#tool-sms-send), [`chat_ott.list_chats`](tool-catalog-inventory.md#tool-chat_ott-list_chats), [`chat_ott.send_message`](tool-catalog-inventory.md#tool-chat_ott-send_message).
- Chứng cứ mã, đúng split: [train/apps/calendar.py:13](../../tools/train/apps/calendar.py#L13); [train/apps/contacts.py:11](../../tools/train/apps/contacts.py#L11); [train/apps/sms.py:11](../../tools/train/apps/sms.py#L11); [train/apps/chat_ott.py:11](../../tools/train/apps/chat_ott.py#L11); [train/apps/chat_ott.py:22](../../tools/train/apps/chat_ott.py#L22).
- Giới hạn/chú giải: Không có x-ref nối calendar sang messaging; đây là ghép dữ liệu từ returns.

<a id="w33"></a>

## W33 — Theo thời tiết rồi điều khiển nhà

- Miền: D07, D01; mức: **S**.
- Ý định: Theo thời tiết rồi điều khiển nhà.
- Tool cần theo nhánh: `weather.get_current`, `weather.get_forecast`, `smart_home.get_status`, `smart_home.climate_set`, `smart_home.switch_set`.
- Thứ tự điển hình: Lấy current hoặc forecast theo thời điểm yêu cầu → đánh giá điều kiện do người dùng nêu → get_status → setter nếu điều kiện đúng.
- Dữ liệu trung gian: current/forecast và đơn vị; devices[].id; ngưỡng; mode/power.
- Điều kiện/quyết định: Chỉ phản ứng trong request hiện tại; không đăng ký tự động theo thời tiết với home_automation.create_rule.
- Xử lý thiếu: Thiếu date cho forecast hoặc mode/device_id chưa rõ → hỏi đúng tool.
- Điều kiện hoàn tất: Điều kiện sai: kết thúc không ghi; điều kiện đúng: setter thành công.
- Chứng cứ catalog: [`weather.get_current`](tool-catalog-inventory.md#tool-weather-get_current), [`weather.get_forecast`](tool-catalog-inventory.md#tool-weather-get_forecast), [`smart_home.get_status`](tool-catalog-inventory.md#tool-smart_home-get_status), [`smart_home.climate_set`](tool-catalog-inventory.md#tool-smart_home-climate_set), [`smart_home.switch_set`](tool-catalog-inventory.md#tool-smart_home-switch_set).
- Chứng cứ mã, đúng split: [train/apps/weather.py:11](../../tools/train/apps/weather.py#L11); [train/apps/weather.py:16](../../tools/train/apps/weather.py#L16); [train/apps/smart_home.py:11](../../tools/train/apps/smart_home.py#L11); [train/apps/smart_home.py:26](../../tools/train/apps/smart_home.py#L26); [train/apps/smart_home.py:30](../../tools/train/apps/smart_home.py#L30).

<a id="w34"></a>

## W34 — Vé, thời gian di chuyển và nhắc/đặt xe

- Miền: D09, D08, D03; mức: **H**.
- Ý định: Vé, thời gian di chuyển và nhắc/đặt xe.
- Tool cần theo nhánh: `flights.my_bookings`, `maps.get_route`, `reminders.create`, `ride_hailing.book`.
- Thứ tự điển hình: my_bookings → chọn chuyến → get_route nếu cần ước lượng → tính giờ từ quy tắc người dùng → reminders.create và/hoặc ride_hailing.book.
- Dữ liệu trung gian: flight.depart/date/origin; route.duration_min; pickup/dropoff; khoảng đệm; time/schedule_time.
- Điều kiện/quyết định: Không có thông tin nhà ga/địa chỉ/giờ đệm thì chưa đủ để tính giờ đi. Không đặt xe chỉ vì yêu cầu nhắc.
- Xử lý thiếu: Thiếu content/time của reminder hoặc pickup/dropoff/vehicle của book → hỏi; không bịa airport_address.
- Điều kiện hoàn tất: Nhắc hoặc ride được tạo đúng lựa chọn và thời gian.
- Chứng cứ catalog: [`flights.my_bookings`](tool-catalog-inventory.md#tool-flights-my_bookings), [`maps.get_route`](tool-catalog-inventory.md#tool-maps-get_route), [`reminders.create`](tool-catalog-inventory.md#tool-reminders-create), [`ride_hailing.book`](tool-catalog-inventory.md#tool-ride_hailing-book).
- Chứng cứ mã, đúng split: [train/apps/flights.py:84](../../tools/train/apps/flights.py#L84); [train/apps/maps.py:54](../../tools/train/apps/maps.py#L54); [train/apps/reminders.py:15](../../tools/train/apps/reminders.py#L15); [train/apps/ride_hailing.py:34](../../tools/train/apps/ride_hailing.py#L34).
- Giới hạn/chú giải: Khả năng từng tool có thật; liên kết sân bay, giờ đệm, timezone và đồng cài phải xác minh.

<a id="w35"></a>

## W35 — Dịch nội dung rồi gửi

- Miền: D15, D04; mức: **S**.
- Ý định: Dịch nội dung rồi gửi.
- Tool cần theo nhánh: `translator.translate`, `contacts.search`, `sms.send`, `chat_ott.list_chats`, `chat_ott.send_message`, `email.send`.
- Thứ tự điển hình: translate(text,to_lang) → lấy translation → phân giải đích nếu cần → gửi bằng kênh yêu cầu.
- Dữ liệu trung gian: translation; recipient/chat; subject/body nếu email.
- Điều kiện/quyết định: Không dịch tên/số/ID một cách tuỳ tiện; không gửi nếu người dùng chỉ muốn xem bản dịch.
- Xử lý thiếu: Thiếu text/to_lang hoặc recipient/content/subject/body chưa xác định → hỏi tool tương ứng.
- Điều kiện hoàn tất: Bản dịch được trả và, khi có yêu cầu, được gửi đúng đích.
- Chứng cứ catalog: [`translator.translate`](tool-catalog-inventory.md#tool-translator-translate), [`contacts.search`](tool-catalog-inventory.md#tool-contacts-search), [`sms.send`](tool-catalog-inventory.md#tool-sms-send), [`chat_ott.list_chats`](tool-catalog-inventory.md#tool-chat_ott-list_chats), [`chat_ott.send_message`](tool-catalog-inventory.md#tool-chat_ott-send_message), [`email.send`](tool-catalog-inventory.md#tool-email-send).
- Chứng cứ mã, đúng split: [test/apps/translator.py:18](../../tools/test/apps/translator.py#L18); [train/apps/contacts.py:11](../../tools/train/apps/contacts.py#L11); [train/apps/sms.py:11](../../tools/train/apps/sms.py#L11); [train/apps/chat_ott.py:11](../../tools/train/apps/chat_ott.py#L11); [train/apps/chat_ott.py:22](../../tools/train/apps/chat_ott.py#L22); [train/apps/email.py:53](../../tools/train/apps/email.py#L53).

<a id="w36"></a>

## W36 — Dừng tại thông tin bắt buộc còn thiếu

- Năng lực hệ thống: SC01 (trước đây D17, không phải miền nghiệp vụ); mức: **E**.
- Ý định: Dừng tại thông tin bắt buộc còn thiếu.
- Tool cần theo nhánh: `sys.ask_missing_info`.
- Thứ tự điển hình: Xác định tool hợp lệ cần dùng → kiểm required/x-one-of với context/history và kết quả đọc có ích → ask_missing_info(tool_name,params) → dừng chờ.
- Dữ liệu trung gian: Tên tool đích; danh sách tên tham số còn thiếu đúng schema.
- Điều kiện/quyết định: x-one-of cần một nhóm đủ, không hỏi cả hai nhóm; không dùng sys cho yêu cầu ngoài khả năng hoặc lỗi nghiệp vụ đơn thuần.
- Xử lý thiếu: Đây là nhánh xử lý thiếu; không tạo slot mới ngoài schema.
- Điều kiện hoàn tất: Kết quả waiting_for_user:true; không tự giả có câu trả lời mới.
- Chứng cứ catalog: [`sys.ask_missing_info`](tool-catalog-inventory.md#tool-sys-ask_missing_info).
- Chứng cứ mã, đúng split: [train/apps/sys.py:11](../../tools/train/apps/sys.py#L11).

<a id="w37"></a>

## W37 — Đặt ngưỡng điện năng từ số liệu

- Miền: D01; mức: **S**.
- Ý định: Đặt ngưỡng điện năng từ số liệu.
- Tool cần theo nhánh: `home_energy.get_usage`, `home_energy.set_alert`.
- Thứ tự điển hình: get_usage(period) khi yêu cầu phụ thuộc số liệu → tính threshold theo quy tắc người dùng → set_alert; ngưỡng nói rõ có thể set_alert trực tiếp.
- Dữ liệu trung gian: usage.kwh/chi tiết theo kỳ nếu có; threshold_kwh nguyên >0.
- Điều kiện/quyết định: week/today không tự quy ra cả tháng nếu người dùng chưa đưa quy tắc; đây là đặt ngưỡng, không tự tắt thiết bị.
- Xử lý thiếu: Thiếu period hoặc threshold_kwh không xác định được → hỏi đúng tool.
- Điều kiện hoàn tất: alert_threshold_kwh đúng ngưỡng; không tuyên bố tiêu thụ đã giảm.
- Chứng cứ catalog: [`home_energy.get_usage`](tool-catalog-inventory.md#tool-home_energy-get_usage), [`home_energy.set_alert`](tool-catalog-inventory.md#tool-home_energy-set_alert).
- Chứng cứ mã, đúng split: [train/apps/home_energy.py:13](../../tools/train/apps/home_energy.py#L13); [train/apps/home_energy.py:21](../../tools/train/apps/home_energy.py#L21).

## Cạnh tham chiếu và nguồn ID tường minh

Bảng sau trích mọi `x-ref` kể cả đường dẫn lồng nhau; đây là tham chiếu bộ sưu tập, không phải tên tool mới. Cột mô tả giữ hướng dẫn nguồn đọc nếu catalog có. Các liên kết không có `x-ref` như menu item, cycle, member, reward và channels được phân tích ở W03/W05/W15/W21/W27.

| Tool | Đối số | x-ref | Chỉ dẫn catalog |
| --- | --- | --- | --- |
| `smart_home.light_set` | `device_id` | `smart_home.devices` | ID thiết bị, lấy từ smart_home.get_status |
| `smart_home.fan_set` | `device_id` | `smart_home.devices` | ID thiết bị, lấy từ smart_home.get_status |
| `smart_home.climate_set` | `device_id` | `smart_home.devices` | ID thiết bị, lấy từ smart_home.get_status |
| `smart_home.switch_set` | `device_id` | `smart_home.devices` | ID thiết bị, lấy từ smart_home.get_status |
| `smart_home.scene_run` | `scene_id` | `smart_home.scenes` | ID ngữ cảnh, lấy từ smart_home.get_status (không lọc) |
| `home_security.acknowledge_alert` | `alert_id` | `home_security.alerts` | ID cảnh báo, lấy từ home_security.list_alerts |
| `door_lock.set_lock` | `lock_id` | `door_lock.locks` | ID khoá, lấy từ door_lock.list_locks |
| `door_lock.grant_guest_code` | `lock_id` | `door_lock.locks` | ID khoá, lấy từ door_lock.list_locks |
| `appliances.start_cycle` | `appliance_id` | `appliances.appliances` | ID thiết bị, lấy từ appliances.list |
| `appliances.stop` | `appliance_id` | `appliances.appliances` | ID thiết bị, lấy từ appliances.list |
| `alarm.update` | `alarm_id` | `alarm.alarms` | ID báo thức, lấy từ alarm.list |
| `alarm.delete` | `alarm_id` | `alarm.alarms` | ID báo thức, lấy từ alarm.list |
| `reminders.complete` | `reminder_id` | `reminders.reminders` | ID nhắc việc, lấy từ reminders.list |
| `reminders.delete` | `reminder_id` | `reminders.reminders` | ID nhắc việc, lấy từ reminders.list |
| `calendar.update_event` | `event_id` | `calendar.events` | ID sự kiện, lấy từ calendar.list_events |
| `calendar.cancel_event` | `event_id` | `calendar.events` | ID sự kiện, lấy từ calendar.list_events |
| `notes.append` | `note_id` | `notes.notes` | ID ghi chú, lấy từ notes.list |
| `tasks.complete` | `task_id` | `tasks.tasks` | ID việc, lấy từ tasks.list |
| `contacts.get` | `contact_id` | `contacts.contacts` | ID liên hệ, lấy từ contacts.search |
| `contacts.update` | `contact_id` | `contacts.contacts` | ID liên hệ, lấy từ contacts.search |
| `phone.call` | `contact_id` | `contacts.contacts` | ID liên hệ, lấy từ contacts.search |
| `sms.send` | `contact_id` | `contacts.contacts` | ID liên hệ, lấy từ contacts.search |
| `sms.read_recent` | `contact_id` | `contacts.contacts` | ID liên hệ, lấy từ contacts.search |
| `chat_ott.read_chat` | `chat_id` | `chat_ott.chats` | ID cuộc trò chuyện, lấy từ chat_ott.list_chats |
| `chat_ott.send_message` | `chat_id` | `chat_ott.chats` | ID cuộc trò chuyện, lấy từ chat_ott.list_chats |
| `chat_ott.send_location` | `chat_id` | `chat_ott.chats` | ID cuộc trò chuyện, lấy từ chat_ott.list_chats |
| `chat_ott.call` | `chat_id` | `chat_ott.chats` | ID cuộc trò chuyện, lấy từ chat_ott.list_chats |
| `email.read` | `email_id` | `email.emails` | ID email, lấy từ email.list |
| `email.reply` | `email_id` | `email.emails` | ID email, lấy từ email.list |
| `email.archive` | `email_id` | `email.emails` | ID email, lấy từ email.list |
| `video_meeting.join` | `meeting_id` | `video_meeting.meetings` | ID cuộc họp, lấy từ video_meeting.list_meetings |
| `banking.list_transactions` | `account_id` | `banking.accounts` | ID tài khoản, lấy từ banking.get_balance |
| `banking.transfer` | `from_account_id` | `banking.accounts` | ID tài khoản, lấy từ banking.get_balance |
| `banking.transfer` | `beneficiary_id` | `banking.beneficiaries` | ID người thụ hưởng, lấy từ banking.list_beneficiaries |
| `banking.open_savings` | `from_account_id` | `banking.accounts` | ID tài khoản, lấy từ banking.get_balance |
| `ewallet.transfer` | `contact_id` | `contacts.contacts` | ID liên hệ, lấy từ contacts.search |
| `bill_payment.pay` | `bill_id` | `bill_payment.bills` | ID hoá đơn, lấy từ bill_payment.list_bills |
| `news.save` | `article_id` | `news.articles` | ID bài báo, lấy từ news.search hoặc news.headlines |
| `maps.save_place` | `place_id` | `maps.places` | ID địa điểm, lấy từ maps.search_place |
| `food_delivery.get_menu` | `restaurant_id` | `food_delivery.restaurants` | ID quán, lấy từ food_delivery.list_restaurants |
| `food_delivery.place_order` | `restaurant_id` | `food_delivery.restaurants` | ID quán, lấy từ food_delivery.list_restaurants |
| `food_delivery.cancel_order` | `order_id` | `food_delivery.orders` | ID đơn, lấy từ food_delivery.order_history |
| `ride_hailing.cancel` | `ride_id` | `ride_hailing.rides` | ID chuyến xe, lấy từ ride_hailing.get_ride |
| `ride_hailing.get_ride` | `ride_id` | `ride_hailing.rides` | ID chuyến xe, lấy từ ride_hailing.get_ride |
| `flights.book` | `flight_id` | `flights.flights` | ID chuyến bay, lấy từ flights.search |
| `flights.cancel` | `booking_id` | `flights.bookings` | ID vé đã đặt, lấy từ flights.my_bookings |
| `flights.check_in` | `booking_id` | `flights.bookings` | ID vé đã đặt, lấy từ flights.my_bookings |
| `shopping_list.remove` | `item_id` | `shopping_list.items` | ID món, lấy từ shopping_list.get |
| `shopping_list.check` | `item_id` | `shopping_list.items` | ID món, lấy từ shopping_list.get |
| `music.play` | `track_id` | `music.tracks` | ID bài hát, lấy từ music.list_tracks |
| `music.play` | `playlist_id` | `music.playlists` | ID playlist, lấy từ music.list_tracks |
| `music.add_to_playlist` | `track_id` | `music.tracks` | ID bài hát, lấy từ music.list_tracks |
| `music.add_to_playlist` | `playlist_id` | `music.playlists` | ID playlist, lấy từ music.list_tracks |
| `tv.record` | `program_id` | `tv.programs` | ID chương trình, lấy từ tv.guide |
| `podcast_radio.play` | `episode_id` | `podcast_radio.episodes` | ID tập podcast, lấy từ podcast_radio.search |
| `podcast_radio.subscribe` | `show_id` | `podcast_radio.shows` | ID kênh podcast, lấy từ podcast_radio.search |
| `podcast_radio.queue` | `episode_id` | `podcast_radio.episodes` | ID tập podcast, lấy từ podcast_radio.search |
| `medication.log_taken` | `schedule_id` | `medication.schedules` | ID lịch thuốc, lấy từ medication.list |
| `medication.remove` | `schedule_id` | `medication.schedules` | ID lịch thuốc, lấy từ medication.list |
| `learning.enroll` | `course_id` | `learning.courses` | ID khoá học, lấy từ learning.list_courses |
| `learning.schedule_lesson` | `course_id` | `learning.courses` | ID khoá học, lấy từ learning.list_courses |
| `learning.log_progress` | `course_id` | `learning.courses` | ID khoá học, lấy từ learning.list_courses |
| `bike_rental.reserve` | `bike_id` | `bike_rental.bikes` | ID xe đạp, lấy từ bike_rental.find_bikes |
| `home_automation.create_rule` | `device_id` | `smart_home.devices` | ID thiết bị, lấy từ smart_home.get_status |
| `home_automation.delete_rule` | `rule_id` | `home_automation.rules` | ID quy tắc, lấy từ home_automation.list_rules |
| `household_chores.assign` | `chore_id` | `household_chores.chores` | ID việc nhà, lấy từ household_chores.list_chores |
| `library.reserve` | `book_id` | `library.books` | ID sách, lấy từ library.search |
| `subscriptions.cancel` | `subscription_id` | `subscriptions.subscriptions` | ID gói đăng ký, lấy từ subscriptions.list |
| `grocery.add_to_cart` | `product_id` | `grocery.products` | ID sản phẩm, lấy từ grocery.search |
| `recipes.get` | `recipe_id` | `recipes.recipes` | ID công thức, lấy từ recipes.search |
| `recipes.save` | `recipe_id` | `recipes.recipes` | ID công thức, lấy từ recipes.search |
| `parking.reserve` | `lot_id` | `parking.lots` | ID bãi đỗ, lấy từ parking.find |
| `parking.end_session` | `session_id` | `parking.sessions` | ID phiên đỗ, lấy từ parking.list_sessions |
| `train_bus_tickets.book` | `trip_id` | `train_bus_tickets.trips` | ID chuyến, lấy từ train_bus_tickets.search |
| `train_bus_tickets.cancel` | `booking_id` | `train_bus_tickets.bookings` | ID vé đã đặt, lấy từ train_bus_tickets.my_bookings |
| `ecommerce.order_status` | `order_id` | `ecommerce.orders` | ID đơn hàng, lấy từ ecommerce.order_status |
| `ecommerce.add_to_cart` | `product_id` | `ecommerce.products` | ID sản phẩm, lấy từ ecommerce.search |
| `ecommerce.cancel_order` | `order_id` | `ecommerce.orders` | ID đơn hàng, lấy từ ecommerce.order_status |
| `ecommerce.request_return` | `order_id` | `ecommerce.orders` | ID đơn hàng, lấy từ ecommerce.order_status |
| `event_tickets.book` | `event_id` | `event_tickets.events` | ID sự kiện, lấy từ event_tickets.search |
| `habit_tracker.log` | `habit_id` | `habit_tracker.habits` | ID thói quen, lấy từ habit_tracker.list_habits |
| `pantry.consume` | `item_id` | `pantry.items` | ID món, lấy từ pantry.list_items |

## Phối hợp liên miền không ép chuỗi cố định

- **E, W13:** D10 cung cấp `merchant_id` cho D05 qua `food_delivery.list_restaurants` → `ewallet.pay_qr`. Chỉ áp dụng khi người dùng yêu cầu trả QR, không mặc định sau đặt món.
- **E, W14:** `bill_payment.pay(source=ewallet)` thay đổi cả hoá đơn và ví (hai app trong D05); không gọi thêm `ewallet.transfer`. Đây là liên app có tác động chung, không đếm như liên miền riêng.
- **S, W32:** D03 lịch → D04 thông báo: S21.B01 (SMS) hoặc S21.B02 (OTT) lấy nội dung và dùng C05 phân giải đích; không retrieve cả S06 hay gửi hai lần.
- **S, W33:** D07 thời tiết → D01 thiết bị: S22.B01 đánh giá điều kiện và dùng phần phân giải thiết bị S01.B01; chỉ một chủ sở hữu setter, điều kiện sai thì không ghi.
- **H, W22:** D10 công thức/tủ bếp → D11 danh sách/giỏ: S15.B01/B02 mô tả phần thiếu, C06/S16.B02 sở hữu giỏ; các nhánh S15 vẫn H, chưa retrieve runtime cho tới khi xác minh đơn vị/quy cách. Không tự trừ tồn tủ.
- **H, W34:** D09 vé → D08 ETA/xe và D03 nhắc: S23.B01/B02 giữ H về booking/giờ/địa chỉ, chưa retrieve runtime; chọn nhắc hoặc xe theo ý định sau khi có bằng chứng, không dùng một nhánh E để bỏ qua gate H.
- **S, W35:** D15 dịch → D04 gửi: S24.B01/B02/B03 chọn đúng một kênh, nhận translation và dùng C05 cho đích; không gọi thêm nhánh gửi của S06.

Các khả năng cần tool cùng eligible trong mẫu; hợp catalog không chứng minh chúng cùng được cài. Điều phối theo mục tiêu và dữ kiện chưa giải quyết, không thực thi cả dãy tool từ các skill ghép lại.

## Ánh xạ workflow sang nhánh nhiệm vụ sau review

Bảng dưới chỉ là điều hướng. Không nối tất cả nhánh trong một hàng thành chuỗi, không nâng W22/W34 mức H thành confirmed. W05/W11/W16 không bắt buộc có skill riêng; dùng schema và hướng dẫn phân giải ID chung khi phù hợp.

| Workflow giữ nguyên | Nhánh có tham chiếu |
| --- | --- |
| W01 | [S01.B01](candidate-skills.md#s01-b01) |
| W02 | [S01.B02](candidate-skills.md#s01-b02) |
| W03 | [S02.B01](candidate-skills.md#s02-b01), [S02.B02](candidate-skills.md#s02-b02), [S02.B03](candidate-skills.md#s02-b03) |
| W04 | [S03.B01](candidate-skills.md#s03-b01), [S03.B02](candidate-skills.md#s03-b02) |
| W05 | Không tạo nhánh riêng; workflow vẫn giữ nguyên |
| W06 | [S04.B01](candidate-skills.md#s04-b01), [S04.B02](candidate-skills.md#s04-b02), [S04.B03](candidate-skills.md#s04-b03) |
| W07 | [S05.B01](candidate-skills.md#s05-b01), [S05.B02](candidate-skills.md#s05-b02), [S05.B03](candidate-skills.md#s05-b03), [S05.B04](candidate-skills.md#s05-b04), [S05.B05](candidate-skills.md#s05-b05) |
| W08 | [S06.B01](candidate-skills.md#s06-b01), [S06.B02](candidate-skills.md#s06-b02), [S06.B03](candidate-skills.md#s06-b03) |
| W09 | [S06.B04](candidate-skills.md#s06-b04), [S06.B05](candidate-skills.md#s06-b05), [S06.B06](candidate-skills.md#s06-b06) |
| W10 | [S07.B01](candidate-skills.md#s07-b01), [S07.B02](candidate-skills.md#s07-b02), [S07.B03](candidate-skills.md#s07-b03) |
| W11 | Không tạo nhánh riêng; workflow vẫn giữ nguyên |
| W12 | [S08.B01](candidate-skills.md#s08-b01), [S08.B02](candidate-skills.md#s08-b02) |
| W13 | [S09.B01](candidate-skills.md#s09-b01), [S09.B02](candidate-skills.md#s09-b02), [S09.B03](candidate-skills.md#s09-b03) |
| W14 | [S10.B01](candidate-skills.md#s10-b01) |
| W15 | [S11.B01](candidate-skills.md#s11-b01), [S11.B02](candidate-skills.md#s11-b02) |
| W16 | Không tạo nhánh riêng; workflow vẫn giữ nguyên |
| W17 | [S12.B01](candidate-skills.md#s12-b01), [S12.B02](candidate-skills.md#s12-b02) |
| W18 | [S12.B03](candidate-skills.md#s12-b03), [S12.B04](candidate-skills.md#s12-b04), [S12.B05](candidate-skills.md#s12-b05) |
| W19 | [S12.B06](candidate-skills.md#s12-b06) |
| W20 | [S13.B01](candidate-skills.md#s13-b01), [S13.B02](candidate-skills.md#s13-b02), [S13.B03](candidate-skills.md#s13-b03), [S13.B04](candidate-skills.md#s13-b04), [S13.B05](candidate-skills.md#s13-b05) |
| W21 | [S14.B01](candidate-skills.md#s14-b01), [S14.B02](candidate-skills.md#s14-b02) |
| W22 | [S15.B01](candidate-skills.md#s15-b01), [S15.B02](candidate-skills.md#s15-b02) |
| W23 | [S16.B01](candidate-skills.md#s16-b01), [S16.B02](candidate-skills.md#s16-b02) |
| W24 | [S17.B01](candidate-skills.md#s17-b01), [S17.B02](candidate-skills.md#s17-b02) |
| W25 | [S17.B03](candidate-skills.md#s17-b03) |
| W26 | [S18.B01](candidate-skills.md#s18-b01), [S18.B02](candidate-skills.md#s18-b02), [S18.B03](candidate-skills.md#s18-b03), [S18.B04](candidate-skills.md#s18-b04), [S18.B05](candidate-skills.md#s18-b05), [S18.B06](candidate-skills.md#s18-b06) |
| W27 | [S18.B07](candidate-skills.md#s18-b07), [S18.B08](candidate-skills.md#s18-b08) |
| W28 | [S18.B09](candidate-skills.md#s18-b09) |
| W29 | [S19.B01](candidate-skills.md#s19-b01), [S19.B02](candidate-skills.md#s19-b02), [S19.B03](candidate-skills.md#s19-b03), [S19.B04](candidate-skills.md#s19-b04) |
| W30 | [S19.B05](candidate-skills.md#s19-b05), [S19.B06](candidate-skills.md#s19-b06), [S19.B07](candidate-skills.md#s19-b07), [S19.B08](candidate-skills.md#s19-b08) |
| W31 | [S20.B01](candidate-skills.md#s20-b01), [S20.B02](candidate-skills.md#s20-b02) |
| W32 | [S21.B01](candidate-skills.md#s21-b01), [S21.B02](candidate-skills.md#s21-b02) |
| W33 | [S22.B01](candidate-skills.md#s22-b01) |
| W34 | [S23.B01](candidate-skills.md#s23-b01), [S23.B02](candidate-skills.md#s23-b02) |
| W35 | [S24.B01](candidate-skills.md#s24-b01), [S24.B02](candidate-skills.md#s24-b02), [S24.B03](candidate-skills.md#s24-b03) |
| W36 | SC01 / C02 — dùng chung, không phải nhánh được đếm |
| W37 | [S22.B02](candidate-skills.md#s22-b02) |
