# 개발 문서

## 구조

```
driver/
  config.yml                       # packageKey pv28cw-tuya-lan, 권한 lan + discovery
  profiles/pv28cw-air-monitor.yml  # capability 11개, 기기 설정
  src/init.lua                     # 수명주기, 폴링, refresh, 설정 변경
  src/dpmap.lua                    # DP → capability, 공기질 등급, 설정 → DP
  src/discovery.lua                # 주변 기기 검색 시 빈 기기 생성
  src/tuya/client.lua              # 연결 → 세션 키 협상 → 조회/제어 → 종료
  src/tuya/protocol.lua            # Tuya 3.5 프레임(6699), 세션 키
  src/tuya/aes.lua gcm.lua sha256.lua
pv28_diag.py                       # 센서 진단 도구 (tinytuya)
tests/                             # Lua 5.3(lupa)로 드라이버 코드를 PC에서 실행
```

## 동작 방식

- 30초(설정 가능)마다 TCP 6668로 접속해 세션 키를 협상하고 `DP_QUERY_NEW` 한 번 보낸 뒤 연결을 끊습니다.
- Edge 런타임에는 쓸 만한 암호 API가 없어서 AES-128, GCM, SHA-256/HMAC을 순수 Lua로 구현했습니다.
- 허브는 Tuya 탐색 포트(UDP 6666/6667/7000)를 bind할 수 없습니다. 그래서 주변 기기 검색 때 빈 기기를 만들고 IP/ID/Key는 사용자가 넣습니다.
- 연속 3번 조회에 실패하면 오프라인으로 표시합니다.

## DP

| DP | 코드 | 처리 |
|---|---|---|
| 2 | `co2_value` | `carbonDioxideMeasurement` (ppm) |
| 18 | `temp_current` | `temperatureMeasurement` (°C 고정, 표시 단위 설정과 무관) |
| 19 | `humidity_value` | `relativeHumidityMeasurement` |
| 102 | `pm25` | `veryFineDustSensor` (이름과 달리 실제 PM1.0) |
| 20 | `pm25_value` | `fineDustSensor`, `dustSensor.fineDustLevel` |
| 101 | `pm10` | `dustSensor.dustLevel` |
| 21 | `voc_value` | `tvocMeasurement` (원시값 = μg/m³) |
| 22 | `ch2o_value` | `formaldehydeMeasurement` (÷1000, mg/m³) |
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
- GCM IV와 세션 nonce는 `math.random`으로 만듭니다. Edge에 암호학적 난수 API가 없어서입니다.

## 참고

- [research-report.md](research-report.md): 처음 조사한 내용 (기존 드라이버, 대안, 프로토콜)
