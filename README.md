# PV28-CW SmartThings 로컬 Edge 드라이버

SmartThings Edge LAN driver for the Tuya PV28-CW air quality monitor. Talks Tuya protocol 3.5 directly from the hub (no cloud).

Tuya PV28-CW 공기질 측정기(`co2bj` / `yrr3eiyiacm31ski`)를 SmartThings 허브에 LAN으로 직접 연결하는 Edge 드라이버 프로젝트.
클라우드를 거치지 않고 허브가 30초마다 기기(TCP 6668, Tuya 프로토콜 3.5)에 접속해 값을 읽는다.
조사 배경과 대안 비교는 [docs/research-report.md](docs/research-report.md)에 있다.

## 드라이버 (`driver/`)

```
driver/
  config.yml                      # packageKey pv28cw-tuya-lan, 권한 lan + discovery
  profiles/pv28cw-air-monitor.yml # capability 16개 + 설정(IP, Device ID, Local Key, 조회 주기, 기기 설정 4개)
  src/init.lua                    # 수명주기, 폴링 타이머, refresh, 설정 변경 처리
  src/dpmap.lua                   # DP → capability 변환, 등급 기준, 설정 → DP 쓰기 값
  src/discovery.lua               # 자리표시자 기기 생성 (허브는 Tuya 탐색 포트를 bind할 수 없음)
  src/tuya/client.lua             # 연결 → 세션 키 협상 → DP_QUERY_NEW / CONTROL_NEW → 종료
  src/tuya/protocol.lua           # 3.5 프레임(6699) pack/unpack, 세션 키 계산
  src/tuya/aes.lua gcm.lua sha256.lua  # 순수 Lua AES-128, AES-GCM, SHA-256/HMAC (직접 작성)
```

매핑: CO2(DP 2), 온도(18, 항상 °C), 습도(19), PM2.5(20 → `fineDustSensor`, `dustSensor.fineDustLevel`), PM10(101), PM1.0(102),
TVOC(21, μg/m³ 그대로), HCHO(22, ÷1000 mg/m³), 배터리(15). 등급(`*HealthConcern`)은 미세먼지는 환경부 예보 등급
(PM2.5 15/35/75, PM10 30/80/150), CO2는 1000/2000 ppm, TVOC는 400/1000 μg/m³ 기준이고, 기기 자체 경보(DP 1, 106)가
울리면 최소 `unhealthy`로 올린다. 종합 `airQualityHealthConcern`은 가장 나쁜 항목을 따른다.

### 테스트

허브 없이 PC에서 Lua 5.3(lupa)으로 드라이버 코드를 그대로 실행한다.

```bash
uv run tests/test_lua.py                  # AES/GCM/SHA-256/HMAC, 3.5 프레임, 세션 키를 cryptography·tinytuya와 비교
uv run tests/test_lua.py --live-write     # + Lua 클라이언트로 실제 기기 조회·쓰기 응답 확인
uv run tests/test_driver.py --live        # + SmartThings 모의 객체 위에서 init.lua 전체를 실제 기기에 실행
```

### 허브에 설치

1. SmartThings CLI 설치 (Node 24.22.1 이상)

   ```bash
   npm install -g @smartthings/cli
   ```

2. 패키지 업로드 (처음 실행하면 브라우저에서 SmartThings 로그인)

   ```bash
   smartthings edge:drivers:package driver
   ```

3. 채널을 만들고 드라이버 배정, 허브 등록, 설치 (각 명령이 선택지를 물어봄)

   ```bash
   smartthings edge:channels:create
   smartthings edge:channels:assign
   smartthings edge:channels:enroll
   smartthings edge:drivers:install
   ```

4. SmartThings 앱 → 기기 추가 → 주변 기기 검색 → "PV28-CW 공기질 측정기" 생성
5. 기기 설정에서 IP 주소(공유기에서 DHCP 예약 권장), Device ID, Local Key 입력 → 2초 뒤 첫 조회
   (Local Key는 SmartThings 기기 설정값으로 저장되므로 같은 위치의 멤버에게 보인다)
6. 로그 확인

   ```bash
   smartthings edge:drivers:logcat
   ```

코드를 고친 뒤에는 2번(`package`)과 `edge:drivers:install`만 다시 하면 된다.

### 허브에서 아직 확인하지 않은 것

- 프로필 preference 문법 (integer/boolean 정의, 빈 문자열 대신 `0.0.0.0`/`-` 기본값)과 앱 화면 표시
- `shared_device_thread_enabled = false` 템플릿 옵션 적용 여부
- 기기 설정 쓰기(DP 26, 105, 13, 108)는 실기 미검증. 이 기기는 쓰기가 불안정한 DP가 있다:
  DP 31(온도 단위)은 처음엔 `c`↔`f` 쓰기가 됐지만, 같은 값 `c`를 다시 쓴 순간 `f`로 바뀌었고 그 뒤로는
  `c` 쓰기가 성공 응답만 오고 무시됐다 (tinytuya도 동일). 그래서 드라이버는 DP 31을 쓰지 않는다
- 허브 CPU에서의 순수 Lua 암호 처리 시간 (PC에서는 조회 1회 약 0.6초, 대부분 네트워크 대기)

## 진단 스크립트

Python 환경은 uv로 관리한다.

```bash
uv sync
uv run pv28_diag.py all                       # 키 없이: 포트 → 버전 계열 → UDP 탐색
uv run pv28_diag.py all --key <LOCAL_KEY>     # 키 있으면: + DP 덤프(30초 x 10회) + 동시 연결 테스트
```

| 명령 | 하는 일 | 키 필요 |
|---|---|---|
| `ports` | ping, TCP 6668 열림 여부 | X |
| `probe` | 평문 3.1식 DP_QUERY로 3.1/3.3 vs 3.4/3.5 판별 | X |
| `listen` | UDP 6666/6667/7000 수신 + 3.5용 REQ_DEVINFO 요청 → Device ID, 버전, productKey | X |
| `status` | 버전 자동 감지 후 DP 덤프, 표에 없는 DP / 변하지 않는 측정값 표시 | O |
| `multi` | 연결 2개 동시 허용 여부, 유휴 시 기기가 끊는지 | O |
| `write-test` | DP 31(온도 단위) 쓰기 → 확인 → 원래 값 복구 | O |

주요 옵션: `--ip`(기본값은 작성자 기기 주소이므로 직접 지정), `--id`, `--key`, `--ver`, `--count`, `--interval`, `--updatedps`, `--hold`.
`write-test`와 `tests/test_lua.py --live-write`는 기기에 실제로 쓴다 (위의 DP 31 주의 참고).
`--id`/`--key`를 생략하면 이 폴더의 `devices.json`(tinytuya wizard 출력)에서 찾는다.
결과는 `diag-results/*.json`에 저장되고 Local Key는 기록하지 않는다.

## Local Key 얻기

1. https://iot.tuya.com 에서 Cloud 프로젝트 생성 (Smart Life 앱 계정과 같은 데이터센터)
2. Devices → Link App Account → Smart Life 앱으로 QR 스캔
3. `uv run python -m tinytuya wizard` 실행 후 API Key/Secret 입력 → `devices.json` 생성

`tinytuya.json`, `devices.json`, `snapshot.json`에는 비밀값이 들어 있으므로 `.gitignore`에 넣어 두었다.

## 진단 결과 (2026-11-06)

결과 원본은 로컬 `diag-results/`에만 두고 저장소에는 올리지 않는다 (Device ID 포함).

**연결**

- TCP 6668 열림. 평문 질의는 응답 없이 끊고, UDP 7000 REQ_DEVINFO에 `version=3.5`, `productKey=yrr3eiyiacm31ski`로 응답
  - 스스로 브로드캐스트하지 않음 → 허브(포트 0만 bind 가능)에서는 자동 발견 불가, IP/ID/Key 수동 입력
- Local Key로 **v3.5 첫 시도에 성공**. 30초 간격 연결→조회→종료 10회 모두 성공, 측정값 정상 갱신
- 동시 연결 2개 허용, 두 번째 연결이 첫 연결을 끊지 않음, 유휴 20초 동안 유지 → HA 등과 공존 가능, 지속 연결 모드도 가능
- 쓰기(CONTROL_NEW): DP 31 `c`→`f`→`c` 반영·복구 성공. 그동안 DP 18은 20 그대로 → DP 18은 표시 단위와 무관하게 °C로 보임
- 클라우드 DP 모델(`devices.json` mapping)에는 12개(1, 2, 5, 7, 13, 15, 17~22)뿐. PM10·PM1.0·임계값 등은 로컬 응답에만 있음
- 앱 대조: 앱 PM2.5 7 / PM1.0 5 / PM10 8 = DP 20 / 102 / 101 값 그대로 → DP 102는 PM1.0 확정

**DP 표 (관측값 기준)**

| DP | 코드 | 관측값 (4.5분) | 드라이버 처리 |
|---|---|---|---|
| 2 | `co2_value` | 779–790 | `carbonDioxideMeasurement` ppm |
| 18 | `temp_current` | 19–20 | `temperatureMeasurement` C (정수) |
| 19 | `humidity_value` | 61 | `relativeHumidityMeasurement` |
| 20 | `pm25_value` | 6–8 | `fineDustSensor` (+ `dustSensor.fineDustLevel`) |
| 101 | `pm10` | 6–8 | `dustSensor.dustLevel` |
| 102 | `pm25` | 5–6 | `veryFineDustSensor` (실제 PM1.0, 앱 값과 일치 확인) |
| 21 | `voc_value` | 133–147 | `tvocMeasurement` ug/m3 그대로 (= 0.133–0.147 mg/m3) |
| 22 | `ch2o_value` | 11–12 | `formaldehydeMeasurement` raw/1000 mg/m^3 |
| 15 | `battery_percentage` | 100 | `battery` |
| 14 | `battery_state` | `normal`/`charge` 번갈아 | 무시 (USB 연결 중 계속 뒤집힘) |
| 1, 106 | `co2_state`, `pm25_state` | `normal` | HealthConcern 보정용 |
| 103 | `humidity_current` | 61 | 무시 (DP 19와 중복) |
| 13, 26, 105, 108 | 경보 on/off, CO2/PM2.5 경보 임계값, 화면 자동 꺼짐 | `False`, 1500, 75, `True` | 설정(preferences)에서 쓰기 |
| 31, 109 | 온도 단위, 화면 꺼짐 시간 | `c`, 60 | 쓰지 않음 (DP 31 쓰기 불안정) |
| 17 | `alarm_bright` | 화면 꺼짐 0 / 켜짐 10 | 쓰지 않음 (현재 화면 밝기로 보임, 쓰기 명령이 오면 화면이 켜짐) |
| 107 | `check_time` | `False` (bool) | 용도 미상, 쓰지 않음 |
| 5, 6, 7, 104 | 경보 음량·종류·시간, 공기질 등급 | 안 옴 | 쓰지 않음 |

**드라이버 방향**: Tuya **3.5**(6699 프레임, 세션 키 협상, HMAC-SHA256, AES-128-GCM)만 구현하고, 기본은 30초 연결→조회→종료.

## 참고

- 프로토콜 동작은 [tinytuya](https://github.com/jasonacox/tinytuya)(MIT) 1.20.0 소스를 기준으로 맞췄다. Lua 코드는 직접 작성했고 복사한 코드는 없다.
- DP 표의 출발점: [make-all/tuya-local](https://github.com/make-all/tuya-local) PV28-CW 설정, Home Assistant 테스트 fixture `co2bj_yrr3eiyiacm31ski`
- capability·프로필 구성: [SmartThingsEdgeDrivers](https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers)의 공기질 드라이버
- GCM IV와 세션 nonce는 Edge에 암호학적 난수 API가 없어 `math.random`으로 만든다. LAN 안에서만 쓰는 용도로 감수했다.

Tuya, Smart Life, SmartThings는 각 소유자의 상표이며 이 프로젝트는 그들과 관계가 없다. 기기 설정 쓰기는 사용자 책임으로 쓴다.

## 라이선스

[MIT](LICENSE)
