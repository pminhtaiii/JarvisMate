# Kiểm kê Tool Catalog LifeMate

Ngày phân tích: 10/11/2026. Base: `e216ad5115229598149ca8c4e3f43554ce065268` (nhánh `codex/009-cross-step-kv-cache`). Chỉ nghiên cứu tĩnh; không chạy tool trên mẫu, GPU, inference, retrieval hay skill thực thi.

Train: **147 tool / 46 app**. Public Test: **122 tool / 36 app**. Giao: **88 tool**; chỉ Train: **59**; chỉ Public Test: **34**. Hợp: **181 tool / 57 app**.

## Nguồn và cách tái kiểm tra

Dữ liệu gốc đã đọc tại workspace:

- `train+public_test/train+public_test/train/train_tools_catalog.json`.
- `train+public_test/train+public_test/public_test/public_test_tools_catalog.json`.
- `train+public_test/train+public_test/README.md` (cấu trúc dữ liệu, schemas và giới hạn truy cập).
- Các module `<split>/zaic_tools/apps/*.py`, `executor.py`, `validate.py` và README theo split.

Bản catalog được lưu sẵn tại [Train](../../tools/train_tools_catalog.json) và [Public Test](../../tools/public_test_tools_catalog.json) khớp cấu trúc JSON sâu với bản dataset; byte khác (không xem byte equality là khác schema). Toàn bộ module app tương ứng khớp sau chuẩn hoá CRLF/LF; liên kết mã trong báo cáo dùng bản repo có thể review độc lập. Schema version của cả hai: `2.7.0`.

| Split | SHA-256 catalog gốc | SHA-256 bản repo |
| --- | --- | --- |
| train | `a994984bb580d7e0d60166641858901d428549682ba3614dbf9269037a33cce0` | `3895a315a24e1ed04ad063ccc71ee4d70afa0a80fee9552f71dbf0d3e05f9a2f` |
| public_test | `c8f46c278a7495d36905ac28fc5b85b67aad22bc2ac0b29ba9ac6455ad9daf5d` | `42a3d0f0e69fdf30da78652292ee85ef7295c666600a06221827bb4fae5eea36` |

Đã duyệt toàn bộ entry JSON và đối chiếu tên method của mọi tool với mã app. Không mở `train.jsonl`, `public_test.jsonl`, nhãn, dự đoán, audio hay bất kỳ file trong `*_environment/`; không tạo ToolEnv. Không suy số lượng mẫu hay tần suất intent từ lần phân tích này.

Cách tái kiểm tra: nạp JSON UTF-8 của bốn catalog, flatten `apps[].tools`, kiểm tên trùng, so deep equality theo tên, tính hiệu/giao/hợp; ghép mỗi tên `<app>.<method>` với module app đúng split. Các đường dẫn `/apps/i/tools/j` dưới đây là JSON Pointer, index bắt đầu từ 0; line link trỏ bản repo.

## So sánh Train và Public Test

88 tool chung có toàn bộ entry bằng nhau, gồm `description`, `kind`, `app`, `parameters`, `returns`; **0 thay đổi schema, 0 thay đổi mô tả** trong phần giao. 25 module app chung cũng khớp mã nguồn sau chuẩn hoá CRLF/LF. Khác biệt giữa hai split nằm ở tập app/tool, không phải implementation của các app chung trong bản đã đọc.

| Tập | Số tool | Tên chính xác |
| --- | --- | --- |
| Cả hai | 88 | `smart_home.get_status`, `smart_home.light_set`, `smart_home.fan_set`, `smart_home.climate_set`, `smart_home.switch_set`, `smart_home.scene_run`, `alarm.list`, `alarm.create`, `alarm.update`, `alarm.delete`, `reminders.list`, `reminders.create`, `reminders.complete`, `reminders.delete`, `calendar.list_events`, `calendar.create_event`, `calendar.update_event`, `calendar.cancel_event`, `notes.list`, `notes.create`, `notes.append`, `tasks.list`, `tasks.add`, `tasks.complete`, `contacts.search`, `contacts.get`, `contacts.update`, `phone.call`, `phone.recent_calls`, `sms.send`, `sms.read_recent`, `chat_ott.list_chats`, `chat_ott.read_chat`, `chat_ott.send_message`, `chat_ott.send_location`, `chat_ott.call`, `email.list`, `email.read`, `email.send`, `email.create_draft`, `email.reply`, `email.archive`, `banking.get_balance`, `banking.list_transactions`, `banking.list_beneficiaries`, `banking.transfer`, `banking.open_savings`, `ewallet.get_balance`, `ewallet.transfer`, `ewallet.topup_mobile`, `ewallet.pay_qr`, `bill_payment.list_bills`, `bill_payment.pay`, `bill_payment.schedule_autopay`, `weather.get_current`, `weather.get_forecast`, `gold_price.get_price`, `fuel_price.get_price`, `maps.search_place`, `maps.get_route`, `maps.save_place`, `food_delivery.list_restaurants`, `food_delivery.get_menu`, `food_delivery.order_history`, `food_delivery.place_order`, `food_delivery.cancel_order`, `ride_hailing.get_quotes`, `ride_hailing.book`, `ride_hailing.cancel`, `ride_hailing.get_ride`, `flights.search`, `flights.book`, `flights.my_bookings`, `flights.cancel`, `flights.check_in`, `shopping_list.get`, `shopping_list.add`, `shopping_list.remove`, `shopping_list.check`, `music.list_tracks`, `music.play`, `music.control`, `music.add_to_playlist`, `tv.guide`, `tv.tune`, `tv.control`, `tv.record`, `sys.ask_missing_info` |
| Chỉ Train | 59 | `home_security.list_alerts`, `home_security.get_camera`, `home_security.arm`, `home_security.acknowledge_alert`, `door_lock.list_locks`, `door_lock.set_lock`, `door_lock.grant_guest_code`, `robot_vacuum.get_status`, `robot_vacuum.start`, `robot_vacuum.stop`, `appliances.list`, `appliances.start_cycle`, `appliances.stop`, `home_energy.get_usage`, `home_energy.set_alert`, `video_meeting.list_meetings`, `video_meeting.create`, `video_meeting.join`, `loyalty.list_vouchers`, `loyalty.get_points`, `loyalty.redeem`, `lottery.get_results`, `lottery.check_ticket`, `exchange_rate.get_rate`, `exchange_rate.convert`, `news.headlines`, `news.search`, `news.save`, `calculator.calculate`, `calculator.convert_unit`, `package_tracking.track`, `package_tracking.reschedule_delivery`, `package_tracking.schedule_pickup`, `podcast_radio.search`, `podcast_radio.play`, `podcast_radio.subscribe`, `podcast_radio.queue`, `medication.list`, `medication.add`, `medication.log_taken`, `medication.remove`, `fitness.get_activity`, `fitness.log_workout`, `fitness.set_goal`, `learning.list_courses`, `learning.enroll`, `learning.schedule_lesson`, `learning.log_progress`, `bike_rental.find_bikes`, `bike_rental.reserve`, `home_automation.list_rules`, `home_automation.create_rule`, `home_automation.delete_rule`, `household_chores.list_chores`, `household_chores.assign`, `library.search`, `library.reserve`, `subscriptions.list`, `subscriptions.cancel` |
| Chỉ Public Test | 34 | `stocks.get_quote`, `stocks.get_portfolio`, `stocks.place_order`, `stocks.set_price_alert`, `translator.translate`, `grocery.search`, `grocery.add_to_cart`, `grocery.checkout`, `recipes.search`, `recipes.get`, `recipes.save`, `public_transit.find_routes`, `public_transit.next_departures`, `public_transit.topup_card`, `parking.find`, `parking.list_sessions`, `parking.reserve`, `parking.end_session`, `train_bus_tickets.search`, `train_bus_tickets.book`, `train_bus_tickets.my_bookings`, `train_bus_tickets.cancel`, `ecommerce.search`, `ecommerce.order_status`, `ecommerce.add_to_cart`, `ecommerce.checkout`, `ecommerce.cancel_order`, `ecommerce.request_return`, `event_tickets.search`, `event_tickets.book`, `habit_tracker.list_habits`, `habit_tracker.log`, `pantry.list_items`, `pantry.consume` |

## Quy tắc diễn giải schema và giới hạn

- `required` là bắt buộc trực tiếp. “Tuỳ chọn” bên dưới chỉ nghĩa không nằm trong `required`; trường thuộc `x-one-of` có thể bắt buộc theo nhánh. `x-one-of` của validator yêu cầu **ít nhất một nhóm đủ**, không phải JSON Schema `oneOf` loại trừ.
- Giữ nguyên `type`, `enum`, `items`, `format`, giới hạn số, `x-ref`, `x-match` và mô tả. Schema đầy đủ được chép nguyên nội dung JSON ở từng entry để không mất ràng buộc lồng nhau. `returns` là mô tả, không phải schema output đã kiểm chứng động. Chuỗi rỗng nghĩa catalog chưa mô tả output.
- [validate.py](../../tools/test/validate.py) kiểm required, type, enum, giới hạn số, format và items đệ quy; không kiểm đầy đủ properties/required của object lồng nhau, không xác thực `x-ref` tồn tại, không thực thi `x-match`, không cấm trường lạ. Không vì vậy mà bỏ hợp đồng nested items của `food_delivery.place_order`.
- `None`, chuỗi rỗng, list rỗng, object rỗng bị coi là chưa cung cấp; optional rỗng có thể bị bỏ qua. Schema `date-time` của validator chấp nhận offset/giây không có, nhưng mô tả thường yêu cầu đầy đủ; `parking.reserve` và `door_lock.grant_guest_code` kiểm offset ở tầng nghiệp vụ. Dùng thời gian đầy đủ theo context/timezone của sample, không lấy ngày phân tích làm “hôm nay”.
- [executor.py](../../tools/test/executor.py) và [base.py](../../tools/test/apps/base.py): `ok:true` có thể đi với `done:false`; ID lạ, thiếu số dư, kết quả rỗng không phải thành công nhiệm vụ. Mọi call thực đều được ghi log, kể cả call lỗi schema.
- `reminders` mô tả app nói theo thời điểm/vị trí nhưng create chỉ có content/time/repeat; không có location trigger. `ewallet` mô tả có “nạp” nhưng không có tool nạp tiền vào ví. Không suy khả năng từ tên app.
- `loyalty.get_points`: catalog `returns=points[]`, mã trả `programs[]` chứa rewards. `contacts.get` được mã xác nhận trả `contacts[]`. Không tự chuẩn hoá output theo tên app/tool hoặc mô tả tóm tắt.

## Từng tool và schema đầy đủ

<a id="tool-smart_home-get_status"></a>

### `smart_home.get_status`

- App: `smart_home`; miền chính: D01; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Lấy thiết bị và trạng thái; lọc theo phòng/tầng/loại; không lọc thì trả về cả danh sách ngữ cảnh (scenes) đã lưu
- Tham số: `room`, `floor`, `type`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `room`, `floor`, `type`.
- Returns nguyên văn: `devices[]`
- Chứng cứ: [train /apps/0/tools/0](../../tools/train_tools_catalog.json#L12); [public_test /apps/0/tools/0](../../tools/public_test_tools_catalog.json#L12); mã [train/apps/smart_home.py:11](../../tools/train/apps/smart_home.py#L11); [test/apps/smart_home.py:11](../../tools/test/apps/smart_home.py#L11).

```json
{
  "type": "object",
  "properties": {
    "room": {
      "type": "string"
    },
    "floor": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2"
    },
    "type": {
      "type": "string",
      "enum": [
        "light",
        "fan",
        "climate",
        "curtain",
        "plug",
        "tv"
      ]
    }
  },
  "required": []
}
```

<a id="tool-smart_home-light_set"></a>

### `smart_home.light_set`

- App: `smart_home`; miền chính: D01; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Bật/tắt/chỉnh sáng đèn
- Tham số: `device_id`, `power`, `brightness`, `color`.
- Bắt buộc trực tiếp: `device_id`.
- Không thuộc required (có thể chịu x-one-of): `power`, `brightness`, `color`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/0/tools/1](../../tools/train_tools_catalog.json#L43); [public_test /apps/0/tools/1](../../tools/public_test_tools_catalog.json#L43); mã [train/apps/smart_home.py:18](../../tools/train/apps/smart_home.py#L18); [test/apps/smart_home.py:18](../../tools/test/apps/smart_home.py#L18).

```json
{
  "type": "object",
  "properties": {
    "device_id": {
      "type": "string",
      "description": "ID thiết bị, lấy từ smart_home.get_status",
      "x-ref": "smart_home.devices"
    },
    "power": {
      "type": "string",
      "enum": [
        "on",
        "off"
      ]
    },
    "brightness": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2"
    },
    "color": {
      "type": "string"
    }
  },
  "required": [
    "device_id"
  ]
}
```

<a id="tool-smart_home-fan_set"></a>

### `smart_home.fan_set`

- App: `smart_home`; miền chính: D01; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Bật/tắt/chỉnh tốc độ quạt
- Tham số: `device_id`, `power`, `speed`.
- Bắt buộc trực tiếp: `device_id`.
- Không thuộc required (có thể chịu x-one-of): `power`, `speed`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/0/tools/2](../../tools/train_tools_catalog.json#L77); [public_test /apps/0/tools/2](../../tools/public_test_tools_catalog.json#L77); mã [train/apps/smart_home.py:22](../../tools/train/apps/smart_home.py#L22); [test/apps/smart_home.py:22](../../tools/test/apps/smart_home.py#L22).

```json
{
  "type": "object",
  "properties": {
    "device_id": {
      "type": "string",
      "description": "ID thiết bị, lấy từ smart_home.get_status",
      "x-ref": "smart_home.devices"
    },
    "power": {
      "type": "string",
      "enum": [
        "on",
        "off"
      ]
    },
    "speed": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2"
    }
  },
  "required": [
    "device_id"
  ]
}
```

<a id="tool-smart_home-climate_set"></a>

### `smart_home.climate_set`

- App: `smart_home`; miền chính: D01; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Đặt chế độ/nhiệt độ điều hoà
- Tham số: `device_id`, `mode`, `temperature`.
- Bắt buộc trực tiếp: `device_id`, `mode`.
- Không thuộc required (có thể chịu x-one-of): `temperature`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/0/tools/3](../../tools/train_tools_catalog.json#L108); [public_test /apps/0/tools/3](../../tools/public_test_tools_catalog.json#L108); mã [train/apps/smart_home.py:26](../../tools/train/apps/smart_home.py#L26); [test/apps/smart_home.py:26](../../tools/test/apps/smart_home.py#L26).

```json
{
  "type": "object",
  "properties": {
    "device_id": {
      "type": "string",
      "description": "ID thiết bị, lấy từ smart_home.get_status",
      "x-ref": "smart_home.devices"
    },
    "mode": {
      "type": "string",
      "enum": [
        "cool",
        "heat",
        "dry",
        "fan",
        "off"
      ]
    },
    "temperature": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2"
    }
  },
  "required": [
    "device_id",
    "mode"
  ]
}
```

<a id="tool-smart_home-switch_set"></a>

### `smart_home.switch_set`

- App: `smart_home`; miền chính: D01; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Bật/tắt ổ cắm, rèm, TV thông minh
- Tham số: `device_id`, `power`.
- Bắt buộc trực tiếp: `device_id`, `power`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/0/tools/4](../../tools/train_tools_catalog.json#L143); [public_test /apps/0/tools/4](../../tools/public_test_tools_catalog.json#L143); mã [train/apps/smart_home.py:30](../../tools/train/apps/smart_home.py#L30); [test/apps/smart_home.py:30](../../tools/test/apps/smart_home.py#L30).

```json
{
  "type": "object",
  "properties": {
    "device_id": {
      "type": "string",
      "description": "ID thiết bị, lấy từ smart_home.get_status",
      "x-ref": "smart_home.devices"
    },
    "power": {
      "type": "string",
      "enum": [
        "on",
        "off"
      ]
    }
  },
  "required": [
    "device_id",
    "power"
  ]
}
```

<a id="tool-smart_home-scene_run"></a>

### `smart_home.scene_run`

- App: `smart_home`; miền chính: D01; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Chạy ngữ cảnh đã đặt sẵn (đi ngủ, ra khỏi nhà...)
- Tham số: `scene_id`.
- Bắt buộc trực tiếp: `scene_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/0/tools/5](../../tools/train_tools_catalog.json#L171); [public_test /apps/0/tools/5](../../tools/public_test_tools_catalog.json#L171); mã [train/apps/smart_home.py:34](../../tools/train/apps/smart_home.py#L34); [test/apps/smart_home.py:34](../../tools/test/apps/smart_home.py#L34).

```json
{
  "type": "object",
  "properties": {
    "scene_id": {
      "type": "string",
      "description": "ID ngữ cảnh, lấy từ smart_home.get_status (không lọc)",
      "x-ref": "smart_home.scenes"
    }
  },
  "required": [
    "scene_id"
  ]
}
```

<a id="tool-home_security-list_alerts"></a>

### `home_security.list_alerts`

- App: `home_security`; miền chính: D02; kind: `read`; split: train.
- Mô tả nguyên văn: Xem cảnh báo gần đây
- Tham số: `since`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `since`.
- Returns nguyên văn: `alerts[]`
- Chứng cứ: [train /apps/1/tools/0](../../tools/train_tools_catalog.json#L199); mã [train/apps/home_security.py:21](../../tools/train/apps/home_security.py#L21).

```json
{
  "type": "object",
  "properties": {
    "since": {
      "type": "string",
      "description": "Chỉ lấy cảnh báo từ thời điểm này, ISO-8601 đầy đủ giây và offset múi giờ, ví dụ 2026-11-11T05:30:00+07:00",
      "format": "date-time"
    }
  },
  "required": []
}
```

<a id="tool-home_security-get_camera"></a>

### `home_security.get_camera`

- App: `home_security`; miền chính: D02; kind: `read`; split: train.
- Mô tả nguyên văn: Xem trạng thái camera theo vị trí
- Tham số: `location`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `location`.
- Returns nguyên văn: `cameras[]`
- Chứng cứ: [train /apps/1/tools/1](../../tools/train_tools_catalog.json#L217); mã [train/apps/home_security.py:32](../../tools/train/apps/home_security.py#L32).

```json
{
  "type": "object",
  "properties": {
    "location": {
      "type": "string",
      "x-match": "fuzzy"
    }
  },
  "required": []
}
```

<a id="tool-home_security-arm"></a>

### `home_security.arm`

- App: `home_security`; miền chính: D02; kind: `write`; split: train.
- Mô tả nguyên văn: Bật/tắt chế độ bảo vệ
- Tham số: `mode`.
- Bắt buộc trực tiếp: `mode`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/1/tools/2](../../tools/train_tools_catalog.json#L234); mã [train/apps/home_security.py:36](../../tools/train/apps/home_security.py#L36).

```json
{
  "type": "object",
  "properties": {
    "mode": {
      "type": "string",
      "enum": [
        "away",
        "home",
        "off"
      ]
    }
  },
  "required": [
    "mode"
  ]
}
```

<a id="tool-home_security-acknowledge_alert"></a>

### `home_security.acknowledge_alert`

- App: `home_security`; miền chính: D02; kind: `write`; split: train.
- Mô tả nguyên văn: Đánh dấu đã xem cảnh báo
- Tham số: `alert_id`.
- Bắt buộc trực tiếp: `alert_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/1/tools/3](../../tools/train_tools_catalog.json#L257); mã [train/apps/home_security.py:41](../../tools/train/apps/home_security.py#L41).

```json
{
  "type": "object",
  "properties": {
    "alert_id": {
      "type": "string",
      "description": "ID cảnh báo, lấy từ home_security.list_alerts",
      "x-ref": "home_security.alerts"
    }
  },
  "required": [
    "alert_id"
  ]
}
```

<a id="tool-door_lock-list_locks"></a>

### `door_lock.list_locks`

- App: `door_lock`; miền chính: D02; kind: `read`; split: train.
- Mô tả nguyên văn: Danh sách khoá và trạng thái
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `locks[]`
- Chứng cứ: [train /apps/2/tools/0](../../tools/train_tools_catalog.json#L285); mã [train/apps/door_lock.py:14](../../tools/train/apps/door_lock.py#L14).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-door_lock-set_lock"></a>

### `door_lock.set_lock`

- App: `door_lock`; miền chính: D02; kind: `write`; split: train.
- Mô tả nguyên văn: Khoá/mở khoá
- Tham số: `lock_id`, `locked`.
- Bắt buộc trực tiếp: `lock_id`, `locked`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/2/tools/1](../../tools/train_tools_catalog.json#L297); mã [train/apps/door_lock.py:18](../../tools/train/apps/door_lock.py#L18).

```json
{
  "type": "object",
  "properties": {
    "lock_id": {
      "type": "string",
      "description": "ID khoá, lấy từ door_lock.list_locks",
      "x-ref": "door_lock.locks"
    },
    "locked": {
      "type": "boolean",
      "description": "true để khoá, false để mở khoá"
    }
  },
  "required": [
    "lock_id",
    "locked"
  ]
}
```

<a id="tool-door_lock-grant_guest_code"></a>

### `door_lock.grant_guest_code`

- App: `door_lock`; miền chính: D02; kind: `write`; split: train.
- Mô tả nguyên văn: Tạo mã mở cửa tạm cho khách
- Tham số: `lock_id`, `valid_until`, `label`.
- Bắt buộc trực tiếp: `lock_id`, `valid_until`.
- Không thuộc required (có thể chịu x-one-of): `label`.
- Returns nguyên văn: `guest_code`
- Chứng cứ: [train /apps/2/tools/2](../../tools/train_tools_catalog.json#L322); mã [train/apps/door_lock.py:24](../../tools/train/apps/door_lock.py#L24).

```json
{
  "type": "object",
  "properties": {
    "lock_id": {
      "type": "string",
      "description": "ID khoá, lấy từ door_lock.list_locks",
      "x-ref": "door_lock.locks"
    },
    "valid_until": {
      "type": "string",
      "description": "Mã hết hạn lúc, ISO-8601 đầy đủ giây và offset múi giờ, ví dụ 2026-11-11T05:30:00+07:00",
      "format": "date-time"
    },
    "label": {
      "type": "string",
      "x-match": "fuzzy"
    }
  },
  "required": [
    "lock_id",
    "valid_until"
  ]
}
```

<a id="tool-robot_vacuum-get_status"></a>

### `robot_vacuum.get_status`

- App: `robot_vacuum`; miền chính: D01; kind: `read`; split: train.
- Mô tả nguyên văn: Pin, trạng thái, khu vực
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `battery, status, mode, rooms[], current_job`
- Chứng cứ: [train /apps/3/tools/0](../../tools/train_tools_catalog.json#L360); mã [train/apps/robot_vacuum.py:17](../../tools/train/apps/robot_vacuum.py#L17).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-robot_vacuum-start"></a>

### `robot_vacuum.start`

- App: `robot_vacuum`; miền chính: D01; kind: `write`; split: train.
- Mô tả nguyên văn: Bắt đầu dọn (toàn bộ nhà khi không truyền rooms, hoặc theo phòng)
- Tham số: `rooms`, `mode`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `rooms`, `mode`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/3/tools/1](../../tools/train_tools_catalog.json#L372); mã [train/apps/robot_vacuum.py:23](../../tools/train/apps/robot_vacuum.py#L23).

```json
{
  "type": "object",
  "properties": {
    "rooms": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Tên phòng, lấy từ rooms của robot_vacuum.get_status, ví dụ [\"phòng khách\", \"bếp\"]; bỏ trống để dọn cả nhà"
    },
    "mode": {
      "type": "string",
      "enum": [
        "vacuum",
        "mop",
        "both"
      ],
      "description": "vacuum: hút bụi; mop: lau; both: hút và lau"
    }
  },
  "required": []
}
```

<a id="tool-robot_vacuum-stop"></a>

### `robot_vacuum.stop`

- App: `robot_vacuum`; miền chính: D01; kind: `write`; split: train.
- Mô tả nguyên văn: Dừng và về dock
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/3/tools/2](../../tools/train_tools_catalog.json#L401); mã [train/apps/robot_vacuum.py:42](../../tools/train/apps/robot_vacuum.py#L42).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-appliances-list"></a>

### `appliances.list`

- App: `appliances`; miền chính: D01; kind: `read`; split: train.
- Mô tả nguyên văn: Danh sách thiết bị và chu trình khả dụng
- Tham số: `type`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `type`.
- Returns nguyên văn: `appliances[]`
- Chứng cứ: [train /apps/4/tools/0](../../tools/train_tools_catalog.json#L421); mã [train/apps/appliances.py:12](../../tools/train/apps/appliances.py#L12).

```json
{
  "type": "object",
  "properties": {
    "type": {
      "type": "string",
      "enum": [
        "washer",
        "dishwasher",
        "dryer",
        "rice_cooker",
        "microwave",
        "air_purifier"
      ]
    }
  },
  "required": []
}
```

<a id="tool-appliances-start_cycle"></a>

### `appliances.start_cycle`

- App: `appliances`; miền chính: D01; kind: `write`; split: train.
- Mô tả nguyên văn: Chạy chu trình
- Tham số: `appliance_id`, `cycle`, `delay_minutes`.
- Bắt buộc trực tiếp: `appliance_id`, `cycle`.
- Không thuộc required (có thể chịu x-one-of): `delay_minutes`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/4/tools/1](../../tools/train_tools_catalog.json#L445); mã [train/apps/appliances.py:16](../../tools/train/apps/appliances.py#L16).

```json
{
  "type": "object",
  "properties": {
    "appliance_id": {
      "type": "string",
      "description": "ID thiết bị, lấy từ appliances.list",
      "x-ref": "appliances.appliances"
    },
    "cycle": {
      "type": "string",
      "description": "Mã chu trình, phải nằm trong cycles của thiết bị (appliances.list), ví dụ quick, normal, eco"
    },
    "delay_minutes": {
      "type": "integer",
      "description": "Hẹn giờ chạy sau bao nhiêu phút. Số nguyên, không dấu chấm hay phẩy, ví dụ 2",
      "minimum": 0
    }
  },
  "required": [
    "appliance_id",
    "cycle"
  ]
}
```

<a id="tool-appliances-stop"></a>

### `appliances.stop`

- App: `appliances`; miền chính: D01; kind: `write`; split: train.
- Mô tả nguyên văn: Dừng thiết bị
- Tham số: `appliance_id`.
- Bắt buộc trực tiếp: `appliance_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/4/tools/2](../../tools/train_tools_catalog.json#L475); mã [train/apps/appliances.py:32](../../tools/train/apps/appliances.py#L32).

```json
{
  "type": "object",
  "properties": {
    "appliance_id": {
      "type": "string",
      "description": "ID thiết bị, lấy từ appliances.list",
      "x-ref": "appliances.appliances"
    }
  },
  "required": [
    "appliance_id"
  ]
}
```

<a id="tool-home_energy-get_usage"></a>

### `home_energy.get_usage`

- App: `home_energy`; miền chính: D01; kind: `read`; split: train.
- Mô tả nguyên văn: Điện tiêu thụ (kWh, tiền) hôm nay, 7 ngày gần nhất (kèm từng ngày) hoặc từ đầu tháng
- Tham số: `period`.
- Bắt buộc trực tiếp: `period`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `usage`
- Chứng cứ: [train /apps/5/tools/0](../../tools/train_tools_catalog.json#L503); mã [train/apps/home_energy.py:13](../../tools/train/apps/home_energy.py#L13).

```json
{
  "type": "object",
  "properties": {
    "period": {
      "type": "string",
      "enum": [
        "today",
        "week",
        "month"
      ],
      "description": "today: hôm nay; week: 7 ngày gần nhất; month: từ đầu tháng đến nay"
    }
  },
  "required": [
    "period"
  ]
}
```

<a id="tool-home_energy-set_alert"></a>

### `home_energy.set_alert`

- App: `home_energy`; miền chính: D01; kind: `write`; split: train.
- Mô tả nguyên văn: Đặt ngưỡng cảnh báo kWh/tháng
- Tham số: `threshold_kwh`.
- Bắt buộc trực tiếp: `threshold_kwh`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `alert_threshold_kwh`
- Chứng cứ: [train /apps/5/tools/1](../../tools/train_tools_catalog.json#L527); mã [train/apps/home_energy.py:21](../../tools/train/apps/home_energy.py#L21).

```json
{
  "type": "object",
  "properties": {
    "threshold_kwh": {
      "type": "integer",
      "description": "Ngưỡng kWh/tháng. Số nguyên, không dấu chấm, phẩy hay đơn vị, ví dụ 300",
      "exclusiveMinimum": 0
    }
  },
  "required": [
    "threshold_kwh"
  ]
}
```

<a id="tool-alarm-list"></a>

### `alarm.list`

- App: `alarm`; miền chính: D03; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Danh sách báo thức
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `alarms[]`
- Chứng cứ: [train /apps/6/tools/0](../../tools/train_tools_catalog.json#L555); [public_test /apps/1/tools/0](../../tools/public_test_tools_catalog.json#L199); mã [train/apps/alarm.py:11](../../tools/train/apps/alarm.py#L11); [test/apps/alarm.py:11](../../tools/test/apps/alarm.py#L11).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-alarm-create"></a>

### `alarm.create`

- App: `alarm`; miền chính: D03; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Tạo báo thức
- Tham số: `time`, `label`, `repeat`.
- Bắt buộc trực tiếp: `time`.
- Không thuộc required (có thể chịu x-one-of): `label`, `repeat`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/6/tools/1](../../tools/train_tools_catalog.json#L567); [public_test /apps/1/tools/1](../../tools/public_test_tools_catalog.json#L211); mã [train/apps/alarm.py:15](../../tools/train/apps/alarm.py#L15); [test/apps/alarm.py:15](../../tools/test/apps/alarm.py#L15).

```json
{
  "type": "object",
  "properties": {
    "time": {
      "type": "string",
      "description": "ISO-8601 đầy đủ giây và offset múi giờ, ví dụ 2026-11-11T05:30:00+07:00"
    },
    "label": {
      "type": "string",
      "x-match": "fuzzy"
    },
    "repeat": {
      "type": "string",
      "enum": [
        "once",
        "daily",
        "weekdays",
        "weekends"
      ]
    }
  },
  "required": [
    "time"
  ]
}
```

<a id="tool-alarm-update"></a>

### `alarm.update`

- App: `alarm`; miền chính: D03; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Sửa giờ/nhãn báo thức
- Tham số: `alarm_id`, `time`, `label`, `enabled`.
- Bắt buộc trực tiếp: `alarm_id`.
- Không thuộc required (có thể chịu x-one-of): `time`, `label`, `enabled`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/6/tools/2](../../tools/train_tools_catalog.json#L599); [public_test /apps/1/tools/2](../../tools/public_test_tools_catalog.json#L243); mã [train/apps/alarm.py:19](../../tools/train/apps/alarm.py#L19); [test/apps/alarm.py:19](../../tools/test/apps/alarm.py#L19).

```json
{
  "type": "object",
  "properties": {
    "alarm_id": {
      "type": "string",
      "description": "ID báo thức, lấy từ alarm.list",
      "x-ref": "alarm.alarms"
    },
    "time": {
      "type": "string",
      "description": "ISO-8601 đầy đủ giây và offset múi giờ, ví dụ 2026-11-11T05:30:00+07:00"
    },
    "label": {
      "type": "string",
      "x-match": "fuzzy"
    },
    "enabled": {
      "type": "boolean"
    }
  },
  "required": [
    "alarm_id"
  ]
}
```

<a id="tool-alarm-delete"></a>

### `alarm.delete`

- App: `alarm`; miền chính: D03; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Xoá báo thức
- Tham số: `alarm_id`.
- Bắt buộc trực tiếp: `alarm_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/6/tools/3](../../tools/train_tools_catalog.json#L630); [public_test /apps/1/tools/3](../../tools/public_test_tools_catalog.json#L274); mã [train/apps/alarm.py:23](../../tools/train/apps/alarm.py#L23); [test/apps/alarm.py:23](../../tools/test/apps/alarm.py#L23).

```json
{
  "type": "object",
  "properties": {
    "alarm_id": {
      "type": "string",
      "description": "ID báo thức, lấy từ alarm.list",
      "x-ref": "alarm.alarms"
    }
  },
  "required": [
    "alarm_id"
  ]
}
```

<a id="tool-reminders-list"></a>

### `reminders.list`

- App: `reminders`; miền chính: D03; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Danh sách nhắc việc
- Tham số: `date`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `date`.
- Returns nguyên văn: `reminders[]`
- Chứng cứ: [train /apps/7/tools/0](../../tools/train_tools_catalog.json#L658); [public_test /apps/2/tools/0](../../tools/public_test_tools_catalog.json#L302); mã [train/apps/reminders.py:11](../../tools/train/apps/reminders.py#L11); [test/apps/reminders.py:11](../../tools/test/apps/reminders.py#L11).

```json
{
  "type": "object",
  "properties": {
    "date": {
      "type": "string",
      "description": "YYYY-MM-DD, ví dụ 2026-11-29"
    }
  },
  "required": []
}
```

<a id="tool-reminders-create"></a>

### `reminders.create`

- App: `reminders`; miền chính: D03; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Tạo nhắc việc
- Tham số: `content`, `time`, `repeat`.
- Bắt buộc trực tiếp: `content`, `time`.
- Không thuộc required (có thể chịu x-one-of): `repeat`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/7/tools/1](../../tools/train_tools_catalog.json#L675); [public_test /apps/2/tools/1](../../tools/public_test_tools_catalog.json#L319); mã [train/apps/reminders.py:15](../../tools/train/apps/reminders.py#L15); [test/apps/reminders.py:15](../../tools/test/apps/reminders.py#L15).

```json
{
  "type": "object",
  "properties": {
    "content": {
      "type": "string",
      "x-match": "fuzzy"
    },
    "time": {
      "type": "string",
      "description": "ISO-8601 đầy đủ giây và offset múi giờ, ví dụ 2026-11-11T05:30:00+07:00"
    },
    "repeat": {
      "type": "string",
      "enum": [
        "once",
        "daily",
        "weekly"
      ]
    }
  },
  "required": [
    "content",
    "time"
  ]
}
```

<a id="tool-reminders-complete"></a>

### `reminders.complete`

- App: `reminders`; miền chính: D03; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Đánh dấu xong
- Tham số: `reminder_id`.
- Bắt buộc trực tiếp: `reminder_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/7/tools/2](../../tools/train_tools_catalog.json#L707); [public_test /apps/2/tools/2](../../tools/public_test_tools_catalog.json#L351); mã [train/apps/reminders.py:19](../../tools/train/apps/reminders.py#L19); [test/apps/reminders.py:19](../../tools/test/apps/reminders.py#L19).

```json
{
  "type": "object",
  "properties": {
    "reminder_id": {
      "type": "string",
      "description": "ID nhắc việc, lấy từ reminders.list",
      "x-ref": "reminders.reminders"
    }
  },
  "required": [
    "reminder_id"
  ]
}
```

<a id="tool-reminders-delete"></a>

### `reminders.delete`

- App: `reminders`; miền chính: D03; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Xoá nhắc việc
- Tham số: `reminder_id`.
- Bắt buộc trực tiếp: `reminder_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/7/tools/3](../../tools/train_tools_catalog.json#L727); [public_test /apps/2/tools/3](../../tools/public_test_tools_catalog.json#L371); mã [train/apps/reminders.py:23](../../tools/train/apps/reminders.py#L23); [test/apps/reminders.py:23](../../tools/test/apps/reminders.py#L23).

```json
{
  "type": "object",
  "properties": {
    "reminder_id": {
      "type": "string",
      "description": "ID nhắc việc, lấy từ reminders.list",
      "x-ref": "reminders.reminders"
    }
  },
  "required": [
    "reminder_id"
  ]
}
```

<a id="tool-calendar-list_events"></a>

### `calendar.list_events`

- App: `calendar`; miền chính: D03; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Danh sách sự kiện, lọc được theo khoảng ngày
- Tham số: `date_from`, `date_to`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `date_from`, `date_to`.
- Returns nguyên văn: `events[]`
- Chứng cứ: [train /apps/8/tools/0](../../tools/train_tools_catalog.json#L755); [public_test /apps/3/tools/0](../../tools/public_test_tools_catalog.json#L399); mã [train/apps/calendar.py:13](../../tools/train/apps/calendar.py#L13); [test/apps/calendar.py:13](../../tools/test/apps/calendar.py#L13).

```json
{
  "type": "object",
  "properties": {
    "date_from": {
      "type": "string",
      "description": "YYYY-MM-DD, ví dụ 2026-11-29"
    },
    "date_to": {
      "type": "string",
      "description": "YYYY-MM-DD, ví dụ 2026-11-29"
    }
  },
  "required": []
}
```

<a id="tool-calendar-create_event"></a>

### `calendar.create_event`

- App: `calendar`; miền chính: D03; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Tạo sự kiện
- Tham số: `title`, `start`, `end`, `location`, `attendees`.
- Bắt buộc trực tiếp: `title`, `start`.
- Không thuộc required (có thể chịu x-one-of): `end`, `location`, `attendees`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/8/tools/1](../../tools/train_tools_catalog.json#L776); [public_test /apps/3/tools/1](../../tools/public_test_tools_catalog.json#L420); mã [train/apps/calendar.py:17](../../tools/train/apps/calendar.py#L17); [test/apps/calendar.py:17](../../tools/test/apps/calendar.py#L17).

```json
{
  "type": "object",
  "properties": {
    "title": {
      "type": "string",
      "x-match": "fuzzy"
    },
    "start": {
      "type": "string",
      "description": "ISO-8601 đầy đủ giây và offset múi giờ, ví dụ 2026-11-11T05:30:00+07:00"
    },
    "end": {
      "type": "string",
      "description": "ISO-8601 đầy đủ giây và offset múi giờ, ví dụ 2026-11-11T05:30:00+07:00; bỏ trống thì mặc định bằng start + 1 giờ"
    },
    "location": {
      "type": "string",
      "x-match": "fuzzy"
    },
    "attendees": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Danh sách ID"
    }
  },
  "required": [
    "title",
    "start"
  ]
}
```

<a id="tool-calendar-update_event"></a>

### `calendar.update_event`

- App: `calendar`; miền chính: D03; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Sửa sự kiện
- Tham số: `event_id`, `title`, `start`, `end`, `location`.
- Bắt buộc trực tiếp: `event_id`.
- Không thuộc required (có thể chịu x-one-of): `title`, `start`, `end`, `location`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/8/tools/2](../../tools/train_tools_catalog.json#L815); [public_test /apps/3/tools/2](../../tools/public_test_tools_catalog.json#L459); mã [train/apps/calendar.py:26](../../tools/train/apps/calendar.py#L26); [test/apps/calendar.py:26](../../tools/test/apps/calendar.py#L26).

```json
{
  "type": "object",
  "properties": {
    "event_id": {
      "type": "string",
      "description": "ID sự kiện, lấy từ calendar.list_events",
      "x-ref": "calendar.events"
    },
    "title": {
      "type": "string",
      "x-match": "fuzzy"
    },
    "start": {
      "type": "string",
      "description": "ISO-8601 đầy đủ giây và offset múi giờ, ví dụ 2026-11-11T05:30:00+07:00"
    },
    "end": {
      "type": "string",
      "description": "ISO-8601 đầy đủ giây và offset múi giờ, ví dụ 2026-11-11T05:30:00+07:00"
    },
    "location": {
      "type": "string",
      "x-match": "fuzzy"
    }
  },
  "required": [
    "event_id"
  ]
}
```

<a id="tool-calendar-cancel_event"></a>

### `calendar.cancel_event`

- App: `calendar`; miền chính: D03; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Huỷ sự kiện
- Tham số: `event_id`.
- Bắt buộc trực tiếp: `event_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/8/tools/3](../../tools/train_tools_catalog.json#L851); [public_test /apps/3/tools/3](../../tools/public_test_tools_catalog.json#L495); mã [train/apps/calendar.py:30](../../tools/train/apps/calendar.py#L30); [test/apps/calendar.py:30](../../tools/test/apps/calendar.py#L30).

```json
{
  "type": "object",
  "properties": {
    "event_id": {
      "type": "string",
      "description": "ID sự kiện, lấy từ calendar.list_events",
      "x-ref": "calendar.events"
    }
  },
  "required": [
    "event_id"
  ]
}
```

<a id="tool-notes-list"></a>

### `notes.list`

- App: `notes`; miền chính: D03; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Danh sách ghi chú
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `notes[]`
- Chứng cứ: [train /apps/9/tools/0](../../tools/train_tools_catalog.json#L879); [public_test /apps/4/tools/0](../../tools/public_test_tools_catalog.json#L523); mã [train/apps/notes.py:11](../../tools/train/apps/notes.py#L11); [test/apps/notes.py:11](../../tools/test/apps/notes.py#L11).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-notes-create"></a>

### `notes.create`

- App: `notes`; miền chính: D03; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Tạo ghi chú
- Tham số: `title`, `content`.
- Bắt buộc trực tiếp: `content`.
- Không thuộc required (có thể chịu x-one-of): `title`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/9/tools/1](../../tools/train_tools_catalog.json#L891); [public_test /apps/4/tools/1](../../tools/public_test_tools_catalog.json#L535); mã [train/apps/notes.py:15](../../tools/train/apps/notes.py#L15); [test/apps/notes.py:15](../../tools/test/apps/notes.py#L15).

```json
{
  "type": "object",
  "properties": {
    "title": {
      "type": "string",
      "x-match": "fuzzy"
    },
    "content": {
      "type": "string",
      "x-match": "fuzzy"
    }
  },
  "required": [
    "content"
  ]
}
```

<a id="tool-notes-append"></a>

### `notes.append`

- App: `notes`; miền chính: D03; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Thêm nội dung vào ghi chú
- Tham số: `note_id`, `content`.
- Bắt buộc trực tiếp: `note_id`, `content`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/9/tools/2](../../tools/train_tools_catalog.json#L914); [public_test /apps/4/tools/2](../../tools/public_test_tools_catalog.json#L558); mã [train/apps/notes.py:19](../../tools/train/apps/notes.py#L19); [test/apps/notes.py:19](../../tools/test/apps/notes.py#L19).

```json
{
  "type": "object",
  "properties": {
    "note_id": {
      "type": "string",
      "description": "ID ghi chú, lấy từ notes.list",
      "x-ref": "notes.notes"
    },
    "content": {
      "type": "string",
      "x-match": "fuzzy"
    }
  },
  "required": [
    "note_id",
    "content"
  ]
}
```

<a id="tool-tasks-list"></a>

### `tasks.list`

- App: `tasks`; miền chính: D03; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Danh sách việc
- Tham số: `status`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `status`.
- Returns nguyên văn: `tasks[]`
- Chứng cứ: [train /apps/10/tools/0](../../tools/train_tools_catalog.json#L947); [public_test /apps/5/tools/0](../../tools/public_test_tools_catalog.json#L591); mã [train/apps/tasks.py:11](../../tools/train/apps/tasks.py#L11); [test/apps/tasks.py:11](../../tools/test/apps/tasks.py#L11).

```json
{
  "type": "object",
  "properties": {
    "status": {
      "type": "string",
      "enum": [
        "open",
        "done"
      ]
    }
  },
  "required": []
}
```

<a id="tool-tasks-add"></a>

### `tasks.add`

- App: `tasks`; miền chính: D03; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Thêm việc
- Tham số: `title`, `due`, `priority`.
- Bắt buộc trực tiếp: `title`.
- Không thuộc required (có thể chịu x-one-of): `due`, `priority`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/10/tools/1](../../tools/train_tools_catalog.json#L967); [public_test /apps/5/tools/1](../../tools/public_test_tools_catalog.json#L611); mã [train/apps/tasks.py:16](../../tools/train/apps/tasks.py#L16); [test/apps/tasks.py:16](../../tools/test/apps/tasks.py#L16).

```json
{
  "type": "object",
  "properties": {
    "title": {
      "type": "string",
      "x-match": "fuzzy"
    },
    "due": {
      "type": "string",
      "description": "ISO-8601 đầy đủ giây và offset múi giờ, ví dụ 2026-11-11T05:30:00+07:00",
      "format": "date-time"
    },
    "priority": {
      "type": "string",
      "enum": [
        "low",
        "normal",
        "high"
      ]
    }
  },
  "required": [
    "title"
  ]
}
```

<a id="tool-tasks-complete"></a>

### `tasks.complete`

- App: `tasks`; miền chính: D03; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Hoàn thành việc
- Tham số: `task_id`.
- Bắt buộc trực tiếp: `task_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/10/tools/2](../../tools/train_tools_catalog.json#L999); [public_test /apps/5/tools/2](../../tools/public_test_tools_catalog.json#L643); mã [train/apps/tasks.py:20](../../tools/train/apps/tasks.py#L20); [test/apps/tasks.py:20](../../tools/test/apps/tasks.py#L20).

```json
{
  "type": "object",
  "properties": {
    "task_id": {
      "type": "string",
      "description": "ID việc, lấy từ tasks.list",
      "x-ref": "tasks.tasks"
    }
  },
  "required": [
    "task_id"
  ]
}
```

<a id="tool-contacts-search"></a>

### `contacts.search`

- App: `contacts`; miền chính: D04; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Tìm liên hệ theo tên, quan hệ hoặc số điện thoại; so chuỗi con, không phân biệt hoa thường và dấu; không truyền query thì trả cả danh bạ
- Tham số: `query`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `query`.
- Returns nguyên văn: `contacts[]`
- Chứng cứ: [train /apps/11/tools/0](../../tools/train_tools_catalog.json#L1027); [public_test /apps/6/tools/0](../../tools/public_test_tools_catalog.json#L671); mã [train/apps/contacts.py:11](../../tools/train/apps/contacts.py#L11); [test/apps/contacts.py:11](../../tools/test/apps/contacts.py#L11).

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Tên, quan hệ (mẹ, vợ, sếp) hoặc số điện thoại"
    }
  },
  "required": []
}
```

<a id="tool-contacts-get"></a>

### `contacts.get`

- App: `contacts`; miền chính: D04; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Chi tiết liên hệ
- Tham số: `contact_id`.
- Bắt buộc trực tiếp: `contact_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `contacts[]`
- Chứng cứ: [train /apps/11/tools/1](../../tools/train_tools_catalog.json#L1044); [public_test /apps/6/tools/1](../../tools/public_test_tools_catalog.json#L688); mã [train/apps/contacts.py:16](../../tools/train/apps/contacts.py#L16); [test/apps/contacts.py:16](../../tools/test/apps/contacts.py#L16).

```json
{
  "type": "object",
  "properties": {
    "contact_id": {
      "type": "string",
      "description": "ID liên hệ, lấy từ contacts.search",
      "x-ref": "contacts.contacts"
    }
  },
  "required": [
    "contact_id"
  ]
}
```

<a id="tool-contacts-update"></a>

### `contacts.update`

- App: `contacts`; miền chính: D04; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Sửa số/email liên hệ
- Tham số: `contact_id`, `phone`, `email`.
- Bắt buộc trực tiếp: `contact_id`.
- Không thuộc required (có thể chịu x-one-of): `phone`, `email`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/11/tools/2](../../tools/train_tools_catalog.json#L1064); [public_test /apps/6/tools/2](../../tools/public_test_tools_catalog.json#L708); mã [train/apps/contacts.py:20](../../tools/train/apps/contacts.py#L20); [test/apps/contacts.py:20](../../tools/test/apps/contacts.py#L20).

```json
{
  "type": "object",
  "properties": {
    "contact_id": {
      "type": "string",
      "description": "ID liên hệ, lấy từ contacts.search",
      "x-ref": "contacts.contacts"
    },
    "phone": {
      "type": "string",
      "description": "Giữ nguyên chuỗi, ví dụ 09123456785"
    },
    "email": {
      "type": "string"
    }
  },
  "required": [
    "contact_id"
  ],
  "x-one-of": [
    [
      "phone"
    ],
    [
      "email"
    ]
  ]
}
```

<a id="tool-phone-call"></a>

### `phone.call`

- App: `phone`; miền chính: D04; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Gọi thoại cho liên hệ hoặc số điện thoại. Bắt buộc một trong: contact_id hoặc phone_number
- Tham số: `contact_id`, `phone_number`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `contact_id`, `phone_number`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/12/tools/0](../../tools/train_tools_catalog.json#L1107); [public_test /apps/7/tools/0](../../tools/public_test_tools_catalog.json#L751); mã [train/apps/phone.py:11](../../tools/train/apps/phone.py#L11); [test/apps/phone.py:11](../../tools/test/apps/phone.py#L11).

```json
{
  "type": "object",
  "properties": {
    "contact_id": {
      "type": "string",
      "description": "ID liên hệ, lấy từ contacts.search",
      "x-ref": "contacts.contacts"
    },
    "phone_number": {
      "type": "string",
      "description": "Số điện thoại, giữ nguyên chuỗi, ví dụ 09123456785"
    }
  },
  "required": [],
  "x-one-of": [
    [
      "contact_id"
    ],
    [
      "phone_number"
    ]
  ]
}
```

<a id="tool-phone-recent_calls"></a>

### `phone.recent_calls`

- App: `phone`; miền chính: D04; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Cuộc gọi gần đây/nhỡ
- Tham số: `missed_only`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `missed_only`.
- Returns nguyên văn: `calls[]`
- Chứng cứ: [train /apps/12/tools/1](../../tools/train_tools_catalog.json#L1137); [public_test /apps/7/tools/1](../../tools/public_test_tools_catalog.json#L781); mã [train/apps/phone.py:18](../../tools/train/apps/phone.py#L18); [test/apps/phone.py:18](../../tools/test/apps/phone.py#L18).

```json
{
  "type": "object",
  "properties": {
    "missed_only": {
      "type": "boolean"
    }
  },
  "required": []
}
```

<a id="tool-sms-send"></a>

### `sms.send`

- App: `sms`; miền chính: D04; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Gửi SMS cho liên hệ hoặc số điện thoại. Bắt buộc một trong: contact_id hoặc phone_number; bắt buộc: content
- Tham số: `contact_id`, `phone_number`, `content`.
- Bắt buộc trực tiếp: `content`.
- Không thuộc required (có thể chịu x-one-of): `contact_id`, `phone_number`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/13/tools/0](../../tools/train_tools_catalog.json#L1161); [public_test /apps/8/tools/0](../../tools/public_test_tools_catalog.json#L805); mã [train/apps/sms.py:11](../../tools/train/apps/sms.py#L11); [test/apps/sms.py:11](../../tools/test/apps/sms.py#L11).

```json
{
  "type": "object",
  "properties": {
    "contact_id": {
      "type": "string",
      "description": "ID liên hệ, lấy từ contacts.search",
      "x-ref": "contacts.contacts"
    },
    "phone_number": {
      "type": "string",
      "description": "Số điện thoại, giữ nguyên chuỗi, ví dụ 09123456785"
    },
    "content": {
      "type": "string",
      "x-match": "fuzzy"
    }
  },
  "required": [
    "content"
  ],
  "x-one-of": [
    [
      "contact_id"
    ],
    [
      "phone_number"
    ]
  ]
}
```

<a id="tool-sms-read_recent"></a>

### `sms.read_recent`

- App: `sms`; miền chính: D04; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Tin nhắn gần đây
- Tham số: `contact_id`, `limit`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `contact_id`, `limit`.
- Returns nguyên văn: `messages[]`
- Chứng cứ: [train /apps/13/tools/1](../../tools/train_tools_catalog.json#L1197); [public_test /apps/8/tools/1](../../tools/public_test_tools_catalog.json#L841); mã [train/apps/sms.py:18](../../tools/train/apps/sms.py#L18); [test/apps/sms.py:18](../../tools/test/apps/sms.py#L18).

```json
{
  "type": "object",
  "properties": {
    "contact_id": {
      "type": "string",
      "description": "ID liên hệ, lấy từ contacts.search",
      "x-ref": "contacts.contacts"
    },
    "limit": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2"
    }
  },
  "required": []
}
```

<a id="tool-chat_ott-list_chats"></a>

### `chat_ott.list_chats`

- App: `chat_ott`; miền chính: D04; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Danh sách cuộc trò chuyện/nhóm
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `chats[]`
- Chứng cứ: [train /apps/14/tools/0](../../tools/train_tools_catalog.json#L1227); [public_test /apps/9/tools/0](../../tools/public_test_tools_catalog.json#L871); mã [train/apps/chat_ott.py:11](../../tools/train/apps/chat_ott.py#L11); [test/apps/chat_ott.py:11](../../tools/test/apps/chat_ott.py#L11).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-chat_ott-read_chat"></a>

### `chat_ott.read_chat`

- App: `chat_ott`; miền chính: D04; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Đọc tin gần đây trong cuộc trò chuyện
- Tham số: `chat_id`, `limit`.
- Bắt buộc trực tiếp: `chat_id`.
- Không thuộc required (có thể chịu x-one-of): `limit`.
- Returns nguyên văn: `messages[]`
- Chứng cứ: [train /apps/14/tools/1](../../tools/train_tools_catalog.json#L1239); [public_test /apps/9/tools/1](../../tools/public_test_tools_catalog.json#L883); mã [train/apps/chat_ott.py:15](../../tools/train/apps/chat_ott.py#L15); [test/apps/chat_ott.py:15](../../tools/test/apps/chat_ott.py#L15).

```json
{
  "type": "object",
  "properties": {
    "chat_id": {
      "type": "string",
      "description": "ID cuộc trò chuyện, lấy từ chat_ott.list_chats",
      "x-ref": "chat_ott.chats"
    },
    "limit": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2"
    }
  },
  "required": [
    "chat_id"
  ]
}
```

<a id="tool-chat_ott-send_message"></a>

### `chat_ott.send_message`

- App: `chat_ott`; miền chính: D04; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Gửi tin vào cuộc trò chuyện
- Tham số: `chat_id`, `content`.
- Bắt buộc trực tiếp: `chat_id`, `content`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/14/tools/2](../../tools/train_tools_catalog.json#L1263); [public_test /apps/9/tools/2](../../tools/public_test_tools_catalog.json#L907); mã [train/apps/chat_ott.py:22](../../tools/train/apps/chat_ott.py#L22); [test/apps/chat_ott.py:22](../../tools/test/apps/chat_ott.py#L22).

```json
{
  "type": "object",
  "properties": {
    "chat_id": {
      "type": "string",
      "description": "ID cuộc trò chuyện, lấy từ chat_ott.list_chats",
      "x-ref": "chat_ott.chats"
    },
    "content": {
      "type": "string",
      "x-match": "fuzzy"
    }
  },
  "required": [
    "chat_id",
    "content"
  ]
}
```

<a id="tool-chat_ott-send_location"></a>

### `chat_ott.send_location`

- App: `chat_ott`; miền chính: D04; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Gửi vị trí hiện tại
- Tham số: `chat_id`.
- Bắt buộc trực tiếp: `chat_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/14/tools/3](../../tools/train_tools_catalog.json#L1288); [public_test /apps/9/tools/3](../../tools/public_test_tools_catalog.json#L932); mã [train/apps/chat_ott.py:31](../../tools/train/apps/chat_ott.py#L31); [test/apps/chat_ott.py:31](../../tools/test/apps/chat_ott.py#L31).

```json
{
  "type": "object",
  "properties": {
    "chat_id": {
      "type": "string",
      "description": "ID cuộc trò chuyện, lấy từ chat_ott.list_chats",
      "x-ref": "chat_ott.chats"
    }
  },
  "required": [
    "chat_id"
  ]
}
```

<a id="tool-chat_ott-call"></a>

### `chat_ott.call`

- App: `chat_ott`; miền chính: D04; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Gọi thoại/video qua OTT
- Tham số: `chat_id`, `video`.
- Bắt buộc trực tiếp: `chat_id`.
- Không thuộc required (có thể chịu x-one-of): `video`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/14/tools/4](../../tools/train_tools_catalog.json#L1308); [public_test /apps/9/tools/4](../../tools/public_test_tools_catalog.json#L952); mã [train/apps/chat_ott.py:40](../../tools/train/apps/chat_ott.py#L40); [test/apps/chat_ott.py:40](../../tools/test/apps/chat_ott.py#L40).

```json
{
  "type": "object",
  "properties": {
    "chat_id": {
      "type": "string",
      "description": "ID cuộc trò chuyện, lấy từ chat_ott.list_chats",
      "x-ref": "chat_ott.chats"
    },
    "video": {
      "type": "boolean"
    }
  },
  "required": [
    "chat_id"
  ]
}
```

<a id="tool-email-list"></a>

### `email.list`

- App: `email`; miền chính: D04; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Danh sách email, lọc được theo chưa đọc
- Tham số: `unread_only`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `unread_only`.
- Returns nguyên văn: `emails[]`
- Chứng cứ: [train /apps/15/tools/0](../../tools/train_tools_catalog.json#L1339); [public_test /apps/10/tools/0](../../tools/public_test_tools_catalog.json#L983); mã [train/apps/email.py:29](../../tools/train/apps/email.py#L29); [test/apps/email.py:29](../../tools/test/apps/email.py#L29).

```json
{
  "type": "object",
  "properties": {
    "unread_only": {
      "type": "boolean"
    }
  },
  "required": []
}
```

<a id="tool-email-read"></a>

### `email.read`

- App: `email`; miền chính: D04; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Đọc nội dung email
- Tham số: `email_id`.
- Bắt buộc trực tiếp: `email_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `email`
- Chứng cứ: [train /apps/15/tools/1](../../tools/train_tools_catalog.json#L1355); [public_test /apps/10/tools/1](../../tools/public_test_tools_catalog.json#L999); mã [train/apps/email.py:36](../../tools/train/apps/email.py#L36); [test/apps/email.py:36](../../tools/test/apps/email.py#L36).

```json
{
  "type": "object",
  "properties": {
    "email_id": {
      "type": "string",
      "description": "ID email, lấy từ email.list",
      "x-ref": "email.emails"
    }
  },
  "required": [
    "email_id"
  ]
}
```

<a id="tool-email-send"></a>

### `email.send`

- App: `email`; miền chính: D04; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Gửi email (lưu vào thư đã gửi)
- Tham số: `to`, `subject`, `body`, `cc`.
- Bắt buộc trực tiếp: `to`, `subject`, `body`.
- Không thuộc required (có thể chịu x-one-of): `cc`.
- Returns nguyên văn: `email`
- Chứng cứ: [train /apps/15/tools/2](../../tools/train_tools_catalog.json#L1375); [public_test /apps/10/tools/2](../../tools/public_test_tools_catalog.json#L1019); mã [train/apps/email.py:53](../../tools/train/apps/email.py#L53); [test/apps/email.py:53](../../tools/test/apps/email.py#L53).

```json
{
  "type": "object",
  "properties": {
    "to": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Danh sách địa chỉ email người nhận, lấy từ contacts.search (trường email) hoặc địa chỉ người dùng đọc, ví dụ [\"lan.nguyen@example.test\"]"
    },
    "subject": {
      "type": "string",
      "x-match": "fuzzy"
    },
    "body": {
      "type": "string",
      "x-match": "fuzzy"
    },
    "cc": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Danh sách địa chỉ email đồng gửi (CC), cùng định dạng với to"
    }
  },
  "required": [
    "to",
    "subject",
    "body"
  ]
}
```

<a id="tool-email-create_draft"></a>

### `email.create_draft`

- App: `email`; miền chính: D04; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Soạn và lưu email nháp, chưa gửi
- Tham số: `to`, `subject`, `body`, `cc`.
- Bắt buộc trực tiếp: `to`, `subject`, `body`.
- Không thuộc required (có thể chịu x-one-of): `cc`.
- Returns nguyên văn: `draft`
- Chứng cứ: [train /apps/15/tools/3](../../tools/train_tools_catalog.json#L1414); [public_test /apps/10/tools/3](../../tools/public_test_tools_catalog.json#L1058); mã [train/apps/email.py:57](../../tools/train/apps/email.py#L57); [test/apps/email.py:57](../../tools/test/apps/email.py#L57).

```json
{
  "type": "object",
  "properties": {
    "to": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Danh sách địa chỉ email người nhận, lấy từ contacts.search (trường email) hoặc địa chỉ người dùng đọc, ví dụ [\"lan.nguyen@example.test\"]"
    },
    "subject": {
      "type": "string",
      "x-match": "fuzzy"
    },
    "body": {
      "type": "string",
      "x-match": "fuzzy"
    },
    "cc": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Danh sách địa chỉ email đồng gửi (CC), cùng định dạng với to"
    }
  },
  "required": [
    "to",
    "subject",
    "body"
  ]
}
```

<a id="tool-email-reply"></a>

### `email.reply`

- App: `email`; miền chính: D04; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Trả lời email
- Tham số: `email_id`, `body`.
- Bắt buộc trực tiếp: `email_id`, `body`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `email`
- Chứng cứ: [train /apps/15/tools/4](../../tools/train_tools_catalog.json#L1453); [public_test /apps/10/tools/4](../../tools/public_test_tools_catalog.json#L1097); mã [train/apps/email.py:61](../../tools/train/apps/email.py#L61); [test/apps/email.py:61](../../tools/test/apps/email.py#L61).

```json
{
  "type": "object",
  "properties": {
    "email_id": {
      "type": "string",
      "description": "ID email, lấy từ email.list",
      "x-ref": "email.emails"
    },
    "body": {
      "type": "string",
      "x-match": "fuzzy"
    }
  },
  "required": [
    "email_id",
    "body"
  ]
}
```

<a id="tool-email-archive"></a>

### `email.archive`

- App: `email`; miền chính: D04; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Lưu trữ/xoá email
- Tham số: `email_id`, `action`.
- Bắt buộc trực tiếp: `email_id`, `action`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/15/tools/5](../../tools/train_tools_catalog.json#L1478); [public_test /apps/10/tools/5](../../tools/public_test_tools_catalog.json#L1122); mã [train/apps/email.py:72](../../tools/train/apps/email.py#L72); [test/apps/email.py:72](../../tools/test/apps/email.py#L72).

```json
{
  "type": "object",
  "properties": {
    "email_id": {
      "type": "string",
      "description": "ID email, lấy từ email.list",
      "x-ref": "email.emails"
    },
    "action": {
      "type": "string",
      "enum": [
        "archive",
        "delete"
      ]
    }
  },
  "required": [
    "email_id",
    "action"
  ]
}
```

<a id="tool-video_meeting-list_meetings"></a>

### `video_meeting.list_meetings`

- App: `video_meeting`; miền chính: D04; kind: `read`; split: train.
- Mô tả nguyên văn: Cuộc họp sắp tới
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `meetings[]`
- Chứng cứ: [train /apps/16/tools/0](../../tools/train_tools_catalog.json#L1514); mã [train/apps/video_meeting.py:20](../../tools/train/apps/video_meeting.py#L20).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-video_meeting-create"></a>

### `video_meeting.create`

- App: `video_meeting`; miền chính: D04; kind: `write`; split: train.
- Mô tả nguyên văn: Tạo phòng họp
- Tham số: `title`, `start`, `attendees`.
- Bắt buộc trực tiếp: `title`, `start`.
- Không thuộc required (có thể chịu x-one-of): `attendees`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/16/tools/1](../../tools/train_tools_catalog.json#L1526); mã [train/apps/video_meeting.py:26](../../tools/train/apps/video_meeting.py#L26).

```json
{
  "type": "object",
  "properties": {
    "title": {
      "type": "string",
      "x-match": "fuzzy"
    },
    "start": {
      "type": "string",
      "description": "ISO-8601 đầy đủ giây và offset múi giờ, ví dụ 2026-11-11T05:30:00+07:00",
      "format": "date-time"
    },
    "attendees": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Danh sách ID liên hệ, lấy từ contacts.search, ví dụ [\"c_01\", \"c_03\"]"
    }
  },
  "required": [
    "title",
    "start"
  ]
}
```

<a id="tool-video_meeting-join"></a>

### `video_meeting.join`

- App: `video_meeting`; miền chính: D04; kind: `write`; split: train.
- Mô tả nguyên văn: Tham gia cuộc họp
- Tham số: `meeting_id`.
- Bắt buộc trực tiếp: `meeting_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/16/tools/2](../../tools/train_tools_catalog.json#L1558); mã [train/apps/video_meeting.py:37](../../tools/train/apps/video_meeting.py#L37).

```json
{
  "type": "object",
  "properties": {
    "meeting_id": {
      "type": "string",
      "description": "ID cuộc họp, lấy từ video_meeting.list_meetings",
      "x-ref": "video_meeting.meetings"
    }
  },
  "required": [
    "meeting_id"
  ]
}
```

<a id="tool-banking-get_balance"></a>

### `banking.get_balance`

- App: `banking`; miền chính: D05; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Số dư các tài khoản
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `accounts[]`
- Chứng cứ: [train /apps/17/tools/0](../../tools/train_tools_catalog.json#L1586); [public_test /apps/11/tools/0](../../tools/public_test_tools_catalog.json#L1158); mã [train/apps/banking.py:11](../../tools/train/apps/banking.py#L11); [test/apps/banking.py:11](../../tools/test/apps/banking.py#L11).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-banking-list_transactions"></a>

### `banking.list_transactions`

- App: `banking`; miền chính: D05; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Giao dịch gần đây
- Tham số: `account_id`, `limit`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `account_id`, `limit`.
- Returns nguyên văn: `transactions[]`
- Chứng cứ: [train /apps/17/tools/1](../../tools/train_tools_catalog.json#L1598); [public_test /apps/11/tools/1](../../tools/public_test_tools_catalog.json#L1170); mã [train/apps/banking.py:15](../../tools/train/apps/banking.py#L15); [test/apps/banking.py:15](../../tools/test/apps/banking.py#L15).

```json
{
  "type": "object",
  "properties": {
    "account_id": {
      "type": "string",
      "description": "ID tài khoản, lấy từ banking.get_balance",
      "x-ref": "banking.accounts"
    },
    "limit": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2"
    }
  },
  "required": []
}
```

<a id="tool-banking-list_beneficiaries"></a>

### `banking.list_beneficiaries`

- App: `banking`; miền chính: D05; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Người thụ hưởng đã lưu
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `beneficiaries[]`
- Chứng cứ: [train /apps/17/tools/2](../../tools/train_tools_catalog.json#L1620); [public_test /apps/11/tools/2](../../tools/public_test_tools_catalog.json#L1192); mã [train/apps/banking.py:19](../../tools/train/apps/banking.py#L19); [test/apps/banking.py:19](../../tools/test/apps/banking.py#L19).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-banking-transfer"></a>

### `banking.transfer`

- App: `banking`; miền chính: D05; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Chuyển tiền cho người thụ hưởng
- Tham số: `from_account_id`, `beneficiary_id`, `amount`, `note`.
- Bắt buộc trực tiếp: `from_account_id`, `beneficiary_id`, `amount`.
- Không thuộc required (có thể chịu x-one-of): `note`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/17/tools/3](../../tools/train_tools_catalog.json#L1632); [public_test /apps/11/tools/3](../../tools/public_test_tools_catalog.json#L1204); mã [train/apps/banking.py:23](../../tools/train/apps/banking.py#L23); [test/apps/banking.py:23](../../tools/test/apps/banking.py#L23).

```json
{
  "type": "object",
  "properties": {
    "from_account_id": {
      "type": "string",
      "description": "ID tài khoản, lấy từ banking.get_balance",
      "x-ref": "banking.accounts"
    },
    "beneficiary_id": {
      "type": "string",
      "description": "ID người thụ hưởng, lấy từ banking.list_beneficiaries",
      "x-ref": "banking.beneficiaries"
    },
    "amount": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm, phẩy hay đơn vị, ví dụ 1200000",
      "exclusiveMinimum": 0
    },
    "note": {
      "type": "string",
      "x-match": "fuzzy"
    }
  },
  "required": [
    "from_account_id",
    "beneficiary_id",
    "amount"
  ]
}
```

<a id="tool-banking-open_savings"></a>

### `banking.open_savings`

- App: `banking`; miền chính: D05; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Gửi tiết kiệm
- Tham số: `from_account_id`, `amount`, `term_months`.
- Bắt buộc trực tiếp: `from_account_id`, `amount`, `term_months`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/17/tools/4](../../tools/train_tools_catalog.json#L1668); [public_test /apps/11/tools/4](../../tools/public_test_tools_catalog.json#L1240); mã [train/apps/banking.py:36](../../tools/train/apps/banking.py#L36); [test/apps/banking.py:36](../../tools/test/apps/banking.py#L36).

```json
{
  "type": "object",
  "properties": {
    "from_account_id": {
      "type": "string",
      "description": "ID tài khoản, lấy từ banking.get_balance",
      "x-ref": "banking.accounts"
    },
    "amount": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm, phẩy hay đơn vị, ví dụ 1200000",
      "exclusiveMinimum": 0
    },
    "term_months": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2",
      "exclusiveMinimum": 0
    }
  },
  "required": [
    "from_account_id",
    "amount",
    "term_months"
  ]
}
```

<a id="tool-ewallet-get_balance"></a>

### `ewallet.get_balance`

- App: `ewallet`; miền chính: D05; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Số dư ví
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `balance`
- Chứng cứ: [train /apps/18/tools/0](../../tools/train_tools_catalog.json#L1708); [public_test /apps/12/tools/0](../../tools/public_test_tools_catalog.json#L1280); mã [train/apps/ewallet.py:11](../../tools/train/apps/ewallet.py#L11); [test/apps/ewallet.py:11](../../tools/test/apps/ewallet.py#L11).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-ewallet-transfer"></a>

### `ewallet.transfer`

- App: `ewallet`; miền chính: D05; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Chuyển tiền ví tới liên hệ hoặc số điện thoại. Bắt buộc một trong: contact_id hoặc phone; bắt buộc: amount
- Tham số: `contact_id`, `phone`, `amount`, `note`.
- Bắt buộc trực tiếp: `amount`.
- Không thuộc required (có thể chịu x-one-of): `contact_id`, `phone`, `note`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/18/tools/1](../../tools/train_tools_catalog.json#L1720); [public_test /apps/12/tools/1](../../tools/public_test_tools_catalog.json#L1292); mã [train/apps/ewallet.py:15](../../tools/train/apps/ewallet.py#L15); [test/apps/ewallet.py:15](../../tools/test/apps/ewallet.py#L15).

```json
{
  "type": "object",
  "properties": {
    "contact_id": {
      "type": "string",
      "description": "ID liên hệ, lấy từ contacts.search",
      "x-ref": "contacts.contacts"
    },
    "phone": {
      "type": "string",
      "description": "Số điện thoại, giữ nguyên chuỗi, ví dụ 09123456785"
    },
    "amount": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm, phẩy hay đơn vị, ví dụ 1200000",
      "exclusiveMinimum": 0
    },
    "note": {
      "type": "string",
      "x-match": "fuzzy"
    }
  },
  "required": [
    "amount"
  ],
  "x-one-of": [
    [
      "contact_id"
    ],
    [
      "phone"
    ]
  ]
}
```

<a id="tool-ewallet-topup_mobile"></a>

### `ewallet.topup_mobile`

- App: `ewallet`; miền chính: D05; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Nạp tiền điện thoại
- Tham số: `phone`, `amount`.
- Bắt buộc trực tiếp: `phone`, `amount`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/18/tools/2](../../tools/train_tools_catalog.json#L1761); [public_test /apps/12/tools/2](../../tools/public_test_tools_catalog.json#L1333); mã [train/apps/ewallet.py:26](../../tools/train/apps/ewallet.py#L26); [test/apps/ewallet.py:26](../../tools/test/apps/ewallet.py#L26).

```json
{
  "type": "object",
  "properties": {
    "phone": {
      "type": "string",
      "description": "Giữ nguyên chuỗi, ví dụ 09123456785"
    },
    "amount": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm, phẩy hay đơn vị, ví dụ 1200000",
      "exclusiveMinimum": 0
    }
  },
  "required": [
    "phone",
    "amount"
  ]
}
```

<a id="tool-ewallet-pay_qr"></a>

### `ewallet.pay_qr`

- App: `ewallet`; miền chính: D05; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Thanh toán QR của một quán/merchant bằng ví; merchant_id lấy từ food_delivery.list_restaurants (trường merchant_id của quán)
- Tham số: `merchant_id`, `amount`.
- Bắt buộc trực tiếp: `merchant_id`, `amount`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/18/tools/3](../../tools/train_tools_catalog.json#L1786); [public_test /apps/12/tools/3](../../tools/public_test_tools_catalog.json#L1358); mã [train/apps/ewallet.py:35](../../tools/train/apps/ewallet.py#L35); [test/apps/ewallet.py:35](../../tools/test/apps/ewallet.py#L35).

```json
{
  "type": "object",
  "properties": {
    "merchant_id": {
      "type": "string",
      "description": "ID merchant của quán (trường merchant_id trong kết quả food_delivery.list_restaurants), không phải id quán"
    },
    "amount": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm, phẩy hay đơn vị, ví dụ 1200000",
      "exclusiveMinimum": 0
    }
  },
  "required": [
    "merchant_id",
    "amount"
  ]
}
```

<a id="tool-bill_payment-list_bills"></a>

### `bill_payment.list_bills`

- App: `bill_payment`; miền chính: D05; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Hoá đơn chưa thanh toán
- Tham số: `type`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `type`.
- Returns nguyên văn: `bills[]`
- Chứng cứ: [train /apps/19/tools/0](../../tools/train_tools_catalog.json#L1819); [public_test /apps/13/tools/0](../../tools/public_test_tools_catalog.json#L1391); mã [train/apps/bill_payment.py:12](../../tools/train/apps/bill_payment.py#L12); [test/apps/bill_payment.py:12](../../tools/test/apps/bill_payment.py#L12).

```json
{
  "type": "object",
  "properties": {
    "type": {
      "type": "string",
      "enum": [
        "electricity",
        "water",
        "internet",
        "tv",
        "tuition",
        "phone"
      ]
    }
  },
  "required": []
}
```

<a id="tool-bill_payment-pay"></a>

### `bill_payment.pay`

- App: `bill_payment`; miền chính: D05; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Thanh toán hoá đơn
- Tham số: `bill_id`, `source`.
- Bắt buộc trực tiếp: `bill_id`, `source`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/19/tools/1](../../tools/train_tools_catalog.json#L1843); [public_test /apps/13/tools/1](../../tools/public_test_tools_catalog.json#L1415); mã [train/apps/bill_payment.py:16](../../tools/train/apps/bill_payment.py#L16); [test/apps/bill_payment.py:16](../../tools/test/apps/bill_payment.py#L16).

```json
{
  "type": "object",
  "properties": {
    "bill_id": {
      "type": "string",
      "description": "ID hoá đơn, lấy từ bill_payment.list_bills",
      "x-ref": "bill_payment.bills"
    },
    "source": {
      "type": "string",
      "enum": [
        "bank",
        "ewallet"
      ]
    }
  },
  "required": [
    "bill_id",
    "source"
  ]
}
```

<a id="tool-bill_payment-schedule_autopay"></a>

### `bill_payment.schedule_autopay`

- App: `bill_payment`; miền chính: D05; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Bật tự động thanh toán
- Tham số: `type`, `enabled`.
- Bắt buộc trực tiếp: `type`, `enabled`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/19/tools/2](../../tools/train_tools_catalog.json#L1871); [public_test /apps/13/tools/2](../../tools/public_test_tools_catalog.json#L1443); mã [train/apps/bill_payment.py:36](../../tools/train/apps/bill_payment.py#L36); [test/apps/bill_payment.py:36](../../tools/test/apps/bill_payment.py#L36).

```json
{
  "type": "object",
  "properties": {
    "type": {
      "type": "string"
    },
    "enabled": {
      "type": "boolean"
    }
  },
  "required": [
    "type",
    "enabled"
  ]
}
```

<a id="tool-loyalty-list_vouchers"></a>

### `loyalty.list_vouchers`

- App: `loyalty`; miền chính: D06; kind: `read`; split: train.
- Mô tả nguyên văn: Voucher đang có
- Tham số: `merchant`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `merchant`.
- Returns nguyên văn: `vouchers[]`
- Chứng cứ: [train /apps/20/tools/0](../../tools/train_tools_catalog.json#L1901); mã [train/apps/loyalty.py:27](../../tools/train/apps/loyalty.py#L27).

```json
{
  "type": "object",
  "properties": {
    "merchant": {
      "type": "string"
    }
  },
  "required": []
}
```

<a id="tool-loyalty-get_points"></a>

### `loyalty.get_points`

- App: `loyalty`; miền chính: D06; kind: `read`; split: train.
- Mô tả nguyên văn: Điểm thành viên
- Tham số: `program`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `program`.
- Returns nguyên văn: `points[]`
- Chứng cứ: [train /apps/20/tools/1](../../tools/train_tools_catalog.json#L1917); mã [train/apps/loyalty.py:31](../../tools/train/apps/loyalty.py#L31).

```json
{
  "type": "object",
  "properties": {
    "program": {
      "type": "string"
    }
  },
  "required": []
}
```

<a id="tool-loyalty-redeem"></a>

### `loyalty.redeem`

- App: `loyalty`; miền chính: D06; kind: `write`; split: train.
- Mô tả nguyên văn: Đổi điểm lấy voucher
- Tham số: `program`, `reward_id`.
- Bắt buộc trực tiếp: `program`, `reward_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/20/tools/2](../../tools/train_tools_catalog.json#L1933); mã [train/apps/loyalty.py:40](../../tools/train/apps/loyalty.py#L40).

```json
{
  "type": "object",
  "properties": {
    "program": {
      "type": "string"
    },
    "reward_id": {
      "type": "string",
      "description": "ID lấy từ state hoặc kết quả tool đọc"
    }
  },
  "required": [
    "program",
    "reward_id"
  ]
}
```

<a id="tool-weather-get_current"></a>

### `weather.get_current`

- App: `weather`; miền chính: D07; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Thời tiết hiện tại
- Tham số: `location`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `location`.
- Returns nguyên văn: `current`
- Chứng cứ: [train /apps/21/tools/0](../../tools/train_tools_catalog.json#L1964); [public_test /apps/15/tools/0](../../tools/public_test_tools_catalog.json#L1580); mã [train/apps/weather.py:11](../../tools/train/apps/weather.py#L11); [test/apps/weather.py:11](../../tools/test/apps/weather.py#L11).

```json
{
  "type": "object",
  "properties": {
    "location": {
      "type": "string",
      "x-match": "fuzzy"
    }
  },
  "required": []
}
```

<a id="tool-weather-get_forecast"></a>

### `weather.get_forecast`

- App: `weather`; miền chính: D07; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Dự báo theo ngày
- Tham số: `location`, `date`.
- Bắt buộc trực tiếp: `date`.
- Không thuộc required (có thể chịu x-one-of): `location`.
- Returns nguyên văn: `forecast`
- Chứng cứ: [train /apps/21/tools/1](../../tools/train_tools_catalog.json#L1981); [public_test /apps/15/tools/1](../../tools/public_test_tools_catalog.json#L1597); mã [train/apps/weather.py:16](../../tools/train/apps/weather.py#L16); [test/apps/weather.py:16](../../tools/test/apps/weather.py#L16).

```json
{
  "type": "object",
  "properties": {
    "location": {
      "type": "string",
      "x-match": "fuzzy",
      "description": "Tên thành phố; bỏ trống = thành phố của người dùng (địa điểm trong thành phố cũng trả dữ liệu thành phố)"
    },
    "date": {
      "type": "string",
      "description": "YYYY-MM-DD, ví dụ 2026-11-29"
    }
  },
  "required": [
    "date"
  ]
}
```

<a id="tool-gold_price-get_price"></a>

### `gold_price.get_price`

- App: `gold_price`; miền chính: D07; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Giá mua/bán theo loại
- Tham số: `type`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `type`.
- Returns nguyên văn: `prices[]`
- Chứng cứ: [train /apps/22/tools/0](../../tools/train_tools_catalog.json#L2013); [public_test /apps/16/tools/0](../../tools/public_test_tools_catalog.json#L1629); mã [train/apps/gold_price.py:11](../../tools/train/apps/gold_price.py#L11); [test/apps/gold_price.py:11](../../tools/test/apps/gold_price.py#L11).

```json
{
  "type": "object",
  "properties": {
    "type": {
      "type": "string",
      "enum": [
        "sjc",
        "ring",
        "world"
      ]
    }
  },
  "required": []
}
```

<a id="tool-fuel_price-get_price"></a>

### `fuel_price.get_price`

- App: `fuel_price`; miền chính: D07; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Giá theo loại nhiên liệu
- Tham số: `type`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `type`.
- Returns nguyên văn: `prices[]`
- Chứng cứ: [train /apps/23/tools/0](../../tools/train_tools_catalog.json#L2042); [public_test /apps/17/tools/0](../../tools/public_test_tools_catalog.json#L1658); mã [train/apps/fuel_price.py:11](../../tools/train/apps/fuel_price.py#L11); [test/apps/fuel_price.py:11](../../tools/test/apps/fuel_price.py#L11).

```json
{
  "type": "object",
  "properties": {
    "type": {
      "type": "string",
      "enum": [
        "ron95",
        "e5",
        "diesel"
      ]
    }
  },
  "required": []
}
```

<a id="tool-lottery-get_results"></a>

### `lottery.get_results`

- App: `lottery`; miền chính: D07; kind: `read`; split: train.
- Mô tả nguyên văn: Kết quả theo đài và ngày
- Tham số: `province`, `date`.
- Bắt buộc trực tiếp: `province`.
- Không thuộc required (có thể chịu x-one-of): `date`.
- Returns nguyên văn: `results`
- Chứng cứ: [train /apps/24/tools/0](../../tools/train_tools_catalog.json#L2071); mã [train/apps/lottery.py:26](../../tools/train/apps/lottery.py#L26).

```json
{
  "type": "object",
  "properties": {
    "province": {
      "type": "string"
    },
    "date": {
      "type": "string",
      "description": "YYYY-MM-DD, ví dụ 2026-11-29"
    }
  },
  "required": [
    "province"
  ]
}
```

<a id="tool-lottery-check_ticket"></a>

### `lottery.check_ticket`

- App: `lottery`; miền chính: D07; kind: `read`; split: train.
- Mô tả nguyên văn: Dò vé số
- Tham số: `province`, `date`, `number`.
- Bắt buộc trực tiếp: `province`, `date`, `number`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `check`
- Chứng cứ: [train /apps/24/tools/1](../../tools/train_tools_catalog.json#L2093); mã [train/apps/lottery.py:30](../../tools/train/apps/lottery.py#L30).

```json
{
  "type": "object",
  "properties": {
    "province": {
      "type": "string"
    },
    "date": {
      "type": "string",
      "description": "YYYY-MM-DD, ví dụ 2026-11-29"
    },
    "number": {
      "type": "string"
    }
  },
  "required": [
    "province",
    "date",
    "number"
  ]
}
```

<a id="tool-exchange_rate-get_rate"></a>

### `exchange_rate.get_rate`

- App: `exchange_rate`; miền chính: D07; kind: `read`; split: train.
- Mô tả nguyên văn: Tỷ giá cặp tiền
- Tham số: `from_currency`, `to_currency`.
- Bắt buộc trực tiếp: `from_currency`, `to_currency`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `rate`
- Chứng cứ: [train /apps/25/tools/0](../../tools/train_tools_catalog.json#L2128); mã [train/apps/exchange_rate.py:11](../../tools/train/apps/exchange_rate.py#L11).

```json
{
  "type": "object",
  "properties": {
    "from_currency": {
      "type": "string"
    },
    "to_currency": {
      "type": "string"
    }
  },
  "required": [
    "from_currency",
    "to_currency"
  ]
}
```

<a id="tool-exchange_rate-convert"></a>

### `exchange_rate.convert`

- App: `exchange_rate`; miền chính: D07; kind: `read`; split: train.
- Mô tả nguyên văn: Quy đổi số tiền
- Tham số: `amount`, `from_currency`, `to_currency`.
- Bắt buộc trực tiếp: `amount`, `from_currency`, `to_currency`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `result`
- Chứng cứ: [train /apps/25/tools/1](../../tools/train_tools_catalog.json#L2150); mã [train/apps/exchange_rate.py:34](../../tools/train/apps/exchange_rate.py#L34).

```json
{
  "type": "object",
  "properties": {
    "amount": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm, phẩy hay đơn vị, ví dụ 1200000",
      "minimum": 0
    },
    "from_currency": {
      "type": "string"
    },
    "to_currency": {
      "type": "string"
    }
  },
  "required": [
    "amount",
    "from_currency",
    "to_currency"
  ]
}
```

<a id="tool-news-headlines"></a>

### `news.headlines`

- App: `news`; miền chính: D07; kind: `read`; split: train.
- Mô tả nguyên văn: Tin nổi bật theo chủ đề
- Tham số: `topic`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `topic`.
- Returns nguyên văn: `articles[]`
- Chứng cứ: [train /apps/26/tools/0](../../tools/train_tools_catalog.json#L2186); mã [train/apps/news.py:12](../../tools/train/apps/news.py#L12).

```json
{
  "type": "object",
  "properties": {
    "topic": {
      "type": "string",
      "enum": [
        "general",
        "sports",
        "business",
        "tech",
        "entertainment"
      ],
      "description": "Chủ đề tin; bỏ trống để lấy tin nổi bật mọi chủ đề"
    }
  },
  "required": []
}
```

<a id="tool-news-search"></a>

### `news.search`

- App: `news`; miền chính: D07; kind: `read`; split: train.
- Mô tả nguyên văn: Tìm tin theo từ khoá (khớp theo từ khoá: chỉ cần một từ của query có trong tiêu đề/tóm tắt/nguồn/chủ đề)
- Tham số: `query`.
- Bắt buộc trực tiếp: `query`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `articles[]`
- Chứng cứ: [train /apps/26/tools/1](../../tools/train_tools_catalog.json#L2210); mã [train/apps/news.py:16](../../tools/train/apps/news.py#L16).

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Từ khoá tìm trong tiêu đề, tóm tắt, nguồn tin; khớp theo từ khoá, kết quả xếp theo số từ trùng"
    }
  },
  "required": [
    "query"
  ]
}
```

<a id="tool-news-save"></a>

### `news.save`

- App: `news`; miền chính: D07; kind: `write`; split: train.
- Mô tả nguyên văn: Lưu bài để đọc sau
- Tham số: `article_id`.
- Bắt buộc trực tiếp: `article_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/26/tools/2](../../tools/train_tools_catalog.json#L2229); mã [train/apps/news.py:32](../../tools/train/apps/news.py#L32).

```json
{
  "type": "object",
  "properties": {
    "article_id": {
      "type": "string",
      "description": "ID bài báo, lấy từ news.search hoặc news.headlines",
      "x-ref": "news.articles"
    }
  },
  "required": [
    "article_id"
  ]
}
```

<a id="tool-calculator-calculate"></a>

### `calculator.calculate`

- App: `calculator`; miền chính: D15; kind: `read`; split: train.
- Mô tả nguyên văn: Tính biểu thức
- Tham số: `expression`.
- Bắt buộc trực tiếp: `expression`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `value`
- Chứng cứ: [train /apps/27/tools/0](../../tools/train_tools_catalog.json#L2257); mã [train/apps/calculator.py:51](../../tools/train/apps/calculator.py#L51).

```json
{
  "type": "object",
  "properties": {
    "expression": {
      "type": "string",
      "x-match": "fuzzy",
      "description": "Biểu thức số học chỉ gồm số và + - * / ( ) . %, ví dụ (120000+85000)*3 hoặc 200000*15%"
    }
  },
  "required": [
    "expression"
  ]
}
```

<a id="tool-calculator-convert_unit"></a>

### `calculator.convert_unit`

- App: `calculator`; miền chính: D15; kind: `read`; split: train.
- Mô tả nguyên văn: Quy đổi đơn vị
- Tham số: `value`, `from_unit`, `to_unit`.
- Bắt buộc trực tiếp: `value`, `from_unit`, `to_unit`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `value`
- Chứng cứ: [train /apps/27/tools/1](../../tools/train_tools_catalog.json#L2277); mã [train/apps/calculator.py:70](../../tools/train/apps/calculator.py#L70).

```json
{
  "type": "object",
  "properties": {
    "value": {
      "type": "number",
      "description": "Số cần quy đổi, dấu chấm thập phân, ví dụ 1.5"
    },
    "from_unit": {
      "type": "string",
      "enum": [
        "mm",
        "cm",
        "m",
        "km",
        "g",
        "kg",
        "ml",
        "l",
        "c",
        "f"
      ],
      "description": "Đơn vị gốc: mm, cm, m, km (độ dài); g, kg (khối lượng); ml, l (thể tích); c, f (độ C, độ F)"
    },
    "to_unit": {
      "type": "string",
      "enum": [
        "mm",
        "cm",
        "m",
        "km",
        "g",
        "kg",
        "ml",
        "l",
        "c",
        "f"
      ],
      "description": "Đơn vị đích, cùng loại với from_unit"
    }
  },
  "required": [
    "value",
    "from_unit",
    "to_unit"
  ]
}
```

<a id="tool-maps-search_place"></a>

### `maps.search_place`

- App: `maps`; miền chính: D08; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Tìm địa điểm theo từ khoá (khớp theo từ khoá: chỉ cần một từ của query có trong tên/loại/mô tả/địa chỉ), gần vị trí tuỳ chọn
- Tham số: `query`, `near`.
- Bắt buộc trực tiếp: `query`.
- Không thuộc required (có thể chịu x-one-of): `near`.
- Returns nguyên văn: `places[]`
- Chứng cứ: [train /apps/28/tools/0](../../tools/train_tools_catalog.json#L2338); [public_test /apps/19/tools/0](../../tools/public_test_tools_catalog.json#L1724); mã [train/apps/maps.py:29](../../tools/train/apps/maps.py#L29); [test/apps/maps.py:29](../../tools/test/apps/maps.py#L29).

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Từ khoá tên hoặc loại địa điểm, ví dụ 'cà phê', 'rạp phim'; khớp theo từ khoá, kết quả xếp theo số từ trùng"
    },
    "near": {
      "type": "string",
      "description": "Khu vực/địa danh lân cận, ví dụ 'Hồ Tây'; khớp theo từ khoá trên địa chỉ/mô tả/tên (chỉ cần một từ trùng)",
      "x-match": "fuzzy"
    }
  },
  "required": [
    "query"
  ]
}
```

<a id="tool-maps-get_route"></a>

### `maps.get_route`

- App: `maps`; miền chính: D08; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Chỉ đường và thời gian dự kiến
- Tham số: `origin`, `destination`, `mode`.
- Bắt buộc trực tiếp: `origin`, `destination`.
- Không thuộc required (có thể chịu x-one-of): `mode`.
- Returns nguyên văn: `route{distance_km, duration_min}`
- Chứng cứ: [train /apps/28/tools/1](../../tools/train_tools_catalog.json#L2362); [public_test /apps/19/tools/1](../../tools/public_test_tools_catalog.json#L1748); mã [train/apps/maps.py:54](../../tools/train/apps/maps.py#L54); [test/apps/maps.py:54](../../tools/test/apps/maps.py#L54).

```json
{
  "type": "object",
  "properties": {
    "origin": {
      "type": "string",
      "description": "Điểm đi: địa chỉ hoặc tên địa điểm; 'nhà' → home_address của profile",
      "x-match": "fuzzy"
    },
    "destination": {
      "type": "string",
      "description": "Điểm đến: địa chỉ hoặc tên địa điểm; 'công ty' → work_address của profile",
      "x-match": "fuzzy"
    },
    "mode": {
      "type": "string",
      "enum": [
        "car",
        "motorbike",
        "walk",
        "transit"
      ],
      "description": "Phương tiện; mặc định motorbike"
    }
  },
  "required": [
    "origin",
    "destination"
  ]
}
```

<a id="tool-maps-save_place"></a>

### `maps.save_place`

- App: `maps`; miền chính: D08; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Lưu địa điểm yêu thích
- Tham số: `place_id`, `label`.
- Bắt buộc trực tiếp: `place_id`, `label`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/28/tools/2](../../tools/train_tools_catalog.json#L2398); [public_test /apps/19/tools/2](../../tools/public_test_tools_catalog.json#L1784); mã [train/apps/maps.py:75](../../tools/train/apps/maps.py#L75); [test/apps/maps.py:75](../../tools/test/apps/maps.py#L75).

```json
{
  "type": "object",
  "properties": {
    "place_id": {
      "type": "string",
      "description": "ID địa điểm, lấy từ maps.search_place",
      "x-ref": "maps.places"
    },
    "label": {
      "type": "string",
      "x-match": "fuzzy"
    }
  },
  "required": [
    "place_id",
    "label"
  ]
}
```

<a id="tool-food_delivery-list_restaurants"></a>

### `food_delivery.list_restaurants`

- App: `food_delivery`; miền chính: D10; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Danh sách quán giao tận nơi quanh đây (tên, nhóm món, đánh giá)
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `restaurants[]`
- Chứng cứ: [train /apps/29/tools/0](../../tools/train_tools_catalog.json#L2431); [public_test /apps/20/tools/0](../../tools/public_test_tools_catalog.json#L1817); mã [train/apps/food_delivery.py:11](../../tools/train/apps/food_delivery.py#L11); [test/apps/food_delivery.py:11](../../tools/test/apps/food_delivery.py#L11).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-food_delivery-get_menu"></a>

### `food_delivery.get_menu`

- App: `food_delivery`; miền chính: D10; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Thực đơn quán
- Tham số: `restaurant_id`.
- Bắt buộc trực tiếp: `restaurant_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `menu[]`
- Chứng cứ: [train /apps/29/tools/1](../../tools/train_tools_catalog.json#L2443); [public_test /apps/20/tools/1](../../tools/public_test_tools_catalog.json#L1829); mã [train/apps/food_delivery.py:15](../../tools/train/apps/food_delivery.py#L15); [test/apps/food_delivery.py:15](../../tools/test/apps/food_delivery.py#L15).

```json
{
  "type": "object",
  "properties": {
    "restaurant_id": {
      "type": "string",
      "description": "ID quán, lấy từ food_delivery.list_restaurants",
      "x-ref": "food_delivery.restaurants"
    }
  },
  "required": [
    "restaurant_id"
  ]
}
```

<a id="tool-food_delivery-order_history"></a>

### `food_delivery.order_history`

- App: `food_delivery`; miền chính: D10; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Đơn đã đặt gần đây
- Tham số: `limit`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `limit`.
- Returns nguyên văn: `orders[]`
- Chứng cứ: [train /apps/29/tools/2](../../tools/train_tools_catalog.json#L2463); [public_test /apps/20/tools/2](../../tools/public_test_tools_catalog.json#L1849); mã [train/apps/food_delivery.py:22](../../tools/train/apps/food_delivery.py#L22); [test/apps/food_delivery.py:22](../../tools/test/apps/food_delivery.py#L22).

```json
{
  "type": "object",
  "properties": {
    "limit": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2"
    }
  },
  "required": []
}
```

<a id="tool-food_delivery-place_order"></a>

### `food_delivery.place_order`

- App: `food_delivery`; miền chính: D10; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Đặt đơn
- Tham số: `restaurant_id`, `items`, `address`, `payment`.
- Bắt buộc trực tiếp: `restaurant_id`, `items`.
- Không thuộc required (có thể chịu x-one-of): `address`, `payment`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/29/tools/3](../../tools/train_tools_catalog.json#L2480); [public_test /apps/20/tools/3](../../tools/public_test_tools_catalog.json#L1866); mã [train/apps/food_delivery.py:26](../../tools/train/apps/food_delivery.py#L26); [test/apps/food_delivery.py:26](../../tools/test/apps/food_delivery.py#L26).

```json
{
  "type": "object",
  "properties": {
    "restaurant_id": {
      "type": "string",
      "description": "ID quán, lấy từ food_delivery.list_restaurants",
      "x-ref": "food_delivery.restaurants"
    },
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "item_id": {
            "type": "string"
          },
          "quantity": {
            "type": "integer"
          },
          "note": {
            "type": "string"
          }
        },
        "required": [
          "item_id",
          "quantity"
        ]
      }
    },
    "address": {
      "type": "string",
      "x-match": "fuzzy"
    },
    "payment": {
      "type": "string",
      "enum": [
        "cash",
        "ewallet",
        "bank"
      ]
    }
  },
  "required": [
    "restaurant_id",
    "items"
  ]
}
```

<a id="tool-food_delivery-cancel_order"></a>

### `food_delivery.cancel_order`

- App: `food_delivery`; miền chính: D10; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Huỷ đơn đang chờ
- Tham số: `order_id`.
- Bắt buộc trực tiếp: `order_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/29/tools/4](../../tools/train_tools_catalog.json#L2534); [public_test /apps/20/tools/4](../../tools/public_test_tools_catalog.json#L1920); mã [train/apps/food_delivery.py:46](../../tools/train/apps/food_delivery.py#L46); [test/apps/food_delivery.py:46](../../tools/test/apps/food_delivery.py#L46).

```json
{
  "type": "object",
  "properties": {
    "order_id": {
      "type": "string",
      "description": "ID đơn, lấy từ food_delivery.order_history",
      "x-ref": "food_delivery.orders"
    }
  },
  "required": [
    "order_id"
  ]
}
```

<a id="tool-ride_hailing-get_quotes"></a>

### `ride_hailing.get_quotes`

- App: `ride_hailing`; miền chính: D08; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Báo giá và thời gian đón
- Tham số: `pickup`, `dropoff`, `vehicle`.
- Bắt buộc trực tiếp: `pickup`, `dropoff`.
- Không thuộc required (có thể chịu x-one-of): `vehicle`.
- Returns nguyên văn: `quotes[]`
- Chứng cứ: [train /apps/30/tools/0](../../tools/train_tools_catalog.json#L2562); [public_test /apps/23/tools/0](../../tools/public_test_tools_catalog.json#L2093); mã [train/apps/ride_hailing.py:30](../../tools/train/apps/ride_hailing.py#L30); [test/apps/ride_hailing.py:30](../../tools/test/apps/ride_hailing.py#L30).

```json
{
  "type": "object",
  "properties": {
    "pickup": {
      "type": "string",
      "x-match": "fuzzy"
    },
    "dropoff": {
      "type": "string",
      "x-match": "fuzzy"
    },
    "vehicle": {
      "type": "string",
      "enum": [
        "bike",
        "car4",
        "car7"
      ]
    }
  },
  "required": [
    "pickup",
    "dropoff"
  ]
}
```

<a id="tool-ride_hailing-book"></a>

### `ride_hailing.book`

- App: `ride_hailing`; miền chính: D08; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Đặt chuyến
- Tham số: `pickup`, `dropoff`, `vehicle`, `schedule_time`, `payment`.
- Bắt buộc trực tiếp: `pickup`, `dropoff`, `vehicle`.
- Không thuộc required (có thể chịu x-one-of): `schedule_time`, `payment`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/30/tools/1](../../tools/train_tools_catalog.json#L2594); [public_test /apps/23/tools/1](../../tools/public_test_tools_catalog.json#L2125); mã [train/apps/ride_hailing.py:34](../../tools/train/apps/ride_hailing.py#L34); [test/apps/ride_hailing.py:34](../../tools/test/apps/ride_hailing.py#L34).

```json
{
  "type": "object",
  "properties": {
    "pickup": {
      "type": "string",
      "x-match": "fuzzy",
      "description": "Điểm đón: địa chỉ hoặc tên địa điểm; 'nhà'/'công ty' → home_address/work_address của profile"
    },
    "dropoff": {
      "type": "string",
      "x-match": "fuzzy",
      "description": "Điểm đến: địa chỉ hoặc tên địa điểm (lấy từ lịch/kết quả tìm kiếm khi người dùng chỉ việc đó)"
    },
    "vehicle": {
      "type": "string",
      "enum": [
        "bike",
        "car4",
        "car7"
      ]
    },
    "schedule_time": {
      "type": "string",
      "description": "Giờ đón khi đặt trước, ISO-8601 đầy đủ giây và offset múi giờ, ví dụ 2026-11-11T05:30:00+07:00; bỏ trống khi đặt ngay (giờ bằng hoặc trước current_time cũng coi là đặt ngay)"
    },
    "payment": {
      "type": "string",
      "enum": [
        "cash",
        "ewallet"
      ]
    }
  },
  "required": [
    "pickup",
    "dropoff",
    "vehicle"
  ]
}
```

<a id="tool-ride_hailing-cancel"></a>

### `ride_hailing.cancel`

- App: `ride_hailing`; miền chính: D08; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Huỷ chuyến
- Tham số: `ride_id`.
- Bắt buộc trực tiếp: `ride_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/30/tools/2](../../tools/train_tools_catalog.json#L2640); [public_test /apps/23/tools/2](../../tools/public_test_tools_catalog.json#L2171); mã [train/apps/ride_hailing.py:41](../../tools/train/apps/ride_hailing.py#L41); [test/apps/ride_hailing.py:41](../../tools/test/apps/ride_hailing.py#L41).

```json
{
  "type": "object",
  "properties": {
    "ride_id": {
      "type": "string",
      "description": "ID chuyến xe, lấy từ ride_hailing.get_ride",
      "x-ref": "ride_hailing.rides"
    }
  },
  "required": [
    "ride_id"
  ]
}
```

<a id="tool-ride_hailing-get_ride"></a>

### `ride_hailing.get_ride`

- App: `ride_hailing`; miền chính: D08; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Trạng thái chuyến hiện tại
- Tham số: `ride_id`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `ride_id`.
- Returns nguyên văn: `ride`
- Chứng cứ: [train /apps/30/tools/3](../../tools/train_tools_catalog.json#L2660); [public_test /apps/23/tools/3](../../tools/public_test_tools_catalog.json#L2191); mã [train/apps/ride_hailing.py:45](../../tools/train/apps/ride_hailing.py#L45); [test/apps/ride_hailing.py:45](../../tools/test/apps/ride_hailing.py#L45).

```json
{
  "type": "object",
  "properties": {
    "ride_id": {
      "type": "string",
      "description": "ID chuyến xe, lấy từ ride_hailing.get_ride",
      "x-ref": "ride_hailing.rides"
    }
  },
  "required": []
}
```

<a id="tool-flights-search"></a>

### `flights.search`

- App: `flights`; miền chính: D09; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Tìm chuyến bay theo điểm đi, điểm đến và ngày
- Tham số: `origin`, `destination`, `date`, `passengers`.
- Bắt buộc trực tiếp: `origin`, `destination`, `date`.
- Không thuộc required (có thể chịu x-one-of): `passengers`.
- Returns nguyên văn: `flights[]`
- Chứng cứ: [train /apps/31/tools/0](../../tools/train_tools_catalog.json#L2686); [public_test /apps/26/tools/0](../../tools/public_test_tools_catalog.json#L2386); mã [train/apps/flights.py:67](../../tools/train/apps/flights.py#L67); [test/apps/flights.py:67](../../tools/test/apps/flights.py#L67).

```json
{
  "type": "object",
  "properties": {
    "origin": {
      "type": "string",
      "description": "Điểm đi: mã IATA (SGN, HAN, DAD) hoặc tên thành phố, ví dụ 'Hà Nội'"
    },
    "destination": {
      "type": "string",
      "description": "Điểm đến: mã IATA (SGN, HAN, DAD) hoặc tên thành phố, ví dụ 'Đà Nẵng'"
    },
    "date": {
      "type": "string",
      "description": "YYYY-MM-DD, ví dụ 2026-11-29"
    },
    "passengers": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2"
    }
  },
  "required": [
    "origin",
    "destination",
    "date"
  ]
}
```

<a id="tool-flights-book"></a>

### `flights.book`

- App: `flights`; miền chính: D09; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Đặt vé
- Tham số: `flight_id`, `passengers`, `seat_class`.
- Bắt buộc trực tiếp: `flight_id`, `passengers`.
- Không thuộc required (có thể chịu x-one-of): `seat_class`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/31/tools/1](../../tools/train_tools_catalog.json#L2719); [public_test /apps/26/tools/1](../../tools/public_test_tools_catalog.json#L2419); mã [train/apps/flights.py:74](../../tools/train/apps/flights.py#L74); [test/apps/flights.py:74](../../tools/test/apps/flights.py#L74).

```json
{
  "type": "object",
  "properties": {
    "flight_id": {
      "type": "string",
      "description": "ID chuyến bay, lấy từ flights.search",
      "x-ref": "flights.flights"
    },
    "passengers": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2"
    },
    "seat_class": {
      "type": "string",
      "enum": [
        "economy",
        "business"
      ]
    }
  },
  "required": [
    "flight_id",
    "passengers"
  ]
}
```

<a id="tool-flights-my_bookings"></a>

### `flights.my_bookings`

- App: `flights`; miền chính: D09; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Vé đã đặt
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `bookings[]`
- Chứng cứ: [train /apps/31/tools/2](../../tools/train_tools_catalog.json#L2751); [public_test /apps/26/tools/2](../../tools/public_test_tools_catalog.json#L2451); mã [train/apps/flights.py:84](../../tools/train/apps/flights.py#L84); [test/apps/flights.py:84](../../tools/test/apps/flights.py#L84).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-flights-cancel"></a>

### `flights.cancel`

- App: `flights`; miền chính: D09; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Huỷ vé
- Tham số: `booking_id`.
- Bắt buộc trực tiếp: `booking_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/31/tools/3](../../tools/train_tools_catalog.json#L2763); [public_test /apps/26/tools/3](../../tools/public_test_tools_catalog.json#L2463); mã [train/apps/flights.py:93](../../tools/train/apps/flights.py#L93); [test/apps/flights.py:93](../../tools/test/apps/flights.py#L93).

```json
{
  "type": "object",
  "properties": {
    "booking_id": {
      "type": "string",
      "description": "ID vé đã đặt, lấy từ flights.my_bookings",
      "x-ref": "flights.bookings"
    }
  },
  "required": [
    "booking_id"
  ]
}
```

<a id="tool-flights-check_in"></a>

### `flights.check_in`

- App: `flights`; miền chính: D09; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Làm thủ tục online
- Tham số: `booking_id`.
- Bắt buộc trực tiếp: `booking_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/31/tools/4](../../tools/train_tools_catalog.json#L2783); [public_test /apps/26/tools/4](../../tools/public_test_tools_catalog.json#L2483); mã [train/apps/flights.py:97](../../tools/train/apps/flights.py#L97); [test/apps/flights.py:97](../../tools/test/apps/flights.py#L97).

```json
{
  "type": "object",
  "properties": {
    "booking_id": {
      "type": "string",
      "description": "ID vé đã đặt, lấy từ flights.my_bookings",
      "x-ref": "flights.bookings"
    }
  },
  "required": [
    "booking_id"
  ]
}
```

<a id="tool-shopping_list-get"></a>

### `shopping_list.get`

- App: `shopping_list`; miền chính: D11; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Xem danh sách
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `items[]`
- Chứng cứ: [train /apps/32/tools/0](../../tools/train_tools_catalog.json#L2811); [public_test /apps/29/tools/0](../../tools/public_test_tools_catalog.json#L2764); mã [train/apps/shopping_list.py:11](../../tools/train/apps/shopping_list.py#L11); [test/apps/shopping_list.py:11](../../tools/test/apps/shopping_list.py#L11).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-shopping_list-add"></a>

### `shopping_list.add`

- App: `shopping_list`; miền chính: D11; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Thêm món
- Tham số: `name`, `quantity`.
- Bắt buộc trực tiếp: `name`.
- Không thuộc required (có thể chịu x-one-of): `quantity`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/32/tools/1](../../tools/train_tools_catalog.json#L2823); [public_test /apps/29/tools/1](../../tools/public_test_tools_catalog.json#L2776); mã [train/apps/shopping_list.py:15](../../tools/train/apps/shopping_list.py#L15); [test/apps/shopping_list.py:15](../../tools/test/apps/shopping_list.py#L15).

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "x-match": "fuzzy",
      "description": "Tên món cần mua, ví dụ dưa chuột"
    },
    "quantity": {
      "type": "integer",
      "description": "Số lượng, số nguyên, không dấu chấm hay phẩy, ví dụ 2; mặc định 1",
      "exclusiveMinimum": 0
    }
  },
  "required": [
    "name"
  ]
}
```

<a id="tool-shopping_list-remove"></a>

### `shopping_list.remove`

- App: `shopping_list`; miền chính: D11; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Xoá món
- Tham số: `item_id`.
- Bắt buộc trực tiếp: `item_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/32/tools/2](../../tools/train_tools_catalog.json#L2848); [public_test /apps/29/tools/2](../../tools/public_test_tools_catalog.json#L2801); mã [train/apps/shopping_list.py:24](../../tools/train/apps/shopping_list.py#L24); [test/apps/shopping_list.py:24](../../tools/test/apps/shopping_list.py#L24).

```json
{
  "type": "object",
  "properties": {
    "item_id": {
      "type": "string",
      "description": "ID món, lấy từ shopping_list.get",
      "x-ref": "shopping_list.items"
    }
  },
  "required": [
    "item_id"
  ]
}
```

<a id="tool-shopping_list-check"></a>

### `shopping_list.check`

- App: `shopping_list`; miền chính: D11; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Đánh dấu đã mua
- Tham số: `item_id`.
- Bắt buộc trực tiếp: `item_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/32/tools/3](../../tools/train_tools_catalog.json#L2868); [public_test /apps/29/tools/3](../../tools/public_test_tools_catalog.json#L2821); mã [train/apps/shopping_list.py:28](../../tools/train/apps/shopping_list.py#L28); [test/apps/shopping_list.py:28](../../tools/test/apps/shopping_list.py#L28).

```json
{
  "type": "object",
  "properties": {
    "item_id": {
      "type": "string",
      "description": "ID món, lấy từ shopping_list.get",
      "x-ref": "shopping_list.items"
    }
  },
  "required": [
    "item_id"
  ]
}
```

<a id="tool-package_tracking-track"></a>

### `package_tracking.track`

- App: `package_tracking`; miền chính: D11; kind: `read`; split: train.
- Mô tả nguyên văn: Trạng thái vận đơn (không truyền tracking_id: mọi kiện đang theo dõi)
- Tham số: `tracking_id`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `tracking_id`.
- Returns nguyên văn: `shipments[]`
- Chứng cứ: [train /apps/33/tools/0](../../tools/train_tools_catalog.json#L2896); mã [train/apps/package_tracking.py:20](../../tools/train/apps/package_tracking.py#L20).

```json
{
  "type": "object",
  "properties": {
    "tracking_id": {
      "type": "string",
      "description": "Mã vận đơn, giữ nguyên chuỗi, ví dụ GST583920174; lấy từ package_tracking.track"
    }
  },
  "required": []
}
```

<a id="tool-package_tracking-reschedule_delivery"></a>

### `package_tracking.reschedule_delivery`

- App: `package_tracking`; miền chính: D11; kind: `write`; split: train.
- Mô tả nguyên văn: Hẹn lại giờ giao
- Tham số: `tracking_id`, `time`.
- Bắt buộc trực tiếp: `tracking_id`, `time`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `shipment`
- Chứng cứ: [train /apps/33/tools/1](../../tools/train_tools_catalog.json#L2913); mã [train/apps/package_tracking.py:29](../../tools/train/apps/package_tracking.py#L29).

```json
{
  "type": "object",
  "properties": {
    "tracking_id": {
      "type": "string",
      "description": "Mã vận đơn, giữ nguyên chuỗi, ví dụ GST583920174; lấy từ package_tracking.track"
    },
    "time": {
      "type": "string",
      "description": "ISO-8601 đầy đủ giây và offset múi giờ, ví dụ 2026-11-11T05:30:00+07:00"
    }
  },
  "required": [
    "tracking_id",
    "time"
  ]
}
```

<a id="tool-package_tracking-schedule_pickup"></a>

### `package_tracking.schedule_pickup`

- App: `package_tracking`; miền chính: D11; kind: `write`; split: train.
- Mô tả nguyên văn: Hẹn bưu tá đến lấy hàng gửi đi
- Tham số: `address`, `date`.
- Bắt buộc trực tiếp: `address`, `date`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `pickup`
- Chứng cứ: [train /apps/33/tools/2](../../tools/train_tools_catalog.json#L2937); mã [train/apps/package_tracking.py:39](../../tools/train/apps/package_tracking.py#L39).

```json
{
  "type": "object",
  "properties": {
    "address": {
      "type": "string",
      "description": "Địa chỉ lấy hàng, giữ nguyên như người dùng nói, ví dụ 18 phố Hàng Cót",
      "x-match": "fuzzy"
    },
    "date": {
      "type": "string",
      "description": "YYYY-MM-DD, ví dụ 2026-11-29",
      "format": "date"
    }
  },
  "required": [
    "address",
    "date"
  ]
}
```

<a id="tool-music-list_tracks"></a>

### `music.list_tracks`

- App: `music`; miền chính: D12; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Thư viện bài hát và playlist
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `tracks[], playlists[]`
- Chứng cứ: [train /apps/34/tools/0](../../tools/train_tools_catalog.json#L2971); [public_test /apps/30/tools/0](../../tools/public_test_tools_catalog.json#L2849); mã [train/apps/music.py:11](../../tools/train/apps/music.py#L11); [test/apps/music.py:11](../../tools/test/apps/music.py#L11).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-music-play"></a>

### `music.play`

- App: `music`; miền chính: D12; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Phát một bài hoặc một playlist. Bắt buộc một trong: track_id hoặc playlist_id
- Tham số: `track_id`, `playlist_id`, `device`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `track_id`, `playlist_id`, `device`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/34/tools/1](../../tools/train_tools_catalog.json#L2983); [public_test /apps/30/tools/1](../../tools/public_test_tools_catalog.json#L2861); mã [train/apps/music.py:19](../../tools/train/apps/music.py#L19); [test/apps/music.py:19](../../tools/test/apps/music.py#L19).

```json
{
  "type": "object",
  "properties": {
    "track_id": {
      "type": "string",
      "description": "ID bài hát, lấy từ music.list_tracks",
      "x-ref": "music.tracks"
    },
    "playlist_id": {
      "type": "string",
      "description": "ID playlist, lấy từ music.list_tracks",
      "x-ref": "music.playlists"
    },
    "device": {
      "type": "string"
    }
  },
  "required": [],
  "x-one-of": [
    [
      "track_id"
    ],
    [
      "playlist_id"
    ]
  ]
}
```

<a id="tool-music-control"></a>

### `music.control`

- App: `music`; miền chính: D12; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Tạm dừng/tiếp tục/chuyển bài/âm lượng
- Tham số: `action`, `volume`.
- Bắt buộc trực tiếp: `action`.
- Không thuộc required (có thể chịu x-one-of): `volume`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/34/tools/2](../../tools/train_tools_catalog.json#L3017); [public_test /apps/30/tools/2](../../tools/public_test_tools_catalog.json#L2895); mã [train/apps/music.py:35](../../tools/train/apps/music.py#L35); [test/apps/music.py:35](../../tools/test/apps/music.py#L35).

```json
{
  "type": "object",
  "properties": {
    "action": {
      "type": "string",
      "enum": [
        "pause",
        "resume",
        "next",
        "previous",
        "volume"
      ]
    },
    "volume": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2"
    }
  },
  "required": [
    "action"
  ]
}
```

<a id="tool-music-add_to_playlist"></a>

### `music.add_to_playlist`

- App: `music`; miền chính: D12; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Thêm bài vào playlist
- Tham số: `track_id`, `playlist_id`.
- Bắt buộc trực tiếp: `track_id`, `playlist_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/34/tools/3](../../tools/train_tools_catalog.json#L3046); [public_test /apps/30/tools/3](../../tools/public_test_tools_catalog.json#L2924); mã [train/apps/music.py:46](../../tools/train/apps/music.py#L46); [test/apps/music.py:46](../../tools/test/apps/music.py#L46).

```json
{
  "type": "object",
  "properties": {
    "track_id": {
      "type": "string",
      "description": "ID bài hát, lấy từ music.list_tracks",
      "x-ref": "music.tracks"
    },
    "playlist_id": {
      "type": "string",
      "description": "ID playlist, lấy từ music.list_tracks",
      "x-ref": "music.playlists"
    }
  },
  "required": [
    "track_id",
    "playlist_id"
  ]
}
```

<a id="tool-tv-guide"></a>

### `tv.guide`

- App: `tv`; miền chính: D12; kind: `read`; split: train, public_test.
- Mô tả nguyên văn: Danh sách kênh đang có và lịch phát sóng (gọi trước khi chuyển kênh)
- Tham số: `channel`, `date`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `channel`, `date`.
- Returns nguyên văn: `programs[], channels[]`
- Chứng cứ: [train /apps/35/tools/0](../../tools/train_tools_catalog.json#L3080); [public_test /apps/31/tools/0](../../tools/public_test_tools_catalog.json#L2958); mã [train/apps/tv.py:11](../../tools/train/apps/tv.py#L11); [test/apps/tv.py:11](../../tools/test/apps/tv.py#L11).

```json
{
  "type": "object",
  "properties": {
    "channel": {
      "type": "string"
    },
    "date": {
      "type": "string",
      "description": "YYYY-MM-DD, ví dụ 2026-11-29"
    }
  },
  "required": []
}
```

<a id="tool-tv-tune"></a>

### `tv.tune`

- App: `tv`; miền chính: D12; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Chuyển kênh (tự bật TV nếu đang tắt); kênh phải có trong channels của tv.guide
- Tham số: `channel`.
- Bắt buộc trực tiếp: `channel`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/35/tools/1](../../tools/train_tools_catalog.json#L3100); [public_test /apps/31/tools/1](../../tools/public_test_tools_catalog.json#L2978); mã [train/apps/tv.py:19](../../tools/train/apps/tv.py#L19); [test/apps/tv.py:19](../../tools/test/apps/tv.py#L19).

```json
{
  "type": "object",
  "properties": {
    "channel": {
      "type": "string"
    }
  },
  "required": [
    "channel"
  ]
}
```

<a id="tool-tv-control"></a>

### `tv.control`

- App: `tv`; miền chính: D12; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Bật/tắt/âm lượng TV
- Tham số: `action`, `volume`.
- Bắt buộc trực tiếp: `action`.
- Không thuộc required (có thể chịu x-one-of): `volume`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/35/tools/2](../../tools/train_tools_catalog.json#L3118); [public_test /apps/31/tools/2](../../tools/public_test_tools_catalog.json#L2996); mã [train/apps/tv.py:26](../../tools/train/apps/tv.py#L26); [test/apps/tv.py:26](../../tools/test/apps/tv.py#L26).

```json
{
  "type": "object",
  "properties": {
    "action": {
      "type": "string",
      "enum": [
        "on",
        "off",
        "volume",
        "mute"
      ]
    },
    "volume": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2"
    }
  },
  "required": [
    "action"
  ]
}
```

<a id="tool-tv-record"></a>

### `tv.record`

- App: `tv`; miền chính: D12; kind: `write`; split: train, public_test.
- Mô tả nguyên văn: Đặt ghi hình chương trình
- Tham số: `program_id`.
- Bắt buộc trực tiếp: `program_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/35/tools/3](../../tools/train_tools_catalog.json#L3146); [public_test /apps/31/tools/3](../../tools/public_test_tools_catalog.json#L3024); mã [train/apps/tv.py:36](../../tools/train/apps/tv.py#L36); [test/apps/tv.py:36](../../tools/test/apps/tv.py#L36).

```json
{
  "type": "object",
  "properties": {
    "program_id": {
      "type": "string",
      "description": "ID chương trình, lấy từ tv.guide",
      "x-ref": "tv.programs"
    }
  },
  "required": [
    "program_id"
  ]
}
```

<a id="tool-podcast_radio-search"></a>

### `podcast_radio.search`

- App: `podcast_radio`; miền chính: D12; kind: `read`; split: train.
- Mô tả nguyên văn: Tìm kênh/tập podcast, radio; trả về kênh, các tập của kênh và đài radio khớp; query "*" liệt kê tất cả
- Tham số: `query`.
- Bắt buộc trực tiếp: `query`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `shows[], episodes[], stations[]`
- Chứng cứ: [train /apps/36/tools/0](../../tools/train_tools_catalog.json#L3174); mã [train/apps/podcast_radio.py:15](../../tools/train/apps/podcast_radio.py#L15).

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Tên kênh, tên tập, chủ đề hoặc tên đài"
    }
  },
  "required": [
    "query"
  ]
}
```

<a id="tool-podcast_radio-play"></a>

### `podcast_radio.play`

- App: `podcast_radio`; miền chính: D12; kind: `write`; split: train.
- Mô tả nguyên văn: Phát một tập podcast hoặc một kênh radio. Bắt buộc một trong: episode_id hoặc station
- Tham số: `episode_id`, `station`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `episode_id`, `station`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/36/tools/1](../../tools/train_tools_catalog.json#L3193); mã [train/apps/podcast_radio.py:35](../../tools/train/apps/podcast_radio.py#L35).

```json
{
  "type": "object",
  "properties": {
    "episode_id": {
      "type": "string",
      "description": "ID tập podcast, lấy từ podcast_radio.search",
      "x-ref": "podcast_radio.episodes"
    },
    "station": {
      "type": "string",
      "description": "Tên hoặc tần số đài radio, ví dụ VOV Giao thông"
    }
  },
  "required": [],
  "x-one-of": [
    [
      "episode_id"
    ],
    [
      "station"
    ]
  ]
}
```

<a id="tool-podcast_radio-subscribe"></a>

### `podcast_radio.subscribe`

- App: `podcast_radio`; miền chính: D12; kind: `write`; split: train.
- Mô tả nguyên văn: Theo dõi kênh
- Tham số: `show_id`.
- Bắt buộc trực tiếp: `show_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/36/tools/2](../../tools/train_tools_catalog.json#L3223); mã [train/apps/podcast_radio.py:54](../../tools/train/apps/podcast_radio.py#L54).

```json
{
  "type": "object",
  "properties": {
    "show_id": {
      "type": "string",
      "description": "ID kênh podcast, lấy từ podcast_radio.search",
      "x-ref": "podcast_radio.shows"
    }
  },
  "required": [
    "show_id"
  ]
}
```

<a id="tool-podcast_radio-queue"></a>

### `podcast_radio.queue`

- App: `podcast_radio`; miền chính: D12; kind: `write`; split: train.
- Mô tả nguyên văn: Thêm một tập podcast vào hàng đợi nghe sau
- Tham số: `episode_id`.
- Bắt buộc trực tiếp: `episode_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/36/tools/3](../../tools/train_tools_catalog.json#L3243); mã [train/apps/podcast_radio.py:64](../../tools/train/apps/podcast_radio.py#L64).

```json
{
  "type": "object",
  "properties": {
    "episode_id": {
      "type": "string",
      "description": "ID tập podcast, lấy từ podcast_radio.search",
      "x-ref": "podcast_radio.episodes"
    }
  },
  "required": [
    "episode_id"
  ]
}
```

<a id="tool-medication-list"></a>

### `medication.list`

- App: `medication`; miền chính: D13; kind: `read`; split: train.
- Mô tả nguyên văn: Lịch thuốc
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `schedules[]`
- Chứng cứ: [train /apps/37/tools/0](../../tools/train_tools_catalog.json#L3271); mã [train/apps/medication.py:11](../../tools/train/apps/medication.py#L11).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-medication-add"></a>

### `medication.add`

- App: `medication`; miền chính: D13; kind: `write`; split: train.
- Mô tả nguyên văn: Thêm nhắc thuốc
- Tham số: `name`, `times`, `days`.
- Bắt buộc trực tiếp: `name`, `times`.
- Không thuộc required (có thể chịu x-one-of): `days`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/37/tools/1](../../tools/train_tools_catalog.json#L3283); mã [train/apps/medication.py:15](../../tools/train/apps/medication.py#L15).

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "x-match": "fuzzy"
    },
    "times": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "days": {
      "type": "string",
      "enum": [
        "daily",
        "weekdays"
      ]
    }
  },
  "required": [
    "name",
    "times"
  ]
}
```

<a id="tool-medication-log_taken"></a>

### `medication.log_taken`

- App: `medication`; miền chính: D13; kind: `write`; split: train.
- Mô tả nguyên văn: Ghi đã uống
- Tham số: `schedule_id`, `time`.
- Bắt buộc trực tiếp: `schedule_id`.
- Không thuộc required (có thể chịu x-one-of): `time`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/37/tools/2](../../tools/train_tools_catalog.json#L3316); mã [train/apps/medication.py:19](../../tools/train/apps/medication.py#L19).

```json
{
  "type": "object",
  "properties": {
    "schedule_id": {
      "type": "string",
      "description": "ID lịch thuốc, lấy từ medication.list",
      "x-ref": "medication.schedules"
    },
    "time": {
      "type": "string",
      "description": "ISO-8601 đầy đủ giây và offset múi giờ, ví dụ 2026-11-11T05:30:00+07:00"
    }
  },
  "required": [
    "schedule_id"
  ]
}
```

<a id="tool-medication-remove"></a>

### `medication.remove`

- App: `medication`; miền chính: D13; kind: `write`; split: train.
- Mô tả nguyên văn: Xoá lịch thuốc
- Tham số: `schedule_id`.
- Bắt buộc trực tiếp: `schedule_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/37/tools/3](../../tools/train_tools_catalog.json#L3340); mã [train/apps/medication.py:28](../../tools/train/apps/medication.py#L28).

```json
{
  "type": "object",
  "properties": {
    "schedule_id": {
      "type": "string",
      "description": "ID lịch thuốc, lấy từ medication.list",
      "x-ref": "medication.schedules"
    }
  },
  "required": [
    "schedule_id"
  ]
}
```

<a id="tool-fitness-get_activity"></a>

### `fitness.get_activity`

- App: `fitness`; miền chính: D13; kind: `read`; split: train.
- Mô tả nguyên văn: Số bước/calo theo ngày (bỏ trống: ngày gần nhất)
- Tham số: `date`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `date`.
- Returns nguyên văn: `activity`
- Chứng cứ: [train /apps/38/tools/0](../../tools/train_tools_catalog.json#L3368); mã [train/apps/fitness.py:15](../../tools/train/apps/fitness.py#L15).

```json
{
  "type": "object",
  "properties": {
    "date": {
      "type": "string",
      "description": "YYYY-MM-DD, ví dụ 2026-11-29",
      "format": "date"
    }
  },
  "required": []
}
```

<a id="tool-fitness-log_workout"></a>

### `fitness.log_workout`

- App: `fitness`; miền chính: D13; kind: `write`; split: train.
- Mô tả nguyên văn: Ghi buổi tập
- Tham số: `type`, `minutes`, `time`.
- Bắt buộc trực tiếp: `type`, `minutes`.
- Không thuộc required (có thể chịu x-one-of): `time`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/38/tools/1](../../tools/train_tools_catalog.json#L3386); mã [train/apps/fitness.py:29](../../tools/train/apps/fitness.py#L29).

```json
{
  "type": "object",
  "properties": {
    "type": {
      "type": "string",
      "description": "Loại bài tập: walking đi bộ, running chạy bộ, cycling đạp xe, swimming bơi, yoga, gym tập tạ/thể hình, football đá bóng, badminton cầu lông, other loại khác",
      "enum": [
        "walking",
        "running",
        "cycling",
        "swimming",
        "yoga",
        "gym",
        "football",
        "badminton",
        "other"
      ]
    },
    "minutes": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2",
      "exclusiveMinimum": 0
    },
    "time": {
      "type": "string",
      "description": "ISO-8601 đầy đủ giây và offset múi giờ, ví dụ 2026-11-11T05:30:00+07:00; bỏ trống thì lấy current_time",
      "format": "date-time"
    }
  },
  "required": [
    "type",
    "minutes"
  ]
}
```

<a id="tool-fitness-set_goal"></a>

### `fitness.set_goal`

- App: `fitness`; miền chính: D13; kind: `write`; split: train.
- Mô tả nguyên văn: Đặt mục tiêu bước/ngày
- Tham số: `steps`.
- Bắt buộc trực tiếp: `steps`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/38/tools/2](../../tools/train_tools_catalog.json#L3427); mã [train/apps/fitness.py:36](../../tools/train/apps/fitness.py#L36).

```json
{
  "type": "object",
  "properties": {
    "steps": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2",
      "exclusiveMinimum": 0
    }
  },
  "required": [
    "steps"
  ]
}
```

<a id="tool-learning-list_courses"></a>

### `learning.list_courses`

- App: `learning`; miền chính: D14; kind: `read`; split: train.
- Mô tả nguyên văn: Khoá học đang theo và khoá học có thể đăng ký (enrolled)
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `courses[]`
- Chứng cứ: [train /apps/39/tools/0](../../tools/train_tools_catalog.json#L3455); mã [train/apps/learning.py:11](../../tools/train/apps/learning.py#L11).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-learning-enroll"></a>

### `learning.enroll`

- App: `learning`; miền chính: D14; kind: `write`; split: train.
- Mô tả nguyên văn: Đăng ký theo học một khoá học
- Tham số: `course_id`.
- Bắt buộc trực tiếp: `course_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/39/tools/1](../../tools/train_tools_catalog.json#L3467); mã [train/apps/learning.py:15](../../tools/train/apps/learning.py#L15).

```json
{
  "type": "object",
  "properties": {
    "course_id": {
      "type": "string",
      "description": "ID khoá học, lấy từ learning.list_courses",
      "x-ref": "learning.courses"
    }
  },
  "required": [
    "course_id"
  ]
}
```

<a id="tool-learning-schedule_lesson"></a>

### `learning.schedule_lesson`

- App: `learning`; miền chính: D14; kind: `write`; split: train.
- Mô tả nguyên văn: Đặt buổi học
- Tham số: `course_id`, `time`.
- Bắt buộc trực tiếp: `course_id`, `time`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/39/tools/2](../../tools/train_tools_catalog.json#L3487); mã [train/apps/learning.py:25](../../tools/train/apps/learning.py#L25).

```json
{
  "type": "object",
  "properties": {
    "course_id": {
      "type": "string",
      "description": "ID khoá học, lấy từ learning.list_courses",
      "x-ref": "learning.courses"
    },
    "time": {
      "type": "string",
      "description": "ISO-8601 đầy đủ giây và offset múi giờ, ví dụ 2026-11-11T05:30:00+07:00",
      "format": "date-time"
    }
  },
  "required": [
    "course_id",
    "time"
  ]
}
```

<a id="tool-learning-log_progress"></a>

### `learning.log_progress`

- App: `learning`; miền chính: D14; kind: `write`; split: train.
- Mô tả nguyên văn: Ghi tiến độ
- Tham số: `course_id`, `minutes`.
- Bắt buộc trực tiếp: `course_id`, `minutes`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/39/tools/3](../../tools/train_tools_catalog.json#L3513); mã [train/apps/learning.py:32](../../tools/train/apps/learning.py#L32).

```json
{
  "type": "object",
  "properties": {
    "course_id": {
      "type": "string",
      "description": "ID khoá học, lấy từ learning.list_courses",
      "x-ref": "learning.courses"
    },
    "minutes": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2",
      "exclusiveMinimum": 0
    }
  },
  "required": [
    "course_id",
    "minutes"
  ]
}
```

<a id="tool-bike_rental-find_bikes"></a>

### `bike_rental.find_bikes`

- App: `bike_rental`; miền chính: D08; kind: `read`; split: train.
- Mô tả nguyên văn: Xe đạp tại các trạm, lọc theo trạm/khu vực
- Tham số: `near`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `near`.
- Returns nguyên văn: `bikes[]`
- Chứng cứ: [train /apps/40/tools/0](../../tools/train_tools_catalog.json#L3547); mã [train/apps/bike_rental.py:14](../../tools/train/apps/bike_rental.py#L14).

```json
{
  "type": "object",
  "properties": {
    "near": {
      "type": "string",
      "description": "Tên trạm hoặc khu vực, ví dụ Hồ Gươm",
      "x-match": "fuzzy"
    }
  },
  "required": []
}
```

<a id="tool-bike_rental-reserve"></a>

### `bike_rental.reserve`

- App: `bike_rental`; miền chính: D08; kind: `write`; split: train.
- Mô tả nguyên văn: Giữ/thuê một xe đạp còn trống
- Tham số: `bike_id`.
- Bắt buộc trực tiếp: `bike_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/40/tools/1](../../tools/train_tools_catalog.json#L3565); mã [train/apps/bike_rental.py:27](../../tools/train/apps/bike_rental.py#L27).

```json
{
  "type": "object",
  "properties": {
    "bike_id": {
      "type": "string",
      "description": "ID xe đạp, lấy từ bike_rental.find_bikes",
      "x-ref": "bike_rental.bikes"
    }
  },
  "required": [
    "bike_id"
  ]
}
```

<a id="tool-home_automation-list_rules"></a>

### `home_automation.list_rules`

- App: `home_automation`; miền chính: D01; kind: `read`; split: train.
- Mô tả nguyên văn: Danh sách quy tắc tự động
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `rules[]`
- Chứng cứ: [train /apps/41/tools/0](../../tools/train_tools_catalog.json#L3593); mã [train/apps/home_automation.py:11](../../tools/train/apps/home_automation.py#L11).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-home_automation-create_rule"></a>

### `home_automation.create_rule`

- App: `home_automation`; miền chính: D01; kind: `write`; split: train.
- Mô tả nguyên văn: Tạo quy tắc bật/tắt một thiết bị vào giờ cố định mỗi ngày
- Tham số: `device_id`, `action`, `time`, `title`.
- Bắt buộc trực tiếp: `device_id`, `action`, `time`.
- Không thuộc required (có thể chịu x-one-of): `title`.
- Returns nguyên văn: `rule`
- Chứng cứ: [train /apps/41/tools/1](../../tools/train_tools_catalog.json#L3605); mã [train/apps/home_automation.py:15](../../tools/train/apps/home_automation.py#L15).

```json
{
  "type": "object",
  "properties": {
    "device_id": {
      "type": "string",
      "description": "ID thiết bị, lấy từ smart_home.get_status",
      "x-ref": "smart_home.devices"
    },
    "action": {
      "type": "string",
      "enum": [
        "on",
        "off"
      ]
    },
    "time": {
      "type": "string",
      "description": "Giờ chạy mỗi ngày dạng HH:MM, ví dụ 19:00",
      "format": "time"
    },
    "title": {
      "type": "string",
      "x-match": "fuzzy"
    }
  },
  "required": [
    "device_id",
    "action",
    "time"
  ]
}
```

<a id="tool-home_automation-delete_rule"></a>

### `home_automation.delete_rule`

- App: `home_automation`; miền chính: D01; kind: `write`; split: train.
- Mô tả nguyên văn: Xoá quy tắc
- Tham số: `rule_id`.
- Bắt buộc trực tiếp: `rule_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/41/tools/2](../../tools/train_tools_catalog.json#L3643); mã [train/apps/home_automation.py:26](../../tools/train/apps/home_automation.py#L26).

```json
{
  "type": "object",
  "properties": {
    "rule_id": {
      "type": "string",
      "description": "ID quy tắc, lấy từ home_automation.list_rules",
      "x-ref": "home_automation.rules"
    }
  },
  "required": [
    "rule_id"
  ]
}
```

<a id="tool-household_chores-list_chores"></a>

### `household_chores.list_chores`

- App: `household_chores`; miền chính: D01; kind: `read`; split: train.
- Mô tả nguyên văn: Danh sách việc nhà, người phụ trách và các thành viên (members)
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `chores[], members[]`
- Chứng cứ: [train /apps/42/tools/0](../../tools/train_tools_catalog.json#L3671); mã [train/apps/household_chores.py:12](../../tools/train/apps/household_chores.py#L12).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-household_chores-assign"></a>

### `household_chores.assign`

- App: `household_chores`; miền chính: D01; kind: `write`; split: train.
- Mô tả nguyên văn: Giao một việc nhà cho một thành viên
- Tham số: `chore_id`, `assignee`.
- Bắt buộc trực tiếp: `assignee`, `chore_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/42/tools/1](../../tools/train_tools_catalog.json#L3683); mã [train/apps/household_chores.py:16](../../tools/train/apps/household_chores.py#L16).

```json
{
  "type": "object",
  "properties": {
    "chore_id": {
      "type": "string",
      "description": "ID việc nhà, lấy từ household_chores.list_chores",
      "x-ref": "household_chores.chores"
    },
    "assignee": {
      "type": "string",
      "description": "Tên thành viên, đúng một tên trong members của household_chores.list_chores"
    }
  },
  "required": [
    "assignee",
    "chore_id"
  ]
}
```

<a id="tool-library-search"></a>

### `library.search`

- App: `library`; miền chính: D14; kind: `read`; split: train.
- Mô tả nguyên văn: Tìm sách theo tên sách hoặc tác giả; không có query thì trả mọi sách
- Tham số: `query`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `query`.
- Returns nguyên văn: `books[]`
- Chứng cứ: [train /apps/43/tools/0](../../tools/train_tools_catalog.json#L3716); mã [train/apps/library.py:11](../../tools/train/apps/library.py#L11).

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Tên sách hoặc tác giả"
    }
  },
  "required": []
}
```

<a id="tool-library-reserve"></a>

### `library.reserve`

- App: `library`; miền chính: D14; kind: `write`; split: train.
- Mô tả nguyên văn: Đặt giữ một cuốn sách (sách đang có thì giữ tại quầy, đang cho mượn thì xếp hàng chờ)
- Tham số: `book_id`.
- Bắt buộc trực tiếp: `book_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/43/tools/1](../../tools/train_tools_catalog.json#L3733); mã [train/apps/library.py:15](../../tools/train/apps/library.py#L15).

```json
{
  "type": "object",
  "properties": {
    "book_id": {
      "type": "string",
      "description": "ID sách, lấy từ library.search",
      "x-ref": "library.books"
    }
  },
  "required": [
    "book_id"
  ]
}
```

<a id="tool-subscriptions-list"></a>

### `subscriptions.list`

- App: `subscriptions`; miền chính: D06; kind: `read`; split: train.
- Mô tả nguyên văn: Danh sách gói đăng ký: tên, giá, ngày gia hạn tiếp theo, trạng thái
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `subscriptions[]`
- Chứng cứ: [train /apps/44/tools/0](../../tools/train_tools_catalog.json#L3761); mã [train/apps/subscriptions.py:11](../../tools/train/apps/subscriptions.py#L11).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-subscriptions-cancel"></a>

### `subscriptions.cancel`

- App: `subscriptions`; miền chính: D06; kind: `write`; split: train.
- Mô tả nguyên văn: Huỷ một gói đăng ký
- Tham số: `subscription_id`.
- Bắt buộc trực tiếp: `subscription_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/44/tools/1](../../tools/train_tools_catalog.json#L3773); mã [train/apps/subscriptions.py:15](../../tools/train/apps/subscriptions.py#L15).

```json
{
  "type": "object",
  "properties": {
    "subscription_id": {
      "type": "string",
      "description": "ID gói đăng ký, lấy từ subscriptions.list",
      "x-ref": "subscriptions.subscriptions"
    }
  },
  "required": [
    "subscription_id"
  ]
}
```

<a id="tool-sys-ask_missing_info"></a>

### `sys.ask_missing_info`

- App: `sys`; miền chính: D17; kind: `meta`; split: train, public_test.
- Mô tả nguyên văn: Báo các tham số bắt buộc còn thiếu của một tool
- Tham số: `tool_name`, `params`.
- Bắt buộc trực tiếp: `tool_name`, `params`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [train /apps/45/tools/0](../../tools/train_tools_catalog.json#L3801); [public_test /apps/35/tools/0](../../tools/public_test_tools_catalog.json#L3195); mã [train/apps/sys.py:11](../../tools/train/apps/sys.py#L11); [test/apps/sys.py:11](../../tools/test/apps/sys.py#L11).

```json
{
  "type": "object",
  "properties": {
    "tool_name": {
      "type": "string",
      "description": "Tên tool bị thiếu tham số, dạng app_name.tool_name, ví dụ sms.send"
    },
    "params": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Tên các tham số bắt buộc còn thiếu, đúng tên trong schema, ví dụ [\"contact_id\"]"
    }
  },
  "required": [
    "tool_name",
    "params"
  ]
}
```

<a id="tool-stocks-get_quote"></a>

### `stocks.get_quote`

- App: `stocks`; miền chính: D16; kind: `read`; split: public_test.
- Mô tả nguyên văn: Giá cổ phiếu/chỉ số
- Tham số: `symbol`.
- Bắt buộc trực tiếp: `symbol`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `quote`
- Chứng cứ: [public_test /apps/14/tools/0](../../tools/public_test_tools_catalog.json#L1473); mã [test/apps/stocks.py:27](../../tools/test/apps/stocks.py#L27).

```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string"
    }
  },
  "required": [
    "symbol"
  ]
}
```

<a id="tool-stocks-get_portfolio"></a>

### `stocks.get_portfolio`

- App: `stocks`; miền chính: D16; kind: `read`; split: public_test.
- Mô tả nguyên văn: Danh mục đang nắm giữ
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `holdings[]`
- Chứng cứ: [public_test /apps/14/tools/1](../../tools/public_test_tools_catalog.json#L1491); mã [test/apps/stocks.py:34](../../tools/test/apps/stocks.py#L34).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-stocks-place_order"></a>

### `stocks.place_order`

- App: `stocks`; miền chính: D16; kind: `write`; split: public_test.
- Mô tả nguyên văn: Đặt lệnh mua/bán
- Tham số: `symbol`, `side`, `quantity`, `price`.
- Bắt buộc trực tiếp: `symbol`, `side`, `quantity`.
- Không thuộc required (có thể chịu x-one-of): `price`.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [public_test /apps/14/tools/2](../../tools/public_test_tools_catalog.json#L1503); mã [test/apps/stocks.py:40](../../tools/test/apps/stocks.py#L40).

```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string"
    },
    "side": {
      "type": "string",
      "enum": [
        "buy",
        "sell"
      ]
    },
    "quantity": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2",
      "exclusiveMinimum": 0
    },
    "price": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm, phẩy hay đơn vị, ví dụ 1200000",
      "exclusiveMinimum": 0
    }
  },
  "required": [
    "symbol",
    "side",
    "quantity"
  ]
}
```

<a id="tool-stocks-set_price_alert"></a>

### `stocks.set_price_alert`

- App: `stocks`; miền chính: D16; kind: `write`; split: public_test.
- Mô tả nguyên văn: Cảnh báo khi giá chạm ngưỡng
- Tham số: `symbol`, `price`, `direction`.
- Bắt buộc trực tiếp: `symbol`, `price`, `direction`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [public_test /apps/14/tools/3](../../tools/public_test_tools_catalog.json#L1540); mã [test/apps/stocks.py:55](../../tools/test/apps/stocks.py#L55).

```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string"
    },
    "price": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm, phẩy hay đơn vị, ví dụ 1200000",
      "exclusiveMinimum": 0
    },
    "direction": {
      "type": "string",
      "enum": [
        "above",
        "below"
      ]
    }
  },
  "required": [
    "symbol",
    "price",
    "direction"
  ]
}
```

<a id="tool-translator-translate"></a>

### `translator.translate`

- App: `translator`; miền chính: D15; kind: `read`; split: public_test.
- Mô tả nguyên văn: Dịch văn bản
- Tham số: `text`, `to_lang`, `from_lang`.
- Bắt buộc trực tiếp: `text`, `to_lang`.
- Không thuộc required (có thể chịu x-one-of): `from_lang`.
- Returns nguyên văn: `translation`
- Chứng cứ: [public_test /apps/18/tools/0](../../tools/public_test_tools_catalog.json#L1687); mã [test/apps/translator.py:18](../../tools/test/apps/translator.py#L18).

```json
{
  "type": "object",
  "properties": {
    "text": {
      "type": "string",
      "x-match": "fuzzy",
      "description": "Câu/đoạn cần dịch, giữ nguyên lời người dùng"
    },
    "to_lang": {
      "type": "string",
      "description": "Mã ngôn ngữ đích ISO 639-1, ví dụ en (tiếng Anh), vi, ja, ko, zh, fr"
    },
    "from_lang": {
      "type": "string",
      "description": "Mã ngôn ngữ nguồn ISO 639-1, ví dụ vi; bỏ trống để tự nhận diện"
    }
  },
  "required": [
    "text",
    "to_lang"
  ]
}
```

<a id="tool-grocery-search"></a>

### `grocery.search`

- App: `grocery`; miền chính: D11; kind: `read`; split: public_test.
- Mô tả nguyên văn: Tìm sản phẩm đi chợ theo tên hoặc loại (sữa, trứng, rau...)
- Tham số: `query`.
- Bắt buộc trực tiếp: `query`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `products[]`
- Chứng cứ: [public_test /apps/21/tools/0](../../tools/public_test_tools_catalog.json#L1948); mã [test/apps/grocery.py:13](../../tools/test/apps/grocery.py#L13).

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Tên hoặc loại sản phẩm, ví dụ trứng gà"
    }
  },
  "required": [
    "query"
  ]
}
```

<a id="tool-grocery-add_to_cart"></a>

### `grocery.add_to_cart`

- App: `grocery`; miền chính: D11; kind: `write`; split: public_test.
- Mô tả nguyên văn: Thêm vào giỏ
- Tham số: `product_id`, `quantity`.
- Bắt buộc trực tiếp: `product_id`, `quantity`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `cart[]`
- Chứng cứ: [public_test /apps/21/tools/1](../../tools/public_test_tools_catalog.json#L1967); mã [test/apps/grocery.py:17](../../tools/test/apps/grocery.py#L17).

```json
{
  "type": "object",
  "properties": {
    "product_id": {
      "type": "string",
      "description": "ID sản phẩm, lấy từ grocery.search",
      "x-ref": "grocery.products"
    },
    "quantity": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2",
      "exclusiveMinimum": 0
    }
  },
  "required": [
    "product_id",
    "quantity"
  ]
}
```

<a id="tool-grocery-checkout"></a>

### `grocery.checkout`

- App: `grocery`; miền chính: D11; kind: `write`; split: public_test.
- Mô tả nguyên văn: Đặt hàng toàn bộ giỏ hiện tại (giỏ được làm trống)
- Tham số: `address`, `delivery_time`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `address`, `delivery_time`.
- Returns nguyên văn: `order`
- Chứng cứ: [public_test /apps/21/tools/2](../../tools/public_test_tools_catalog.json#L1993); mã [test/apps/grocery.py:21](../../tools/test/apps/grocery.py#L21).

```json
{
  "type": "object",
  "properties": {
    "address": {
      "type": "string",
      "x-match": "fuzzy"
    },
    "delivery_time": {
      "type": "string",
      "description": "ISO-8601 đầy đủ giây và offset múi giờ, ví dụ 2026-11-11T05:30:00+07:00"
    }
  },
  "required": []
}
```

<a id="tool-recipes-search"></a>

### `recipes.search`

- App: `recipes`; miền chính: D10; kind: `read`; split: public_test.
- Mô tả nguyên văn: Tìm công thức theo tên món hoặc nguyên liệu; servings quy đổi lượng nguyên liệu theo số người ăn
- Tham số: `query`, `servings`.
- Bắt buộc trực tiếp: `query`.
- Không thuộc required (có thể chịu x-one-of): `servings`.
- Returns nguyên văn: `recipes[]`
- Chứng cứ: [public_test /apps/22/tools/0](../../tools/public_test_tools_catalog.json#L2022); mã [test/apps/recipes.py:25](../../tools/test/apps/recipes.py#L25).

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Tên món hoặc nguyên liệu, ví dụ súp bí đỏ"
    },
    "servings": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2"
    }
  },
  "required": [
    "query"
  ]
}
```

<a id="tool-recipes-get"></a>

### `recipes.get`

- App: `recipes`; miền chính: D10; kind: `read`; split: public_test.
- Mô tả nguyên văn: Chi tiết công thức: nguyên liệu và các bước
- Tham số: `recipe_id`.
- Bắt buộc trực tiếp: `recipe_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `recipe`
- Chứng cứ: [public_test /apps/22/tools/1](../../tools/public_test_tools_catalog.json#L2045); mã [test/apps/recipes.py:38](../../tools/test/apps/recipes.py#L38).

```json
{
  "type": "object",
  "properties": {
    "recipe_id": {
      "type": "string",
      "description": "ID công thức, lấy từ recipes.search",
      "x-ref": "recipes.recipes"
    }
  },
  "required": [
    "recipe_id"
  ]
}
```

<a id="tool-recipes-save"></a>

### `recipes.save`

- App: `recipes`; miền chính: D10; kind: `write`; split: public_test.
- Mô tả nguyên văn: Lưu công thức vào mục đã lưu
- Tham số: `recipe_id`.
- Bắt buộc trực tiếp: `recipe_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `saved`
- Chứng cứ: [public_test /apps/22/tools/2](../../tools/public_test_tools_catalog.json#L2065); mã [test/apps/recipes.py:45](../../tools/test/apps/recipes.py#L45).

```json
{
  "type": "object",
  "properties": {
    "recipe_id": {
      "type": "string",
      "description": "ID công thức, lấy từ recipes.search",
      "x-ref": "recipes.recipes"
    }
  },
  "required": [
    "recipe_id"
  ]
}
```

<a id="tool-public_transit-find_routes"></a>

### `public_transit.find_routes`

- App: `public_transit`; miền chính: D08; kind: `read`; split: public_test.
- Mô tả nguyên văn: Tìm tuyến giữa hai điểm
- Tham số: `origin`, `destination`.
- Bắt buộc trực tiếp: `origin`, `destination`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `routes[]`
- Chứng cứ: [public_test /apps/24/tools/0](../../tools/public_test_tools_catalog.json#L2217); mã [test/apps/public_transit.py:33](../../tools/test/apps/public_transit.py#L33).

```json
{
  "type": "object",
  "properties": {
    "origin": {
      "type": "string",
      "description": "Điểm đi: tên trạm, địa điểm hoặc địa chỉ; 'nhà' → home_address của profile",
      "x-match": "fuzzy"
    },
    "destination": {
      "type": "string",
      "description": "Điểm đến: tên trạm, địa điểm hoặc địa chỉ",
      "x-match": "fuzzy"
    }
  },
  "required": [
    "origin",
    "destination"
  ]
}
```

<a id="tool-public_transit-next_departures"></a>

### `public_transit.next_departures`

- App: `public_transit`; miền chính: D08; kind: `read`; split: public_test.
- Mô tả nguyên văn: Chuyến kế tiếp tại trạm
- Tham số: `stop`, `route`.
- Bắt buộc trực tiếp: `stop`.
- Không thuộc required (có thể chịu x-one-of): `route`.
- Returns nguyên văn: `departures[]`
- Chứng cứ: [public_test /apps/24/tools/1](../../tools/public_test_tools_catalog.json#L2243); mã [test/apps/public_transit.py:52](../../tools/test/apps/public_transit.py#L52).

```json
{
  "type": "object",
  "properties": {
    "stop": {
      "type": "string",
      "description": "Tên trạm/ga, ví dụ Cầu Giấy"
    },
    "route": {
      "type": "string",
      "description": "Tên hoặc số tuyến, ví dụ 32"
    }
  },
  "required": [
    "stop"
  ]
}
```

<a id="tool-public_transit-topup_card"></a>

### `public_transit.topup_card`

- App: `public_transit`; miền chính: D08; kind: `write`; split: public_test.
- Mô tả nguyên văn: Nạp thẻ đi xe
- Tham số: `amount`.
- Bắt buộc trực tiếp: `amount`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [public_test /apps/24/tools/2](../../tools/public_test_tools_catalog.json#L2266); mã [test/apps/public_transit.py:65](../../tools/test/apps/public_transit.py#L65).

```json
{
  "type": "object",
  "properties": {
    "amount": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm, phẩy hay đơn vị, ví dụ 1200000",
      "exclusiveMinimum": 0
    }
  },
  "required": [
    "amount"
  ]
}
```

<a id="tool-parking-find"></a>

### `parking.find`

- App: `parking`; miền chính: D08; kind: `read`; split: public_test.
- Mô tả nguyên văn: Bãi đỗ gần một địa điểm
- Tham số: `near`.
- Bắt buộc trực tiếp: `near`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `lots[]`
- Chứng cứ: [public_test /apps/25/tools/0](../../tools/public_test_tools_catalog.json#L2294); mã [test/apps/parking.py:15](../../tools/test/apps/parking.py#L15).

```json
{
  "type": "object",
  "properties": {
    "near": {
      "type": "string",
      "description": "Địa điểm hoặc khu vực, ví dụ Hồ Gươm",
      "x-match": "fuzzy"
    }
  },
  "required": [
    "near"
  ]
}
```

<a id="tool-parking-list_sessions"></a>

### `parking.list_sessions`

- App: `parking`; miền chính: D08; kind: `read`; split: public_test.
- Mô tả nguyên văn: Các phiên đỗ/chỗ đã đặt
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `sessions[]`
- Chứng cứ: [public_test /apps/25/tools/1](../../tools/public_test_tools_catalog.json#L2314); mã [test/apps/parking.py:22](../../tools/test/apps/parking.py#L22).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-parking-reserve"></a>

### `parking.reserve`

- App: `parking`; miền chính: D08; kind: `write`; split: public_test.
- Mô tả nguyên văn: Đặt chỗ
- Tham số: `lot_id`, `from_time`, `hours`.
- Bắt buộc trực tiếp: `lot_id`, `from_time`, `hours`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [public_test /apps/25/tools/2](../../tools/public_test_tools_catalog.json#L2326); mã [test/apps/parking.py:27](../../tools/test/apps/parking.py#L27).

```json
{
  "type": "object",
  "properties": {
    "lot_id": {
      "type": "string",
      "description": "ID bãi đỗ, lấy từ parking.find",
      "x-ref": "parking.lots"
    },
    "from_time": {
      "type": "string",
      "description": "ISO-8601 đầy đủ giây và offset múi giờ, ví dụ 2026-11-11T05:30:00+07:00",
      "format": "date-time"
    },
    "hours": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2",
      "exclusiveMinimum": 0
    }
  },
  "required": [
    "lot_id",
    "from_time",
    "hours"
  ]
}
```

<a id="tool-parking-end_session"></a>

### `parking.end_session`

- App: `parking`; miền chính: D08; kind: `write`; split: public_test.
- Mô tả nguyên văn: Kết thúc phiên đỗ
- Tham số: `session_id`.
- Bắt buộc trực tiếp: `session_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [public_test /apps/25/tools/3](../../tools/public_test_tools_catalog.json#L2358); mã [test/apps/parking.py:46](../../tools/test/apps/parking.py#L46).

```json
{
  "type": "object",
  "properties": {
    "session_id": {
      "type": "string",
      "description": "ID phiên đỗ, lấy từ parking.list_sessions",
      "x-ref": "parking.sessions"
    }
  },
  "required": [
    "session_id"
  ]
}
```

<a id="tool-train_bus_tickets-search"></a>

### `train_bus_tickets.search`

- App: `train_bus_tickets`; miền chính: D09; kind: `read`; split: public_test.
- Mô tả nguyên văn: Tìm chuyến
- Tham số: `origin`, `destination`, `date`, `type`.
- Bắt buộc trực tiếp: `origin`, `destination`, `date`.
- Không thuộc required (có thể chịu x-one-of): `type`.
- Returns nguyên văn: `trips[]`
- Chứng cứ: [public_test /apps/27/tools/0](../../tools/public_test_tools_catalog.json#L2511); mã [test/apps/train_bus_tickets.py:14](../../tools/test/apps/train_bus_tickets.py#L14).

```json
{
  "type": "object",
  "properties": {
    "origin": {
      "type": "string",
      "description": "Thành phố đi, ví dụ Hà Nội"
    },
    "destination": {
      "type": "string",
      "description": "Thành phố đến, ví dụ Hải Phòng"
    },
    "date": {
      "type": "string",
      "description": "YYYY-MM-DD, ví dụ 2026-11-29"
    },
    "type": {
      "type": "string",
      "enum": [
        "train",
        "bus"
      ]
    }
  },
  "required": [
    "origin",
    "destination",
    "date"
  ]
}
```

<a id="tool-train_bus_tickets-book"></a>

### `train_bus_tickets.book`

- App: `train_bus_tickets`; miền chính: D09; kind: `write`; split: public_test.
- Mô tả nguyên văn: Đặt vé
- Tham số: `trip_id`, `seats`.
- Bắt buộc trực tiếp: `trip_id`, `seats`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [public_test /apps/27/tools/1](../../tools/public_test_tools_catalog.json#L2547); mã [test/apps/train_bus_tickets.py:25](../../tools/test/apps/train_bus_tickets.py#L25).

```json
{
  "type": "object",
  "properties": {
    "trip_id": {
      "type": "string",
      "description": "ID chuyến, lấy từ train_bus_tickets.search",
      "x-ref": "train_bus_tickets.trips"
    },
    "seats": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2",
      "exclusiveMinimum": 0
    }
  },
  "required": [
    "trip_id",
    "seats"
  ]
}
```

<a id="tool-train_bus_tickets-my_bookings"></a>

### `train_bus_tickets.my_bookings`

- App: `train_bus_tickets`; miền chính: D09; kind: `read`; split: public_test.
- Mô tả nguyên văn: Vé đã đặt
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `bookings[]`
- Chứng cứ: [public_test /apps/27/tools/2](../../tools/public_test_tools_catalog.json#L2573); mã [test/apps/train_bus_tickets.py:21](../../tools/test/apps/train_bus_tickets.py#L21).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-train_bus_tickets-cancel"></a>

### `train_bus_tickets.cancel`

- App: `train_bus_tickets`; miền chính: D09; kind: `write`; split: public_test.
- Mô tả nguyên văn: Huỷ vé
- Tham số: `booking_id`.
- Bắt buộc trực tiếp: `booking_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [public_test /apps/27/tools/3](../../tools/public_test_tools_catalog.json#L2585); mã [test/apps/train_bus_tickets.py:37](../../tools/test/apps/train_bus_tickets.py#L37).

```json
{
  "type": "object",
  "properties": {
    "booking_id": {
      "type": "string",
      "description": "ID vé đã đặt, lấy từ train_bus_tickets.my_bookings",
      "x-ref": "train_bus_tickets.bookings"
    }
  },
  "required": [
    "booking_id"
  ]
}
```

<a id="tool-ecommerce-search"></a>

### `ecommerce.search`

- App: `ecommerce`; miền chính: D11; kind: `read`; split: public_test.
- Mô tả nguyên văn: Tìm sản phẩm trên sàn
- Tham số: `query`, `max_price`.
- Bắt buộc trực tiếp: `query`.
- Không thuộc required (có thể chịu x-one-of): `max_price`.
- Returns nguyên văn: `products[]`
- Chứng cứ: [public_test /apps/28/tools/0](../../tools/public_test_tools_catalog.json#L2613); mã [test/apps/ecommerce.py:16](../../tools/test/apps/ecommerce.py#L16).

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Tên hoặc loại sản phẩm, ví dụ tai nghe"
    },
    "max_price": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm, phẩy hay đơn vị, ví dụ 1200000"
    }
  },
  "required": [
    "query"
  ]
}
```

<a id="tool-ecommerce-order_status"></a>

### `ecommerce.order_status`

- App: `ecommerce`; miền chính: D11; kind: `read`; split: public_test.
- Mô tả nguyên văn: Trạng thái đơn hàng (không truyền order_id: mọi đơn gần đây)
- Tham số: `order_id`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `order_id`.
- Returns nguyên văn: `orders[]`
- Chứng cứ: [public_test /apps/28/tools/1](../../tools/public_test_tools_catalog.json#L2636); mã [test/apps/ecommerce.py:23](../../tools/test/apps/ecommerce.py#L23).

```json
{
  "type": "object",
  "properties": {
    "order_id": {
      "type": "string",
      "description": "ID đơn hàng, lấy từ ecommerce.order_status",
      "x-ref": "ecommerce.orders"
    }
  },
  "required": []
}
```

<a id="tool-ecommerce-add_to_cart"></a>

### `ecommerce.add_to_cart`

- App: `ecommerce`; miền chính: D11; kind: `write`; split: public_test.
- Mô tả nguyên văn: Thêm vào giỏ
- Tham số: `product_id`, `quantity`.
- Bắt buộc trực tiếp: `product_id`, `quantity`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `cart[]`
- Chứng cứ: [public_test /apps/28/tools/2](../../tools/public_test_tools_catalog.json#L2654); mã [test/apps/ecommerce.py:32](../../tools/test/apps/ecommerce.py#L32).

```json
{
  "type": "object",
  "properties": {
    "product_id": {
      "type": "string",
      "description": "ID sản phẩm, lấy từ ecommerce.search",
      "x-ref": "ecommerce.products"
    },
    "quantity": {
      "type": "integer",
      "description": "Số nguyên, không dấu chấm hay phẩy, ví dụ 2",
      "exclusiveMinimum": 0
    }
  },
  "required": [
    "product_id",
    "quantity"
  ]
}
```

<a id="tool-ecommerce-checkout"></a>

### `ecommerce.checkout`

- App: `ecommerce`; miền chính: D11; kind: `write`; split: public_test.
- Mô tả nguyên văn: Đặt hàng toàn bộ giỏ (giỏ được làm trống); payment mặc định cod
- Tham số: `address`, `payment`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `address`, `payment`.
- Returns nguyên văn: `order`
- Chứng cứ: [public_test /apps/28/tools/3](../../tools/public_test_tools_catalog.json#L2680); mã [test/apps/ecommerce.py:36](../../tools/test/apps/ecommerce.py#L36).

```json
{
  "type": "object",
  "properties": {
    "address": {
      "type": "string",
      "x-match": "fuzzy"
    },
    "payment": {
      "type": "string",
      "enum": [
        "cod",
        "ewallet",
        "bank"
      ]
    }
  },
  "required": []
}
```

<a id="tool-ecommerce-cancel_order"></a>

### `ecommerce.cancel_order`

- App: `ecommerce`; miền chính: D11; kind: `write`; split: public_test.
- Mô tả nguyên văn: Huỷ đơn chưa giao
- Tham số: `order_id`.
- Bắt buộc trực tiếp: `order_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [public_test /apps/28/tools/4](../../tools/public_test_tools_catalog.json#L2705); mã [test/apps/ecommerce.py:40](../../tools/test/apps/ecommerce.py#L40).

```json
{
  "type": "object",
  "properties": {
    "order_id": {
      "type": "string",
      "description": "ID đơn hàng, lấy từ ecommerce.order_status",
      "x-ref": "ecommerce.orders"
    }
  },
  "required": [
    "order_id"
  ]
}
```

<a id="tool-ecommerce-request_return"></a>

### `ecommerce.request_return`

- App: `ecommerce`; miền chính: D11; kind: `write`; split: public_test.
- Mô tả nguyên văn: Tạo yêu cầu trả hàng/hoàn tiền cho đơn đã giao
- Tham số: `order_id`, `reason`.
- Bắt buộc trực tiếp: `order_id`, `reason`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `return`
- Chứng cứ: [public_test /apps/28/tools/5](../../tools/public_test_tools_catalog.json#L2725); mã [test/apps/ecommerce.py:50](../../tools/test/apps/ecommerce.py#L50).

```json
{
  "type": "object",
  "properties": {
    "order_id": {
      "type": "string",
      "description": "ID đơn hàng, lấy từ ecommerce.order_status",
      "x-ref": "ecommerce.orders"
    },
    "reason": {
      "type": "string",
      "enum": [
        "wrong_item",
        "damaged",
        "changed_mind",
        "other"
      ],
      "description": "wrong_item: giao sai hàng; damaged: hàng hỏng/vỡ; changed_mind: đổi ý, không cần nữa; other: lý do khác"
    }
  },
  "required": [
    "order_id",
    "reason"
  ]
}
```

<a id="tool-event_tickets-search"></a>

### `event_tickets.search`

- App: `event_tickets`; miền chính: D12; kind: `read`; split: public_test.
- Mô tả nguyên văn: Tìm sự kiện theo tên, loại hoặc địa điểm; bỏ trống query để liệt kê tất cả
- Tham số: `query`.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): `query`.
- Returns nguyên văn: `events[]`
- Chứng cứ: [public_test /apps/32/tools/0](../../tools/public_test_tools_catalog.json#L3052); mã [test/apps/event_tickets.py:13](../../tools/test/apps/event_tickets.py#L13).

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Tên sự kiện, loại (ca nhạc, kịch...) hoặc địa điểm"
    }
  },
  "required": []
}
```

<a id="tool-event_tickets-book"></a>

### `event_tickets.book`

- App: `event_tickets`; miền chính: D12; kind: `write`; split: public_test.
- Mô tả nguyên văn: Đặt vé sự kiện
- Tham số: `event_id`, `quantity`.
- Bắt buộc trực tiếp: `event_id`, `quantity`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [public_test /apps/32/tools/1](../../tools/public_test_tools_catalog.json#L3069); mã [test/apps/event_tickets.py:17](../../tools/test/apps/event_tickets.py#L17).

```json
{
  "type": "object",
  "properties": {
    "event_id": {
      "type": "string",
      "description": "ID sự kiện, lấy từ event_tickets.search",
      "x-ref": "event_tickets.events"
    },
    "quantity": {
      "type": "integer",
      "description": "Số vé. Số nguyên, không dấu chấm hay phẩy, ví dụ 2",
      "exclusiveMinimum": 0
    }
  },
  "required": [
    "event_id",
    "quantity"
  ]
}
```

<a id="tool-habit_tracker-list_habits"></a>

### `habit_tracker.list_habits`

- App: `habit_tracker`; miền chính: D13; kind: `read`; split: public_test.
- Mô tả nguyên văn: Danh sách thói quen và chuỗi ngày liên tiếp (streak)
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `habits[]`
- Chứng cứ: [public_test /apps/33/tools/0](../../tools/public_test_tools_catalog.json#L3103); mã [test/apps/habit_tracker.py:13](../../tools/test/apps/habit_tracker.py#L13).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-habit_tracker-log"></a>

### `habit_tracker.log`

- App: `habit_tracker`; miền chính: D13; kind: `write`; split: public_test.
- Mô tả nguyên văn: Đánh dấu đã thực hiện thói quen trong một ngày
- Tham số: `habit_id`, `date`.
- Bắt buộc trực tiếp: `date`, `habit_id`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: Chuỗi rỗng — chưa mô tả.
- Chứng cứ: [public_test /apps/33/tools/1](../../tools/public_test_tools_catalog.json#L3115); mã [test/apps/habit_tracker.py:17](../../tools/test/apps/habit_tracker.py#L17).

```json
{
  "type": "object",
  "properties": {
    "habit_id": {
      "type": "string",
      "description": "ID thói quen, lấy từ habit_tracker.list_habits",
      "x-ref": "habit_tracker.habits"
    },
    "date": {
      "type": "string",
      "description": "YYYY-MM-DD, ví dụ 2026-11-29",
      "format": "date"
    }
  },
  "required": [
    "date",
    "habit_id"
  ]
}
```

<a id="tool-pantry-list_items"></a>

### `pantry.list_items`

- App: `pantry`; miền chính: D10; kind: `read`; split: public_test.
- Mô tả nguyên văn: Danh sách đồ trong tủ bếp và số lượng còn
- Tham số: Không có.
- Bắt buộc trực tiếp: Không có.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `items[]`
- Chứng cứ: [public_test /apps/34/tools/0](../../tools/public_test_tools_catalog.json#L3149); mã [test/apps/pantry.py:11](../../tools/test/apps/pantry.py#L11).

```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

<a id="tool-pantry-consume"></a>

### `pantry.consume`

- App: `pantry`; miền chính: D10; kind: `write`; split: public_test.
- Mô tả nguyên văn: Ghi nhận đã dùng một lượng của một món (trừ vào số còn)
- Tham số: `item_id`, `quantity`.
- Bắt buộc trực tiếp: `item_id`, `quantity`.
- Không thuộc required (có thể chịu x-one-of): Không có.
- Returns nguyên văn: `item`
- Chứng cứ: [public_test /apps/34/tools/1](../../tools/public_test_tools_catalog.json#L3161); mã [test/apps/pantry.py:15](../../tools/test/apps/pantry.py#L15).

```json
{
  "type": "object",
  "properties": {
    "item_id": {
      "type": "string",
      "description": "ID món, lấy từ pantry.list_items",
      "x-ref": "pantry.items"
    },
    "quantity": {
      "type": "integer",
      "description": "Số lượng đã dùng theo đơn vị của món, số nguyên, không dấu chấm hay phẩy, ví dụ 2",
      "exclusiveMinimum": 0
    }
  },
  "required": [
    "item_id",
    "quantity"
  ]
}
```
