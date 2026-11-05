# PV28-CW SmartThings Edge Driver

Tuya PV28-CW 공기질 센서를 SmartThings 허브에 로컬(LAN)로 연결하는 Edge 드라이버입니다.
Tuya 클라우드를 거치지 않고 허브가 센서에 직접 접속해서 30초마다 값을 가져옵니다.

SmartThings Edge LAN driver for the Tuya PV28-CW air quality sensor (Tuya protocol 3.5, no cloud).

## 지원 항목

- 공기질, 이산화탄소 농도, PM 1.0, PM 2.5, PM 10, 휘발성 유기화합물(TVOC), 포름알데히드
- 온도, 습도, 배터리
- 센서 설정: 경보음, 이산화탄소 농도·PM 2.5 경보 기준, 화면 자동 꺼짐

화면 구성과 공기질 등급은 SmartThings 기본 Matter 공기질 센서와 같게 맞췄습니다.

## 준비물

- SmartThings 허브 (센서와 같은 네트워크)
- Smart Life 또는 Tuya Smart 앱에 등록된 PV28-CW
- 센서의 IP 주소, Device ID, Local Key

## 설치

1. [채널 초대 링크](https://bestow-regional.api.smartthings.com/invite/VbMbQYdZoKjB)에서 허브를 등록하고 **PV28-CW Tuya LAN** 드라이버를 설치합니다.
2. SmartThings 앱 → 기기 추가 → **주변 기기 검색**을 누르면 "공기질 센서"가 추가됩니다.
3. 추가된 기기의 설정에 IP 주소, Device ID, Local Key를 입력합니다.

잠시 뒤 값이 들어오기 시작합니다.

## Device ID, Local Key 확인

[tuyawizard](https://github.com/3735943886/tuyawizard)를 쓰면 Tuya 개발자 계정 없이 Smart Life 앱 로그인만으로 확인할 수 있습니다.

1. Smart Life 앱 → 나 → 설정 → 계정 및 보안 → **사용자 코드**를 확인합니다.
2. tuyawizard를 실행합니다.
   - Windows: [Releases](https://github.com/3735943886/tuyawizard/releases/latest)에서 `tuyawizard-windows.zip`을 받아 `tuyawizard.exe` 실행
   - 그 외: `pip install tuyawizard cryptography` 후 `python -m tuyawizard`
3. 사용자 코드를 입력하고, 화면에 나온 QR 코드를 Smart Life 앱으로 스캔합니다.
4. 만들어진 `tuyadevices.json`에서 센서의 `id`가 Device ID, `local_key`가 Local Key입니다.

IP 주소는 공유기 관리 페이지에서 확인하고, 바뀌지 않게 고정(DHCP 예약)해 두세요.
`tuyadevices.json`의 `ip`는 외부 IP라서 쓸 수 없습니다.

앱에서 센서를 삭제했다가 다시 등록하면 Local Key가 바뀝니다. 이때는 새 키를 다시 넣어 주세요.

## 공기질 등급

공기질은 아래 항목 중 가장 나쁜 등급을 따릅니다.

| 항목 | 좋음 | 약간 나쁨 | 나쁨 | 매우 나쁨 |
|---|---|---|---|---|
| PM 2.5, PM 1.0 (μg/m³) | ~15 | ~35 | ~75 | 76~ |
| PM 10 (μg/m³) | ~30 | ~80 | ~150 | 151~ |
| 이산화탄소 농도 (ppm) | ~1000 | ~2000 | 2001~ | |
| TVOC (μg/m³) | ~400 | ~1000 | 1001~ | |

센서 자체 경보(이산화탄소 농도, PM 2.5 경보 기준 초과)가 울리면 최소 "나쁨"으로 표시합니다.

## 문제 해결

- **오프라인으로 나올 때**: IP 주소가 바뀌지 않았는지, Device ID와 Local Key가 맞는지 확인하세요.
- **기기가 추가되지 않을 때**: 드라이버가 허브에 설치됐는지 확인하고 주변 기기 검색을 다시 해 보세요. 설정을 입력하지 않은 기기가 이미 있으면 새로 만들지 않습니다.
- **로그**: [SmartThings CLI](https://github.com/SmartThingsCommunity/smartthings-cli)로 `smartthings edge:drivers:logcat`을 실행하면 볼 수 있습니다.

## 개발

구조, 테스트, 직접 빌드하는 방법은 [docs/development.md](docs/development.md)에 있습니다.

## 참고

- [tinytuya](https://github.com/jasonacox/tinytuya): 프로토콜 동작 기준 (코드는 복사하지 않음)
- [make-all/tuya-local](https://github.com/make-all/tuya-local): PV28-CW DP 정의
- [SmartThingsEdgeDrivers](https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers): 공기질 프로필, LAN 드라이버 구조

## 라이선스

[MIT](LICENSE)

Tuya, Smart Life, SmartThings는 각 소유자의 상표이며, 이 프로젝트는 이들과 관련이 없습니다.
