# 개발 문서

## 구조

```
driver/
  config.yml                       # packageKey pv28cw-tuya-lan, 권한 lan + discovery
  profiles/pv28cw-air-monitor.yml  # capability 11개, 기기 설정
  src/init.lua                     # 수명주기, 폴링, refresh, 설정 쓰기 대기열
  src/dpmap.lua                    # DP → capability, 공기질 등급, 설정 → DP
  src/discovery.lua                # 주변 기기 검색·새 기기 추가 시 빈 기기 생성, 연결 설정 확인
  src/tuya/client.lua              # 연결 → 세션 키 협상 → 조회/제어 → 종료
  src/tuya/protocol.lua            # Tuya 3.5 프레임(6699), 세션 키
  src/tuya/aes.lua gcm.lua sha256.lua
pv28_diag.py                       # 센서 진단 도구 (tinytuya)
tests/                             # Lua 5.3(lupa)로 드라이버 코드를 PC에서 실행
```

## 동작 방식

- 30초(설정 가능)마다 TCP 6668로 접속해 세션 키를 협상하고 `DP_QUERY_NEW` 한 번 보낸 뒤 연결을 끊습니다.
- Edge 런타임에는 쓸 만한 암호 API가 없어서 AES-128, GCM, SHA-256/HMAC을 순수 Lua로 구현했습니다.
- 허브는 Tuya 탐색 포트(UDP 6666/6667/7000)를 bind할 수 없습니다. 그래서 빈 기기를 만들고 IP와 Local Key는 사용자가 넣습니다. 주변 기기 검색은 앱에서 다른 기기를 찾을 때도 허브의 모든 드라이버에 불리므로, 이 드라이버의 기기가 하나도 없을 때만 만듭니다. 3.5 요청에는 Device ID가 들어가지 않아서 받지 않습니다.
- 여러 대를 쓸 수 있게 기기 설정에 `addDevice` 스위치를 둡니다. 설정 화면에는 버튼이 없어서, 꺼짐 → 켜짐일 때 `infoChanged`에서 `driver:try_create_device`로 빈 기기를 만듭니다(MIoT 드라이버의 `createDev`와 같은 방식). 끌 때와 이전 값이 없을 때(기기 생성, 드라이버 업데이트로 설정 추가)는 만들지 않습니다.
- 빈 기기는 설정 전 기기가 이미 있으면 만들지 않습니다. `try_create_device`는 비동기라 만든 기기가 `get_devices`에 나오거나 60초가 지날 때까지는 다시 요청해도 만들지 않습니다(스위치를 껐다가 바로 다시 켜는 경우). 이름은 "공기질 센서", "공기질 센서 2", ... 중 안 쓰는 것을 붙입니다.
- IP와 Local Key가 없거나 형식이 틀리면 조회하지 않고, 어느 항목이 문제인지 로그에 남깁니다.
- 연속 3번 조회에 실패하면 오프라인으로 표시합니다. 응답에 측정 DP가 하나도 없어도 실패로 셉니다. 4번째부터는 실패 로그를 debug로 남깁니다.
- 값이 바뀐 이벤트만 보냅니다 (`device:get_latest_state`와 비교).
- 기기 설정을 바꾸면 쓸 DP를 대기열(영구 필드)에 넣고 바로 조회합니다. 같은 세션에서 CONTROL_NEW → DP_QUERY_NEW 순서로 보내고, 쓰기가 성공했거나 쓰기는 실패해도 조회가 되면(기기가 받지 않음) 대기열을 비웁니다. 연결이 안 되면 남겨 두고 다음 조회 때 다시 보냅니다.
- 센서에는 보정 DP가 없어서 드라이버가 `temperatureCorrection`(°C, 소수 가능), `humidityCorrection` 설정 값을 더하고 소수 첫째 자리로 반올림합니다. 바꾸면 바로 다시 조회합니다. 표준 `tempOffset`·`humidityOffset` preference와 섞이지 않게 이름을 따로 씁니다.

## DP

| DP | 코드 | 처리 |
|---|---|---|
| 2 | `co2_value` | `carbonDioxideMeasurement` (ppm) |
| 18 | `temp_current` | `temperatureMeasurement` (°C 고정, 표시 단위 설정과 무관. 온도 보정을 더함) |
| 19 | `humidity_value` | `relativeHumidityMeasurement` (습도 보정을 더하고 0~100으로 자름) |
| 102 | `pm25` | `veryFineDustSensor` (이름과 달리 실제 PM1.0) |
| 20 | `pm25_value` | `fineDustSensor`, `dustSensor.fineDustLevel` |
| 101 | `pm10` | `dustSensor.dustLevel` |
| 21 | `voc_value` | `tvocMeasurement` (원시값 = μg/m³, `ug/m3`. capability 단위가 ppm/ppb/ug/m3뿐) |
| 22 | `ch2o_value` | `formaldehydeMeasurement` (HCHO, ÷1000, `mg/m^3`. capability 단위가 ppm/mg/m^3뿐) |
| 15 | `battery_percentage` | `battery` |
| 1, 106 | `co2_state`, `pm25_state` | `alarm`이면 종합 공기질을 최소 `unhealthy`로 |
| 26, 105, 13, 108 | 경보 기준, 경보음, 화면 자동 꺼짐 | 기기 설정에서 바꿀 때만 씀 |
| 14, 17, 31, 103, 107, 109 | | 안 씀 |

클라우드 데이터 모델에는 DP가 12개(1, 2, 5, 7, 13, 15, 17~22)뿐이고 PM10·PM1.0 등은 로컬 응답에만 있습니다.

## 테스트

```bash
uv sync
uv run tests/test_lua.py                 # AES/GCM/SHA-256/HMAC, 3.5 프레임을 cryptography·tinytuya와 비교
uv run tests/test_driver.py              # SmartThings 모의 객체 위에서 init.lua 실행
uv run tests/test_driver.py --live       # 실제 센서 대상 (devices.json 필요)
uv run tests/test_lua.py --live-write    # 실제 센서에 쓰기 응답까지 확인
```

`--live` 계열은 tinytuya wizard가 만든 `devices.json`(id, key)을 저장소 루트에서 읽습니다.

## 진단 도구

```bash
uv run pv28_diag.py all --ip 192.168.0.x            # 포트, 프로토콜 계열, UDP 탐색 (+키가 있으면 DP 덤프, 동시 연결)
uv run pv28_diag.py status --ip 192.168.0.x --key <LOCAL_KEY>
```

`ports`, `probe`, `listen`, `status`, `multi`, `write-test` 하위 명령이 있습니다. 결과는 `diag-results/`에 저장되고 Local Key는 기록하지 않습니다.

## 직접 빌드해서 설치

[SmartThings CLI](https://github.com/SmartThingsCommunity/smartthings-cli)가 필요합니다.

```bash
smartthings edge:channels:create
smartthings edge:channels:enroll
smartthings edge:drivers:package driver --channel <CHANNEL_ID> --hub <HUB_ID>
smartthings edge:drivers:logcat
```

## 알려진 문제

- DP 31(온도 표시 단위) 쓰기가 불안정합니다. 같은 값을 다시 쓰면 반대로 바뀌거나, 이후 쓰기가 성공 응답만 오고 무시되는 경우가 있었습니다. 그래서 드라이버는 DP 31을 건드리지 않습니다.
- 기기 설정 쓰기(DP 26, 105, 13, 108)는 실제 센서에서 충분히 검증하지 못했습니다.
- 앱의 기기 설정 값은 센서에서 읽어 오지 않습니다. 센서에서 직접 바꾼 설정은 앱에 반영되지 않습니다.
- GCM IV와 세션 nonce는 `math.random`으로 만듭니다. Edge에 암호학적 난수 API가 없어서입니다.

## 참고

- [research-report.md](research-report.md): 구현 전에 조사한 내용 (기존 드라이버, 대안, 프로토콜). 실제 구현과 다른 점은 문서 앞머리에 있습니다.
