# 부품을 조립해 PV28-CW를 허브에 직결하라

> 구현 전에 정리한 조사 기록입니다. 실제 드라이버는 이 문서의 권고와 다음이 다릅니다. 현재 동작은 [development.md](development.md)를 보세요.
>
> - 프로토콜은 3.5만 구현했습니다. AES, GCM, SHA-256은 다른 저장소에서 가져오지 않고 직접 작성했고 `st.security`는 쓰지 않습니다.
> - 오염원별 `*HealthConcern` 없이 종합 `airQualityHealthConcern`만 쓰고, 등급 기준은 MultiIR 대신 환경부 예보 등급입니다 (README "공기질 등급").
> - 3.5 요청에는 Device ID가 들어가지 않아서 설정에서 뺐습니다.
> - 쓰는 기기 설정은 DP 13, 26, 105, 108뿐입니다. DP 31은 쓰기가 불안정해서 쓰지 않습니다.

2026년 11월 6일 현재, PV28-CW를 SmartThings 허브에 LAN으로 직접 붙이는 **기성 Edge 드라이버는 없다**. 범위를 Tuya `co2bj` 카테고리의 Wi-Fi 공기질 측정기 전체로 넓혀도 마찬가지다. 그래도 필요한 부품은 모두 공개돼 있다. 2026년 5~10월에 허브에서 Tuya 로컬 프로토콜(3.3/3.4/3.5)을 순수 Lua로 직접 처리하는 커뮤니티 드라이버가 최소 4종 나왔다. PV28-CW의 DP 표는 tuya-local과 Home Assistant 테스트 fixture에 정리돼 있다. PM1.0·PM2.5·PM10·CO2·TVOC·HCHO·온습도를 받을 공식 capability도 있고, 거의 그대로 쓸 수 있는 공식 프로필도 있다. 그러니 프로토콜 코덱은 새로 쓰지 말고 가져오는 것이 가장 현실적이다. GPL을 받아들일 수 있으면 drdecibel의 Arida 드라이버를, 허용적 라이선스가 필요하면 MIT인 ST-SmartHome 코드와 tinytuya 포팅을 쓴다. 새로 쓸 것은 PV28-CW 전용 DP→capability 변환 표, 프로필, 설정, 폴링 루프뿐이다. 진짜 위험은 코드가 아니라 기기 쪽에 있다. 2024년 한 소유자의 PV28-CW는 클라우드에만 연결돼 있고 로컬 포트가 모두 닫혀 있었다. 이 모델의 프로토콜 버전은 공개된 기록이 없다. 게다가 Tuya 기기는 로컬 TCP 연결을 하나, 많아야 몇 개만 받는다. 따라서 첫 작업은 코딩이 아니다. `tinytuya scan`·`wizard`·`status()`로 내 기기의 6668 포트, 프로토콜 버전, local_key, 실제 DP 값을 먼저 확인해야 한다. 암호화는 자료가 엇갈린다. 공식 APIv21 라이브러리에는 문서화되지 않은 네이티브 `st.security`(AES 암·복호화, 해시 함수)가 들어 있지만, 2026년 Tuya 드라이버 작성자들은 "네이티브 암호화가 없다"고 적었다. 실무 결론은 이중 구조다. `pcall`로 모듈을 확인하고, 자가 시험을 통과할 때만 네이티브 AES-ECB를 쓴다. GCM과 HMAC은 순수 Lua로 둔다.

## 기성 드라이버는 없고, 허브 직결 Tuya 드라이버 4종은 모두 다른 기기용이다

GitHub, SmartThings Community, DCInside 스마트싱스 갤러리, r/SmartThings를 조사했지만 PV28-CW나 Tuya Wi-Fi 공기질 측정기용 Edge 드라이버는 찾지 못했다. 그사이 바뀐 것은 Tuya 프로토콜 쪽이다. 2024년 3월만 해도 커뮤니티 답변은 "기존 Tuya Wi-Fi Edge 드라이버는 모른다"였고, tuyapi를 Lua로 포팅하자는 제안도 결과물로 이어지지 않았다 ([SmartThings Community: Edge Driver for Tuya Wi-Fi Devices Project](https://community.smartthings.com/t/edge-driver-for-tuya-wi-fi-devices-project/279645)). 2026년에는 허브가 TCP 6668로 기기와 직접 통신하는 드라이버가 여럿 나왔다. 다만 모두 특정 기기용이고, 나온 지 2~6개월밖에 안 됐다.

| 드라이버 | 대상 기기 | Tuya 버전 | 암호 구현 | 라이선스 | 최근 활동 | 평가 |
|---|---|---|---|---|---|---|
| [drdecibel/smartthings-arida-tuya-edge](https://github.com/drdecibel/smartthings-arida-tuya-edge) | Arida 환기장치 | 3.3/3.4/3.5 (실기 검증은 3.5만) | 순수 Lua (lockbox AES + T-table AES, GCM, SHA-256/HMAC) | GPL-3.0-or-later | 2026-10-27 | tinytuya와 바이트 단위 일치, 테스트 63개. 코덱 품질 최고 |
| [ST-SmartHome/smartthings-drivers](https://github.com/ST-SmartHome/smartthings-drivers) | Ventair Skyfan, Hunter Pacific 선풍기 | 3.3 + 3.5 자동 감지 | lockbox 기반 순수 Lua | MIT | 2026-10-09 (3.5 추가) | 3.5는 실기 2대에서 확인, 3.3 모듈은 실기 미검증 |
| [ldeora tuya-air-purifier](https://github.com/ldeora/SmartThingsEdgeDrivers/tree/main/tuya-air-purifier) | KLAMER 500i류 공기청정기 | 3.3만 | 직접 작성한 AES-128-ECB (PoC) | 이번 조사에서 미확인 | 2026-08-03 | 공기질 capability 구성 참고용 |
| Halwin12 "Tuya Wi-Fi" | 범용 DPS | 사용자 선택 (지원 목록 미상) | 미상 (소스 비공개) | 미상 | 2026-05 | 테스터 평가 "half-baked" |

Arida 드라이버 README에 따르면 3.3, 3.4, 3.5의 프레임·핸드셰이크·세션 키가 tinytuya와 바이트 단위로 같다. 3.5 실기 3대에서 키 입력, 기기 생성, 프로토콜 감지, 상태 읽기, DHCP 변경 뒤 IP 재탐색까지 검증했다. 반면 대부분의 명령과 3.3/3.4 실기 동작은 아직 검증하지 않았다 ([Arida README](https://github.com/drdecibel/smartthings-arida-tuya-edge/blob/main/README.md)). Skyfan 드라이버는 2026-10-09에 3.5 지원을 추가했고, 팬이 **로컬 연결을 한 번에 하나만 받는다**고 경고한다 ([SmartThings Community: Ventair Skyfan](https://community.smartthings.com/t/st-edge-lan-driver-ventair-skyfan-dc-ceiling-fan/310702)). Halwin12의 범용 드라이버는 Local Key, Host IP, Device ID, Protocol Version, "Auto profile from DPS" 설정을 제공한다. 그러나 테스터 보고는 좋지 않다. 스마트 플러그의 전력값이 NaN으로 나왔고, 6개 기기 중 완전히 동작한 것은 2개뿐이었으며, 조명 하나는 Smart Life에서 오프라인이 됐다 ([SmartThings Community: Anyone using the Tuya Wi-Fi Edge Driver?](https://community.smartthings.com/t/anyone-using-the-tuya-wi-fi-edge-driver/309594)). Halwin12를 뺀 세 드라이버는 DP 표가 해당 기기에 고정돼 있어서 PV28-CW를 연결해도 측정값이 나오지 않는다. 3.4/3.3을 지원한다는 [WoongTs/tuya-fan-1570C](https://github.com/WoongTs/tuya-fan-1570C)도 있지만, 이번 조사에서 코드는 읽지 않았다.

질문에서 기준으로 삼은 MIoT 드라이버는 한국 커뮤니티가 주도한다. 가장 큰 [wonjj6768/smartthings-miot-edge-driver](https://github.com/wonjj6768/smartthings-miot-edge-driver)는 모델별 드라이버 약 215개(Qingping Air Monitor 포함)를 개인 채널로 배포한다. 기기 설정에서 `ipAddress`·`token`·`pollingInterval`을 받고, `createDev` 토글로 LAN 기기를 수동 생성한다. 이 저장소를 소개한 DCInside 글은 "Tuya 드라이버는 안정화되면 공개"한다고 예고했다 ([DCInside 스마트싱스 갤러리 14527](https://gall.dcinside.com/mgallery/board/view/?id=smartthings&no=14527)). 하지만 같은 작성자의 예전 `smartthings-tuya-edge-driver` 저장소는 Zigbee 드라이버로 옮겨 갔고, Tuya Wi-Fi/LAN 코드는 남아 있지 않다 ([GitHub](https://github.com/wonjj6768/smartthings-tuya-edge-driver)). 공식 Tuya/Smart Life 계정 연동은 클라우드 간(cloud-to-cloud) 방식이다. 커뮤니티에서는 Smart Life 센서가 SmartThings에 나타나지 않는다는 보고가 반복된다 ([CO Sensor in Smart Life Not Showing](https://community.smartthings.com/t/co-sensor-in-smart-life-not-showing-in-smartthings/281951); [Using Tuya WiFi Sensors with SmartThings?](https://community.smartthings.com/t/using-tuya-wifi-sensors-with-smartthings/282011)). 무엇보다 클라우드를 빼고 싶다는 요구와 맞지 않는다.

MIoT 드라이버를 고쳐 쓸 수 없는 이유는 두 프로토콜에 공통점이 거의 없어서다. 모델별 드라이버, 설정으로 IP·키 입력, 폴링 같은 구조는 본뜰 수 있다. 하지만 전송 방식, 암호화, 연결 모델은 새로 짜야 한다.

| 항목 | Xiaomi miIO/MIoT (wonjj6768, YEUNU) | Tuya LAN (PV28-CW) |
|---|---|---|
| 전송 | UDP 54321 | TCP 6668, 기기당 로컬 연결 1개(또는 소수) |
| 암호 | AES-128-CBC, `key = md5(token)`, `iv = md5(key ‖ token)`, MD5 체크섬 | 3.3: AES-128-ECB + CRC32 / 3.4: 세션 키 협상 + ECB + HMAC-SHA256 / 3.5: 세션 키 협상 + AES-128-GCM |
| 키 획득 | Xiaomi Cloud Tokens Extractor 등으로 token 추출 | Tuya IoT Platform 클라우드 프로젝트 + `python -m tinytuya wizard`로 16자 local_key 획득 |
| 허브 측 발견 | UDP 스캔 가능 | 허브는 포트 0만 bind할 수 있어 6666/6667 브로드캐스트 수신 불가, 수동 입력 필요 |

MIoT 쪽 내용은 wonjj6768과 YEUNU 소스에서 확인했다 ([wonjj6768 libs/miio.lua](https://github.com/wonjj6768/smartthings-miot-edge-driver/blob/main/libs/miio.lua); [YEUNU miio/packet.lua](https://github.com/YEUNU/edge_iot/blob/main/xiaomi-miio/src/miio/packet.lua)). Tuya 쪽은 tinytuya 코드와 Tuya 임베디드 SDK 헤더에서 확인했다 ([tinytuya XenonDevice.py](https://github.com/jasonacox/tinytuya/blob/c0eb2ee3594f44bd43587fd6390676eca9d312f8/tinytuya/core/XenonDevice.py#L893-L969); [Tuya lan_protocol.h](https://github.com/tuya/tuya-iotos-embeded-sdk-wifi-ble-bk7231n/blob/master/sdk/include/lan_protocol.h#L71-L101)).

## 코덱은 가져오고 DP 표만 새로 쓴다: 어느 저장소를 쓸지는 라이선스가 정한다

선택지를 현실성 순으로 정리하면 아래와 같다. 1순위가 확실히 낫다. Tuya 프로토콜 구현은 이미 흔한 부품이 됐고, PV28-CW만을 위한 작업은 DP를 capability로 옮기는 표 하나 정도이기 때문이다.

| 순위 | 선택지 | 경로 | 해야 할 일 | 핵심 위험 |
|---|---|---|---|---|
| 1 | **새 PV28-CW 드라이버 + 검증된 Tuya 코덱 이식** | 허브 직결 | DP 표, 프로필, 설정, 폴링 루프만 새로 작성 | 기기 펌웨어(포트 닫힘), 3.3/3.4 실기 검증 부족 |
| 2 | Halwin12 범용 드라이버 시험 | 허브 직결 | 설정 입력만 | 값 NaN, 다른 기기가 오프라인된 사례, 소스 비공개 |
| 3 | Home Assistant + tuya-local → MQTT(MQTTDevices) 또는 Matter 브리지 | LAN + 상시 브리지 호스트 | HA 운용, 매핑 | HA가 단일 연결을 점유, Matter 공기질 표시 방식 미검증 |
| 4 | OpenBeken 재플래시(Cloudcutter) + MQTT | LAN, 클라우드 완전 제거 | 플래시, 템플릿 작성 | PV28-CW 템플릿 없음, MCU 업데이트가 끊긴다는 보고 |
| 5 | 공식 Tuya/Smart Life C2C 연동 | 클라우드 | 계정 연결 | 센서 누락 보고, 클라우드 의존 |

1순위 안에서 어느 코드베이스를 쓸지는 라이선스가 정한다. **Arida는 GPL-3.0-or-later다.** `src/tuya/` 폴더(`frame55`, `v33`, `v34`, `v35`, `gcm`, `crc32`, `crypto`, `payload`, `client`)를 통째로 가져오면 3.3/3.4/3.5를 가장 빨리 확보한다. 대신 완성된 드라이버도 GPL-3.0-or-later가 된다 ([Arida 저장소](https://github.com/drdecibel/smartthings-arida-tuya-edge)). 혼자 쓰는 동안에는 의무가 생기지 않는다. 그러나 채널 초대 링크로 남에게 나눠 주면 배포에 해당하므로 GPL 조건으로 소스를 공개해야 한다. 라이선스가 없는 저장소나 MIT 저장소에 합칠 수도, 비공개로 돌릴 수도 없다. Arida의 "DP map" 설정으로 DP를 덮어쓸 수는 있지만, 프로필이 환기장치용이다. 공기질 capability로 보여 주려면 결국 포크해야 한다.

허용적 라이선스를 원하면 MIT 원본으로 거슬러 올라가면 된다. Arida 스스로 tinytuya를 따르면서 ST-SmartHome/smartthings-drivers와 lua-lockbox의 MIT 코드를 재사용한다고 밝힌다 ([Arida AUTHORS.md](https://github.com/drdecibel/smartthings-arida-tuya-edge/blob/main/AUTHORS.md)). ST-SmartHome의 `skyfan-driver/src/`에는 `gcm.lua`, `crc32.lua`, 실기 2대에서 확인된 `tuya35.lua`가 있다. 3.3 모듈 `tuya_protocol.lua`에는 "NOT tested against a live device"라고 적혀 있다 ([skyfan-driver/src](https://github.com/ST-SmartHome/smartthings-drivers/tree/main/skyfan-driver/src)). 3.4는 MIT인 tinytuya의 `XenonDevice._negotiate_session_key`와 `_encode_message`를 함수 단위로 포팅하면 된다 ([tinytuya core/](https://github.com/jasonacox/tinytuya/tree/c0eb2ee3594f44bd43587fd6390676eca9d312f8/tinytuya/core)). 해시 함수는 MIT인 Egor Skriptunoff의 `sha2.lua`(MD5, SHA-256, HMAC) ([pure_lua_SHA](https://github.com/Egor-Skriptunoff/pure_lua_SHA))나 역시 MIT인 [blueyetisoftware/smartthings-edge-crypto](https://github.com/blueyetisoftware/smartthings-edge-crypto)로 채운다. 테스트 벡터는 Arida의 `test/fixtures`를 복사하지 말고 tinytuya로 직접 만드는 편이 라이선스상 깔끔하다. 실기 대신 쓸 상대로는 3.1~3.5 기기를 흉내 내는 Apache-2.0 시뮬레이터 [cB-Sigma/tuyalan-sim](https://github.com/cB-Sigma/tuyalan-sim)이 있다.

라이선스와 관련해 주의할 점이 하나 더 있다. 구조 참고용으로 가장 좋은 wonjj6768과 YEUNU 저장소에는 **라이선스 필드가 없다** ([wonjj6768](https://github.com/wonjj6768/smartthings-miot-edge-driver); [YEUNU/edge_iot](https://github.com/YEUNU/edge_iot)). 라이선스가 없으면 기본 저작권이 그대로 적용되므로, 아키텍처만 참고하고 코드는 복사하지 않는다. lunDreame의 MIoT 드라이버는 "All rights reserved"이고 소스도 공개되지 않았다 ([lunDreame/EdgeDriver](https://github.com/lunDreame/EdgeDriver)).

2순위 이하는 1순위가 막혔을 때의 대안이다. Halwin12 드라이버는 코드 없이 "허브가 이 기기와 통신할 수 있는가"를 확인하는 실험용으로는 쓸 만하다. 다만 다른 Tuya 기기를 오프라인으로 만든 사례가 있으니, Smart Life에서 쓰는 다른 기기가 함께 있는 환경에서는 시험하지 않는 편이 낫다. HA 경로는 tuya-local이 이미 PV28-CW를 지원하므로 드라이버를 개발할 필요가 없다 ([tuya-local DEVICES.md](https://github.com/make-all/tuya-local/blob/main/DEVICES.md)). 실제로 포럼 사용자 두 명이 Tuya Wi-Fi 기기를 HA의 Tuya Local과 Matter 브리지로 SmartThings에 연결해 쓰고 있다 ([SmartThings Community](https://community.smartthings.com/t/anyone-using-the-tuya-wi-fi-edge-driver/309594)). MQTT로 가려면 toddaustin07의 [MQTTDevices](https://github.com/toddaustin07/MQTTDevices)가 브로커만 있으면 로컬 센서 기기를 만들어 준다. 하지만 어느 쪽이든 상시 켜 둔 호스트가 필요하고, PV28-CW의 로컬 연결 슬롯을 HA가 차지한다. MIoT처럼 허브만으로 동작해야 한다는 요구는 충족하지 못한다.

## PV28-CW의 측정 DP 9개는 공식 capability에 그대로 들어간다

PV28-CW는 Ggele, JUANJUAN, meterk 등의 브랜드로 팔리는 화이트라벨 8-in-1 측정기다. Tuya 카테고리는 **`co2bj`**, 제품 ID는 **`yrr3eiyiacm31ski`**이고, HA 코어 fixture에는 `"support_local": true`로 기록돼 있다 ([HA core fixture co2bj_yrr3eiyiacm31ski.json](https://github.com/home-assistant/core/blob/dev/tests/components/tuya/fixtures/co2bj_yrr3eiyiacm31ski.json); [tuya-local PR #931](https://github.com/make-all/tuya-local/pull/931)). 매뉴얼에는 350 mAh 리튬 배터리와 USB-C 충전이 적혀 있다 ([manuals.plus JUANJUAN PV28-CW](https://manuals.plus/ae/1005008797324734), 검색 스니펫 기준). 하드웨어는 2.4 GHz Wi-Fi 전용이다. Beken BK7231N 모듈이 별도 센서 MCU와 9600 baud UART로 통신하는 TuyaMCU 구조다 ([Elektroda topic4036569 p.2](https://www.elektroda.com/rtvforum/topic4036569-30.html), 검색 스니펫 기준). 그래서 DP 번호는 MCU 펌웨어가 정하고, 순정 Tuya 펌웨어든 OpenBeken이든 같다. 이름에 "PV28"이 들어가도 PV28-AW(CO2 3-in-1)와 PV28-COW(일산화탄소)는 DP의 의미가 다르다 ([tuya-local issue #4406](https://github.com/make-all/tuya-local/issues/4406)). 드라이버는 제품 ID를 확인하고, DP 이름이 아니라 **DP 번호**로 매핑해야 한다.

아래 표는 HA fixture의 타입·범위·스케일에 tuya-local YAML과 HA discussion #842의 DP 번호를 합친 것이다 ([tuya-local PV28-CW YAML](https://github.com/make-all/tuya-local/blob/main/custom_components/tuya_local/devices/pv28-cw_airquality_monitor.yaml); [HA discussion #842](https://github.com/orgs/home-assistant/discussions/842)). capability ID와 단위는 공식 APIv21 capability 정의와, 공식 공기질 드라이버가 이벤트를 만드는 코드에서 확인했다 ([zigbee-air-quality-detector MultiIR init.lua](https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers/blob/main/drivers/SmartThings/zigbee-air-quality-detector/src/MultiIR/init.lua); [matter-sensor attribute_handlers.lua](https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers/blob/main/drivers/SmartThings/matter-sensor/src/sub_drivers/air_quality_sensor/air_quality_sensor_handlers/attribute_handlers.lua)).

| DP | 코드 | 원시값 | SmartThings capability.attribute | 변환 |
|---|---|---|---|---|
| 2 | `co2_value` | 0–5000 ppm, scale 0 | `carbonDioxideMeasurement.carbonDioxide` | 그대로, `unit="ppm"` |
| 20 | `pm25_value` | 0–1000 µg/m³ | `fineDustSensor.fineDustLevel` (+ `dustSensor.fineDustLevel`) | 그대로, `unit="μg/m^3"` |
| 101 | `pm10` | 0–1000 µg/m³ | `dustSensor.dustLevel` | 그대로 |
| 102 | `pm25` | 0–1000 µg/m³ | **`veryFineDustSensor.veryFineDustLevel`** | 그대로. 코드명과 달리 실제 값은 **PM1.0** |
| 21 | `voc_value` | 0–9999, mg/m³, **scale 3** | `tvocMeasurement.tvocLevel` | 원시값이 곧 µg/m³, `unit="ug/m3"` (mg/m³는 허용 단위 아님) |
| 22 | `ch2o_value` | 0–9999, mg/m³, **scale 3** | `formaldehydeMeasurement.formaldehydeLevel` | `raw / 1000`, `unit="mg/m^3"` |
| 18 | `temp_current` | −9…199 ℃, **scale 0** | `temperatureMeasurement.temperature` | 그대로, `unit="C"` (정수 해상도) |
| 19 | `humidity_value` | 0–100 % | `relativeHumidityMeasurement.humidity` | 그대로. DP 103 `humidity_current`는 중복이므로 무시 |
| 15 | `battery_percentage` | 0–100 % | `battery.battery` | 그대로 |

주의할 점이 두 가지다. 첫째, **DP 102의 코드명은 `pm25`지만 실제 값은 PM1.0이다.** discussion #842 작성자가 앱과 대조해 확인했다. 둘째, **TVOC와 HCHO 값은 mg/m³에 1000을 곱한 정수다.** 원시값 71은 0.071 mg/m³, 곧 71 µg/m³다. `tvocMeasurement`는 ppm, ppb, ug/m3 단위만 받으므로 원시값을 `ug/m3`로 그대로 보내는 것이 가장 간단하다. tuya-local도 같은 방식이다. 공식 Matter 드라이버는 프로필에 `fineDustSensor`와 `dustSensor`가 함께 있으면 PM2.5 값을 `dustSensor.fineDustLevel`에도 보낸다. 이 방식을 따르는 것이 안전하다.

나머지 DP는 측정값이 아니라 설정값이다. 읽기·쓰기가 가능한 DP는 기기 설정(preferences)으로 노출하고, `infoChanged`에서 바뀐 값만 CONTROL 명령으로 쓰는 것이 깔끔하다. 대상은 다음과 같다.

- 13 `alarm_switch` (bool)
- 26 `maxco2_set` (800–2000 ppm, 100 단위)
- 105 `pm25_set` (15–75 µg/m³, 5 단위)
- 31 `temp_unit_convert` (`c`/`f`)
- 108 `screen_sleep` (bool)
- 109 `screen_sleep_time` (10–300 s, 10 단위)

DP 107(`check_time`)과 109의 번호는 형제 기기 PV33에서 추론한 값이라 실기에서 확인해야 한다. DP 5·6·7·17·104는 iot.tuya.com에는 지원 항목으로 나오지만, tuya-local 작성자가 "동작하지 않는다"며 주석 처리했다 ([tuya-local PR #931](https://github.com/make-all/tuya-local/pull/931)). 이들은 선택 항목으로 둔다. tuya-local YAML은 화면 꺼짐 시간 엔티티를 PM2.5 경보 임계값과 같은 DP 105에 잘못 매핑했으므로 그대로 베끼면 안 된다 ([YAML](https://github.com/make-all/tuya-local/blob/main/custom_components/tuya_local/devices/pv28-cw_airquality_monitor.yaml)). 설정의 기본값을 설치 직후 기기에 강제로 쓰지 말고, 사용자가 값을 바꿨을 때만 쓰게 해야 기기에 이미 해 둔 설정을 덮어쓰지 않는다.

`*HealthConcern` 등급은 공식 MultiIR 드라이버의 기준을 기본값으로 쓰면 된다 ([MultiIR init.lua](https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers/blob/main/drivers/SmartThings/zigbee-air-quality-detector/src/MultiIR/init.lua)).

| 항목 | good | moderate | unhealthy |
|---|---|---|---|
| CO2 | 1500 ppm 이하 | 2500 ppm 이하 | 그 이상 |
| PM2.5 | 75 이하 | 115 미만 | 그 이상 |
| PM1.0 | 100 이하 | | |
| PM10 | 150 이하 | | |
| TVOC | 600 µg/m³ 미만 | | |

이 기준은 국내 체감 기준보다 느슨하므로 임계값을 설정으로 열어 두기를 권한다. 종합 `airQualityHealthConcern`은 하위 지표 중 가장 나쁜 값으로 정한다. 기기 자체 경보 플래그를 반영하는 방법도 있다. DP 1 `co2_state`나 DP 106 `pm25_state`가 `alarm`이 되면 해당 지표를 한 단계 이상 올리는 식이다. 이렇게 하면 사용자가 기기에 설정한 임계값이 SmartThings 등급에도 반영된다. DP 104 `air_quality` 열거형(`great`,`mild`,`good`,`medium`,`severe`)은 값의 순서가 무엇을 뜻하는지 불분명하고 tuya-local에서도 꺼져 있으므로 쓰지 않는다. 등급 값은 `unknown`, `good`, `moderate`, `slightlyUnhealthy`, `unhealthy`, `veryUnhealthy`, `hazardous` 중 하나다. 공식 Matter 드라이버는 초기화 때 `supported*Values`를 `displayed=false`로 한 번 보내 앱에 표시되는 등급 범위를 제한한다. 이 패턴을 따른다 ([matter-sensor air_quality_sensor](https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers/tree/main/drivers/SmartThings/matter-sensor/src/sub_drivers/air_quality_sensor)).

프로필은 공식 Zigbee MultiIR 프로필(PM1/2.5/10, CO2, HCHO, TVOC, 온습도)과 거의 정확히 일치한다. LAN 드라이버에는 의미 없는 `firmwareUpdate`를 빼고 `battery`를 더하면 된다 ([air-quality-detector-MultiIR.yml](https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers/blob/main/drivers/SmartThings/zigbee-air-quality-detector/profiles/air-quality-detector-MultiIR.yml)). `formaldehydeHealthConcern`은 원하면 추가한다. 연결 상태는 공식 LAN 드라이버(Bose, Harman Luxury)처럼 `healthCheck` 대신 `device:online()`/`device:offline()`으로 표시한다 ([SmartThingsEdgeDrivers](https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers)). 아래 예시는 공간을 줄이려고 YAML 흐름 스타일로 썼다. 블록 스타일로 써도 의미는 같다.

```yaml
name: pv28cw-air-monitor
components:
  - id: main
    capabilities:
      - { id: airQualityHealthConcern, version: 1 }
      - { id: carbonDioxideMeasurement, version: 1 }
      - { id: carbonDioxideHealthConcern, version: 1 }
      - { id: fineDustSensor, version: 1 }
      - { id: fineDustHealthConcern, version: 1 }
      - { id: veryFineDustSensor, version: 1 }
      - { id: veryFineDustHealthConcern, version: 1 }
      - { id: dustSensor, version: 1 }
      - { id: dustHealthConcern, version: 1 }
      - { id: tvocMeasurement, version: 1 }
      - { id: tvocHealthConcern, version: 1 }
      - { id: formaldehydeMeasurement, version: 1 }
      - { id: temperatureMeasurement, version: 1 }
      - { id: relativeHumidityMeasurement, version: 1 }
      - { id: battery, version: 1 }
      - { id: refresh, version: 1 }
    categories:
      - name: AirQualityDetector
preferences:
  - { name: ipAddress, title: "IP 주소", required: true, preferenceType: string,
      definition: { stringType: text, default: "" } }
  - { name: deviceId, title: "Device ID", required: true, preferenceType: string,
      definition: { stringType: text, default: "" } }
  - { name: localKey, title: "Local Key (16자)", required: true, preferenceType: string,
      definition: { stringType: text, default: "" } }
  - { name: protoVer, title: "프로토콜 버전", preferenceType: enumeration,
      definition: { options: { auto: "자동", v33: "3.3", v34: "3.4", v35: "3.5" }, default: auto } }
  - { name: pollInterval, title: "폴링 주기(초)", preferenceType: integer,
      definition: { minimum: 10, maximum: 600, default: 30 } }
  - { name: tempOffset, title: "온도 보정", preferenceType: number,
      definition: { minimum: -10, maximum: 10, default: 0 } }
  - { name: co2Alarm, title: "CO2 경보 임계값(DP 26)", preferenceType: integer,
      definition: { minimum: 800, maximum: 2000, default: 1000 } }
  - { name: pm25Alarm, title: "PM2.5 경보 임계값(DP 105)", preferenceType: integer,
      definition: { minimum: 15, maximum: 75, default: 35 } }
  - { name: screenSleep, title: "화면 자동 꺼짐(DP 108)", preferenceType: boolean,
      definition: { default: false } }
```

이번 조사에서 공식 프로필로 문법이 확인된 것은 `preferenceType: string` + `stringType: text` 조합뿐이다 ([zwave-switch aeotec-heavy-duty.yml](https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers/blob/main/drivers/SmartThings/zwave-switch/profiles/aeotec-heavy-duty.yml)). integer·number·boolean·enumeration의 정의 문법과, local key를 가리는 `stringType: password` 지원 여부는 개발자 문서에서 다시 확인해야 한다.

## 3.3·3.4·3.5를 모두 구현하고, `st.security`는 '있으면 쓰는' 가속기로 다룬다

### 버전을 알 수 없으니 자동 감지가 필수다

PV28-CW의 프로토콜 버전이 적힌 공개 기록은 없다. 확인된 사실은 2023년 tuya-local이 지원을 추가할 때 LAN이 동작했다는 것뿐이다 ([tuya-local PR #931](https://github.com/make-all/tuya-local/pull/931)). 같은 시기 BK7231N 펌웨어는 3.3이 흔하고, 최신 펌웨어는 3.4나 3.5를 쓰는 경향이 있다. 따라서 드라이버는 3.3·3.4·3.5를 모두 구현해야 한다. 버전 설정이 `auto`면 Arida처럼 3.3 → 3.4 → 3.5 순으로 시도하고, 성공한 버전을 기기 필드에 저장한다 ([Arida client.lua](https://github.com/drdecibel/smartthings-arida-tuya-edge/blob/main/src/tuya/client.lua)). 3.1은 CONTROL 명령만 암호화하고 상태 조회는 키 없이도 되는 구버전이다. PV28-CW가 3.1을 쓴다는 증거가 없으므로 나중으로 미룬다.

**프레임 형식.** 55AA 프레임(3.1~3.4)과 6699 프레임(3.5)의 구조는 다음과 같다 ([tinytuya message_helper.py](https://github.com/jasonacox/tinytuya/blob/c0eb2ee3594f44bd43587fd6390676eca9d312f8/tinytuya/core/message_helper.py#L28-L67); [Tuya lan_protocol.h](https://github.com/tuya/tuya-iotos-embeded-sdk-wifi-ble-bk7231n/blob/master/sdk/include/lan_protocol.h#L71-L101); [tinytuya Discussion #260](https://github.com/jasonacox/tinytuya/discussions/260)).

| 순서 | 55AA (3.1~3.4) | 6699 (3.5) |
|---|---|---|
| 헤더 | 16바이트: `0x000055AA`, seqno, cmd, length | 18바이트: `0x00006699`, `0x0000`, seqno, cmd, length |
| 본문 앞 | 4바이트 return code (기기→클라이언트 방향만) | 12바이트 IV |
| 본문 | 페이로드 | GCM 암호문 |
| 무결성 | CRC32 (3.3까지) 또는 32바이트 HMAC-SHA256 (3.4) | 16바이트 GCM 태그 |
| 끝 | `0x0000AA55` | `0x00009966` |
| length 범위 | 헤더 뒤 모든 바이트, 접미사 포함 | IV부터 태그까지, 접미사 제외 |

6699 프레임에서는 접두사 뒤 14바이트가 GCM의 AAD(추가 인증 데이터)다. Lua 5.3에서는 `string.pack(">I4I4I4I4", ...)`과 `string.pack(">I4I2I4I4I4", ...)`로 두 헤더를 바로 만들 수 있다. 수신 측은 먼저 4바이트를 확인한다. 55AA면 `16 + length`, 6699면 `22 + length`만큼 읽는다. 둘 다 아니면 한 바이트씩 버리며 재동기화한다. tinytuya처럼 페이로드가 1440바이트를 넘으면 스트림이 어긋난 것으로 본다 ([tinytuya const.py](https://github.com/jasonacox/tinytuya/blob/c0eb2ee3594f44bd43587fd6390676eca9d312f8/tinytuya/core/const.py#L19)).

**명령 코드.** 3.3에서는 DP_QUERY(0x0a)와 CONTROL(0x07)을 쓴다. 3.4/3.5에서는 페이로드가 `{}`인 DP_QUERY_NEW(0x10)와 CONTROL_NEW(0x0d)를 쓴다. HEART_BEAT(0x09)는 모든 버전에 공통이다. 기기가 스스로 보내는 상태 변경은 STATUS(0x08)로 비동기 도착한다 ([tinytuya payload_dict](https://github.com/jasonacox/tinytuya/blob/c0eb2ee3594f44bd43587fd6390676eca9d312f8/tinytuya/core/XenonDevice.py#L145-L235)). 15바이트 버전 헤더는 `"3.3"`(또는 `"3.4"`/`"3.5"`) 뒤에 0x00 12개를 붙인 것이다. DP_QUERY, DP_QUERY_NEW, UPDATEDPS, HEART_BEAT, 협상 명령을 뺀 모든 명령 앞에 붙는다. 3.3에서는 암호문 바깥에, 3.4/3.5에서는 암호문 안에 들어간다 ([tinytuya header.py](https://github.com/jasonacox/tinytuya/blob/c0eb2ee3594f44bd43587fd6390676eca9d312f8/tinytuya/core/header.py#L30)).

**세션 키 협상(3.4/3.5).** TCP 연결마다 다음 순서로 세션 키를 새로 만든다 ([tinytuya XenonDevice.py L893-L969](https://github.com/jasonacox/tinytuya/blob/c0eb2ee3594f44bd43587fd6390676eca9d312f8/tinytuya/core/XenonDevice.py#L893-L969); [ST-SmartHome tuya35.lua](https://github.com/ST-SmartHome/smartthings-drivers/blob/main/skyfan-driver/src/tuya35.lua)).

1. 클라이언트가 16바이트 난수 `local_nonce`를 cmd 3으로 보낸다.
2. 기기가 cmd 4로 `remote_nonce ‖ HMAC-SHA256(local_key, local_nonce)`를 돌려준다.
3. 클라이언트가 HMAC을 검증한 뒤 cmd 5로 `HMAC-SHA256(local_key, remote_nonce)`를 보낸다.
4. 세션 키를 계산한다.
   - 3.4: `AES-ECB(local_key, local_nonce ⊕ remote_nonce)`
   - 3.5: `(local_nonce ⊕ remote_nonce) ⊕ AES-ECB(local_key, local_nonce[0:12] ‖ 00000002)`

세션 키의 첫 바이트가 0x00이면 기기가 거부하므로 협상을 다시 해야 한다 ([Discussion #260](https://github.com/jasonacox/tinytuya/discussions/260)).

**JSON 페이로드.** JSON은 공백 없이 직접 직렬화해야 한다. tinytuya는 공백을 지우지 않으면 기기가 응답하지 않는다며 페이로드의 공백을 모두 제거하고, DP 키는 문자열로 보낸다 ([tinytuya generate_payload](https://github.com/jasonacox/tinytuya/blob/c0eb2ee3594f44bd43587fd6390676eca9d312f8/tinytuya/core/XenonDevice.py#L1319-L1369)). 3.3 제어 페이로드는 `{"devId","uid","t","dps"}` 형태이고 `t`는 epoch 초를 문자열로 넣는다. 3.4/3.5 제어 페이로드는 `{"protocol":5,"t":<int>,"data":{"dps":{...}}}`다. 받을 때는 최상위 `dps`와 `data.dps`를 똑같이 처리한다.

**예외 처리.** 응답에 `"data unvalid"`가 오면 22자 ID를 가진 "device22" 변종이다. 이 경우 CONTROL_NEW에 `{"dps":{"1":null}}` 같은 페이로드를 실어 조회한다. 다만 tuya-local은 이 자동 감지가 진짜 3.3 기기를 device22로 잘못 판단해 업데이트가 끊기는 사례가 있어 별도 버전 "3.22"를 두었다 ([tuya-local README](https://github.com/make-all/tuya-local/blob/main/README.md)). 3.5 기기는 보낸 seqno가 아니라 자체적으로 증가하는 seqno로 응답한다. 그러므로 응답은 seqno가 아니라 cmd로 짝지어야 한다 ([tinytuya XenonDevice.py L1034-L1044](https://github.com/jasonacox/tinytuya/blob/c0eb2ee3594f44bd43587fd6390676eca9d312f8/tinytuya/core/XenonDevice.py#L1034-L1044)).

### 네이티브 암호화를 두고 자료가 엇갈리지만, 1차 소스는 "있다"고 말한다

필요한 암호 요소는 버전마다 다르다. 3.3은 AES-128-ECB 암·복호화와 CRC32, 3.4는 여기에 HMAC-SHA256, 3.5는 AES 암호화(GCM = CTR + GHASH)가 필요하다. 3.5는 복호화 방향의 AES 블록 연산이 필요 없다. 허브가 이것들을 네이티브로 제공하는지를 두고 자료가 정면으로 엇갈린다.

**"없다"는 쪽.**

- SmartThings 직원 nayelyz는 2021년 11월, Lua 라이브러리에 AES가 없고 서드파티 코드는 순수 Lua여야 한다고 답했다 ([SmartThings Community: LUA Aes library?](https://community.smartthings.com/t/lua-aes-library/234457)).
- 2026년 Tuya 드라이버 작성자 두 명도 같은 취지로 적었다. 한 명은 Edge 샌드박스에 네이티브 암호화가 없다고 했고 ([Skyfan 스레드](https://community.smartthings.com/t/st-edge-lan-driver-ventair-skyfan-dc-ceiling-fan/310702)), 다른 한 명은 SmartThings Edge 런타임이 AES도 SHA-256도 제공하지 않는다고 소스 주석에 남겼다 ([Arida crypto.lua](https://github.com/drdecibel/smartthings-arida-tuya-edge/blob/main/src/tuya/crypto.lua)).
- 공개 Edge 레퍼런스 색인에는 security 모듈이 없다 ([Edge driver reference](https://developer.smartthings.com/docs/edge-device-drivers/)). 해당 문서가 있을 법한 주소 `security.html`은 404를 반환한다 ([developer.smartthings.com](https://developer.smartthings.com/docs/edge-device-drivers/security.html)).
- APIv13~APIv21 릴리스 노트에도 관련 언급이 없다 ([SmartThingsEdgeDrivers releases](https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers/releases)).

**"있다"는 쪽.**

- 공식 APIv21 Lua 라이브러리 tarball(허브 0.62.x용, 2026-08-25)에 `st/security.lua`가 들어 있다. 저작권 표기는 2023년이다. 이 모듈은 네이티브 모듈 `_envlibrequire("security")`를 불러 `available_ciphers()`, `encrypt_bytes(data, key, {cipher, padding, iv})`/`decrypt_bytes`, `available_digests()`, `digest(algo, data)`/`hexdigest`, `generate_self_signed_cert`를 노출한다. 파트너 전용이라는 주석은 `get_secret` 계열에만 붙어 있다 ([APIv21 lua_libs tarball](https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers/releases/download/apiv21_62/lua_libs-api_v21_62X.tar.gz)).
- 공식 저장소에서도 쓰인다. Aqara 잠금장치 드라이버는 `cipher = "aes256-ecb"`로 이 API를 호출하고, Sonos 드라이버는 `pcall(require, "st.security")`로 실패에 대비하며 불러온다 ([SmartThingsEdgeDrivers](https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers)).
- 개인 채널로 배포되는 wonjj6768의 MIoT 드라이버 약 215개는 순수 Lua 대안 없이 `security.encrypt_bytes(payload, key, {cipher="aes128-cbc", iv=iv, padding=true})`에 의존한다 ([wonjj6768 libs/miio.lua](https://github.com/wonjj6768/smartthings-miot-edge-driver/blob/main/libs/miio.lua)).

**판단.** 직원의 "없다" 발언은 모듈의 저작권 연도(2023)보다 2년 앞선다. 2026년 작성자들의 진술은 테스트 결과가 아니라, 문서에 없다는 사실에 기댄 단정으로 보인다. 공식 tarball의 코드와 공식 드라이버의 실제 사용은 이보다 강한 1차 증거다. 그러므로 **현재 펌웨어(0.62.x)에 네이티브 AES 진입점이 있다는 것은 사실로 봐야 한다.**

불확실한 점은 세 가지가 남는다.

- **커뮤니티 서명 드라이버에서도 호출이 허용되는가.** wonjj6768이 강한 정황 증거지만, 사용자 동작 보고를 직접 확인하지는 못했다.
- **`"aes128-ecb"`라는 이름이 `available_ciphers()` 목록에 있는가.** `aes256-ecb`와 `aes128-cbc` 사용례로 보면 있을 가능성이 높지만 확인되지 않았다.
- **GCM과 HMAC.** API 문서가 IV를 16바이트로 고정하고 입력이 블록 크기의 배수여야 한다고 하므로 GCM은 없다고 봐야 한다. HMAC 함수도 없다. 다만 `digest`가 `sha256`을 지원하면 HMAC은 몇 줄로 직접 만들 수 있다.

문서화되지 않은 API는 예고 없이 바뀔 수 있다. 구형 펌웨어에서는 "Security functionality is not available on this SmartThings Hub" 오류가 난다는 점도 감안해야 한다.

### 권장 암호 계층: 확인 → 자가 시험 → 폴백

실무 결론은 백엔드 두 개를 같은 인터페이스 뒤에 두는 것이다.

1. 초기화 때 `pcall(require, "st.security")`로 모듈을 불러 본다.
2. `available_ciphers()`와 `available_digests()` 결과를 로그로 남긴다.
3. 알려진 벡터로 `aes128-ecb`를 자가 시험한다. 결과가 **비트 단위로 일치할 때만** 네이티브 경로를 켜고, 그 밖의 경우는 순수 Lua AES를 쓴다.

패딩은 `padding=false`로 두고 PKCS#7을 Lua에서 직접 처리해야 두 백엔드의 동작이 같아진다.

```lua
-- src/tuya/crypto.lua (개념 스케치)
local log = require "log"
local function unhex(h) return (h:gsub("..", function(x) return string.char(tonumber(x, 16)) end)) end
-- 자가 시험 벡터: AES-128-ECB(key="0123456789abcdef", pt=0x10 x16)
-- 기대값은 조사자가 계산한 것이므로 tinytuya/파이썬으로 재확인한 뒤 쓸 것
local TEST_KEY, TEST_PT = "0123456789abcdef", string.rep("\x10", 16)
local TEST_CT = unhex("377222e061a924c591cd9c27ea163ed4")

local M = { backend = "pure" }
local ok, security = pcall(require, "st.security")
if ok and security then
  local okc, ciphers = pcall(security.available_ciphers)
  local okd, digests = pcall(security.available_digests)
  log.info_with({ hub_logs = true }, string.format("st.security ciphers=%s digests=%s",
    (okc and type(ciphers) == "table") and table.concat(ciphers, ",") or "n/a",
    (okd and type(digests) == "table") and table.concat(digests, ",") or "n/a"))
  local oke, out = pcall(security.encrypt_bytes, TEST_PT, TEST_KEY,
                         { cipher = "aes128-ecb", padding = false })
  if oke and out == TEST_CT then M.backend = "native" end
end
return M
```

GCM에는 쓸 만한 요령이 하나 있다(추론). GCM의 CTR 키스트림과 해시 키 H = AES_K(0¹²⁸)는 모두 AES-ECB 블록 암호화다. 그러므로 네이티브 ECB가 있으면 이 부분은 네이티브로 돌리고, GF(2¹²⁸) 곱셈인 GHASH만 순수 Lua로 두면 된다. 3.5 세션 키 계산도 ECB 한 블록이다. HMAC-SHA256은 `available_digests()`에 `sha256`이 있으면 `digest` 위에 표준 HMAC 구성을 얹고, 없으면 `sha2.lua`를 쓴다. CRC32는 Lua 5.3 네이티브 비트 연산으로 만든 256항목 테이블이면 충분하다.

순수 Lua 경로에는 실제로 성능 함정이 있다.

- 원본 lua-lockbox는 Lua 5.3에서 `bit` 모듈이 없어 동작하지 않고, GCM도 없다 ([lua-lockbox](https://github.com/somesocks/lua-lockbox)).
- Arida 작성자에 따르면 lockbox의 AES는 16바이트 블록마다 키를 다시 확장해 PC에서도 블록당 약 2 ms가 걸린다. 그래서 Arida는 키를 한 번만 확장하는 T-table AES를 따로 썼다 ([Arida gcm.lua](https://github.com/drdecibel/smartthings-arida-tuya-edge/blob/main/src/tuya/gcm.lua)).
- ST-SmartHome 작성자는 lockbox의 SHA-256이 PC에서 HMAC 한 번에 약 14 ms 걸리고 세션마다 3번 필요하다고 지적했다. 그래서 약 50배 빠른 구현으로 바꿨다 ([ST-SmartHome tuya35.lua](https://github.com/ST-SmartHome/smartthings-drivers/blob/main/skyfan-driver/src/tuya35.lua)).

허브 하드웨어에서 측정한 수치는 공개된 것이 없다. 다만 PV28-CW 트래픽은 30초에 수백 바이트 수준이라, 위 최적화만 적용하면 순수 Lua로도 부담이 크지 않다(추론).

## 단일 연결 제약 때문에 기본값은 '30초마다 연결하고 닫기'다

Tuya 기기의 연결 수 제약이 설계 전체를 좌우한다.

- tinytuya와 tuyapi는 "TCP 연결은 한 번에 하나"라며 폰 앱을 닫으라고 안내한다 ([tinytuya README](https://github.com/jasonacox/tinytuya/blob/c0eb2ee3594f44bd43587fd6390676eca9d312f8/README.md); [tuyapi README](https://github.com/codetheweb/tuyapi/blob/master/README.md)).
- Arida는 기기가 연결을 "몇 개까지"는 받으며 Smart Life 앱과도 함께 동작한다고 적었다 ([Arida README](https://github.com/drdecibel/smartthings-arida-tuya-edge)).
- Hunter Pacific 스레드는 HA 같은 다른 로컬 통합이 같은 팬에 붙으면 드라이버와 충돌한다고 경고한다 ([SmartThings Community: Hunter Pacific](https://community.smartthings.com/t/st-edge-lan-driver-hunter-pacific-dc-ceiling-fans-tuya-wifi-local-control/311396)).
- PV28-CW의 경우, 2024년 tuya-local 메인테이너는 연결 실패 원인으로 폰 앱이 로컬 세션을 점유했을 가능성을 먼저 의심했다 ([tuya-local issue #2288](https://github.com/make-all/tuya-local/issues/2288)).

즉 Edge 드라이버, HA tuya-local, 디버깅용 tinytuya 가운데 **한 기기에는 로컬 컨트롤러 하나만 붙인다**고 생각해야 한다.

**기본 모드: 주기마다 연결하고 닫기.** Arida 방식을 권한다. 주기마다 연결하고(5초 타임아웃), 3.4/3.5면 세션 키를 협상하고, DP_QUERY(_NEW)를 보낸다. 응답과 그사이에 섞여 들어온 cmd 8 푸시를 모두 반영한 뒤 연결을 끊는다. Arida 작성자는 30초 간격으로 폴링한다면 연결을 붙잡아 둬도 얻는 게 거의 없다고 정리했다 ([Arida client.lua](https://github.com/drdecibel/smartthings-arida-tuya-edge/blob/main/src/tuya/client.lua)). PV28-CW에 이 방식이 더 맞는 이유가 세 가지 더 있다.

- 공기질 값은 천천히 변한다.
- TuyaMCU가 가끔 센서 업데이트 전송을 멈춘다는 보고가 있다 ([Elektroda topic4036569 p.2](https://www.elektroda.com/rtvforum/topic4036569-30.html), 검색 스니펫 기준). 푸시를 기다리기보다 직접 조회하는 편이 견고하다.
- tuyapi README에 따르면 일부 신형 기기는 앱이 열려 있지 않으면 업데이트를 보내지 않는다 ([tuyapi README](https://github.com/codetheweb/tuyapi/blob/master/README.md)).

쓰기는 같은 연결에서 CONTROL(_NEW)을 보낸 뒤 곧바로 다시 조회해 결과를 확인한다. 명령은 기기별로 직렬화하고, Skyfan처럼 "가장 최근 명령이 이긴다" 규칙을 적용한다.

**선택 모드: 지속 연결.** 실시간 푸시가 필요하면 지속 연결을 선택 모드로 둔다 ([tuyapi index.js](https://github.com/codetheweb/tuyapi/blob/4135c835deaa7c94ad0df9dd4c34878cb5eb2916/index.js#L95-L98); [tinytuya Monitor.py](https://github.com/jasonacox/tinytuya/blob/c0eb2ee3594f44bd43587fd6390676eca9d312f8/tinytuya/core/Monitor.py#L181); [WeMo init.lua](https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers/blob/main/drivers/SmartThings/wemo/src/init.lua)).

- `cosock.spawn`으로 수신 루프를 돌리고, HEART_BEAT를 약 10초마다 보낸다. 참고로 tuyapi는 10초, localtuya는 10초, hass-localtuya는 8.3초, tinytuya Monitor는 12초 간격을 쓴다.
- 하트비트 응답이 두 번 빠지거나 읽기가 타임아웃되면 `device:offline()`을 호출하고 소켓을 닫는다.
- 재연결은 WeMo 드라이버처럼 지수 백오프(최대 300초, ±25% 지터)로 하고, 3.4/3.5면 세션 키를 다시 협상한다.
- 이 모드에서도 tinytuya Monitor처럼 30초마다 전체 조회를 함께 돌린다.

tinytuya는 1초보다 빠르게 폴링하면 기기가 연결을 끊거나 리셋할 수 있다고 경고한다 ([tinytuya README](https://github.com/jasonacox/tinytuya/blob/c0eb2ee3594f44bd43587fd6390676eca9d312f8/README.md)). 그래서 폴링 주기의 하한은 10초로 둔다.

**Edge 런타임 제약.** 드라이버는 Lua 5.3 샌드박스에서 돈다. 네이티브 비트 연산과 `string.pack`은 쓸 수 있지만 `io`는 없다 ([APIv21 lua_libs tarball](https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers/releases/download/apiv21_62/lua_libs-api_v21_62X.tar.gz)). 모든 소켓은 `cosock.socket`을 써야 한다. 드라이버 전체가 OS 스레드 하나에서 돌고, 기기마다 코루틴이 하나씩 할당된다 ([SmartThings LAN Edge 가이드](https://developer.smartthings.com/docs/devices/hub-connected/lan)). 이 구조에서 지킬 점은 다음과 같다.

- 허브는 메모리를 아끼려고 모든 기기를 공유 스레드 하나에 몰아넣을 수 있다. 그러면 블로킹 receive가 다른 기기까지 멈추게 하므로 드라이버 템플릿에 `shared_device_thread_enabled = false`를 명시한다.
- `init`은 빨리 반환해야 하므로 긴 루프는 `cosock.spawn`으로 뺀다.
- WeMo 드라이버 주석에 따르면 LAN 드라이버에서는 `init`이 모든 기기에 호출되지 않는 버그가 있다. `added`에서도 초기화를 보장한다 ([WeMo init.lua](https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers/blob/main/drivers/SmartThings/wemo/src/init.lua)).
- 로그는 `print` 대신 `log` 모듈로 남긴다.
- LAN 드라이버는 프로토콜 스택을 직접 들고 다녀 메모리를 많이 쓴다. 허브는 드라이버가 메모리 상한을 넘으면 재시작한다 ([Edge Drivers and Hard Limit](https://community.smartthings.com/t/edge-drivers-and-hard-limit-on-my-v3-hub/267886)). lockbox 전체가 아니라 AES·GCM·SHA-256·CRC32만 가져온다.

**발견과 IP 관리.** 기본은 수동 입력이다. Edge에서는 `bind`가 포트 0만 허용하므로, 기기가 6666/6667 포트로 보내는 브로드캐스트를 받을 수 없다 ([LAN 가이드](https://developer.smartthings.com/docs/devices/hub-connected/lan); [Skyfan 스레드](https://community.smartthings.com/t/st-edge-lan-driver-ventair-skyfan-dc-ceiling-fan/310702)). 3.5 신형 기기의 REQ_DEVINFO 응답도 포트 7000으로 오므로 받지 못할 가능성이 높다(미검증). 그래서 진행 순서는 다음과 같다 ([WeMo try_create_device](https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers/blob/main/drivers/SmartThings/wemo/src/init.lua); [ldeora 스레드](https://community.smartthings.com/t/st-edge-tuya-smart-life-wi-fi-air-purifiers/309519)).

1. discovery 핸들러가 ldeora 드라이버처럼 자리표시자 기기 하나를 만든다. 호출은 `driver:try_create_device{type="LAN", device_network_id=<UUID>, label="PV28-CW", profile="pv28cw-air-monitor", manufacturer="Tuya", model="PV28-CW", vendor_provided_label="PV28-CW"}` 형태다.
2. 사용자가 그 기기의 설정에 IP·Device ID·Local Key를 입력한다.
3. `infoChanged`에서 연결을 시작한다.

가장 단순한 IP 대책은 공유기에서 DHCP 예약을 걸어 두는 것이다. 그래도 IP 변경에 대비하려면 Arida 방식을 쓴다. 연결이 계속 실패하면 허브가 속한 /24 대역의 모든 주소에 TCP 6668로 32개씩 접속해, 해당 기기의 키로 상태를 물어본다. 키가 맞는 기기만 답하므로 Device ID를 안정적인 식별자로 쓸 수 있다 ([Arida README](https://github.com/drdecibel/smartthings-arida-tuya-edge)). 허브 IP 변경은 `lan_info_changed_handler`로 받는다. `config.yml`에는 WeMo처럼 `permissions: lan: {}`와 `discovery: {}`를 넣는다 ([wemo/config.yml](https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers/blob/main/drivers/SmartThings/wemo/config.yml)).

```
pv28cw-tuya-lan/
  config.yml              -- permissions: lan, discovery
  profiles/pv28cw-air-monitor.yml
  src/init.lua            -- Driver 템플릿, lifecycle(init/added/infoChanged/removed), refresh
  src/discovery.lua       -- 자리표시자 LAN 기기 생성
  src/dpmap.lua           -- DP → capability 변환 (PV28-CW 전용 코드는 사실상 여기뿐)
  src/health.lua          -- *HealthConcern 등급 기준, 종합 지표
  src/tuya/frame.lua      -- 55AA/6699 pack/unpack, 재동기화
  src/tuya/v33.lua v34.lua v35.lua  -- 버전별 인코딩, 3.4/3.5 세션 협상
  src/tuya/client.lua     -- 연결 → 협상 → 조회 → 종료, 버전 자동 감지, 명령 큐
  src/tuya/crypto.lua     -- st.security 확인 + 순수 Lua 폴백
  src/tuya/aes.lua gcm.lua sha2.lua crc32.lua   -- MIT 출처 명시
```

공식 가이드는 통신 라이브러리를 SmartThings 안팎 어디서나 돌아가게 만들라고 권한다 ([LAN 가이드](https://developer.smartthings.com/docs/devices/hub-connected/lan)). 그러니 `src/tuya/`는 데스크톱 Lua 5.3에서 tinytuya가 만든 벡터와 tuyalan-sim을 상대로 먼저 시험한 뒤 허브에 올린다. 배포에는 SmartThings CLI 3.0.0(2026-11-04 출시, Node 24.22.1 이상 필요)을 쓴다 ([npm @smartthings/cli](https://www.npmjs.com/package/@smartthings/cli); [smartthings-cli README](https://github.com/SmartThingsCommunity/smartthings-cli/blob/main/README.md)).

1. `edge:drivers:package`로 패키지를 만든다.
2. `edge:channels:create`로 채널을 만든다.
3. `edge:channels:assign`으로 드라이버를 채널에 넣는다.
4. `edge:channels:enroll`로 허브를 채널에 등록한다.
5. `edge:drivers:install`로 허브에 설치한다.

디버깅은 `edge:drivers:logcat`으로, 다른 사람과의 공유는 `edge:channels:invites:create`로 한다.

## 코드보다 먼저: 내 PV28-CW에서 확인할 7단계

PV28-CW에서 가장 큰 불확실성은 개체마다 다른 사실이다. 2024년 issue #2288의 소유자는 앱을 닫고 폰을 모바일 데이터로 바꿔도 로컬 연결에 실패했다. 그 기기는 Tuya 클라우드와의 연결은 유지하면서 포트 스캔에서는 모든 포트가 닫혀 있었다. 소유자는 로컬 제어를 허용하지 않는 다른 펌웨어라고 결론 내렸다 ([tuya-local issue #2288](https://github.com/make-all/tuya-local/issues/2288)). 최근 기기의 6668 포트에서 TLS-PSK 핸드셰이크가 보인다는 보고가 있고 ([Discussion #260](https://github.com/jasonacox/tinytuya/discussions/260)), Tuya가 일부 신규 모듈에서 LAN 프로토콜을 끄기 시작했다는 주장도 한 건 있다 ([Elektroda Q&A](https://www.elektroda.com/qa,http-requests-tuya-devices-control.html)). 둘 다 검증되지 않았지만 같은 방향의 위험이다.

아래 단계는 PC 한 대로 30분 안에 끝나고, 그 결과로 드라이버를 만들지 말지가 정해진다. 준비 사항은 세 가지다. PC를 PV28-CW와 같은 서브넷에 두고, 방화벽에서 UDP 6666/6667/7000과 TCP 6668을 연다. 기기는 USB 전원에 연결한다(배터리만으로는 어떻게 동작하는지 알려진 바가 없다).

| 단계 | 실행 | 확인할 것 | 결과 해석 |
|---|---|---|---|
| 1 | `pip install tinytuya` 후 `python -m tinytuya scan` | IP, `gwId`(= Device ID), **`version`**, `productKey` | 버전에 따라 구현 우선순위가 정해진다. 3.5 신형은 스스로 브로드캐스트하지 않지만, scan은 포트 7000으로 요청도 보낸다 |
| 2 | Smart Life 앱을 완전히 종료하고 TCP 6668 접속 확인 | 포트 열림 여부 | **닫혀 있으면 이 개체에는 로컬 드라이버를 쓸 수 없다**(#2288 사례) |
| 3 | iot.tuya.com에서 클라우드 프로젝트 생성 → 앱 계정을 QR로 연결 → `python -m tinytuya wizard` | 16자 `local_key`, `devices.json`의 DP `mapping`, 제품 ID가 `yrr3eiyiacm31ski`인지 | IoT Core 무료 체험은 1개월이다. 그 뒤 새 키를 받으려면 연장해야 한다. 기기를 제거했다가 다시 등록하면 키가 바뀐다 |
| 4 | iot.tuya.com → 기기 → "Query Things Data Model" | 코드별 `abilityId`(= DP 번호) | DP 107/109 번호 확정 |
| 5 | `tinytuya.Device(ID, IP, KEY, version=<1단계 값>)`로 `status()`를 30초 간격 10회 | DP 21/22 원시값, DP 102와 앱의 PM1.0 값 일치 여부, DP 5/6/7/17/104 존재 여부, 값 갱신 여부 | 값이 멈추면 MCU 정지 이슈이므로 폴링 설계로 대응한다. 마지막으로 `set_value(31, "f")` 후 DP 18이 화씨로 바뀌는지 보고 `"c"`로 되돌린다 |
| 6 | tinytuya 지속 연결을 열어 둔 채 Smart Life 앱이나 두 번째 tinytuya로 접속 | 어느 쪽이 거부되거나 끊기는지 | 지속 연결 모드를 쓸지, 연결 후 닫기만 쓸지 결정 |
| 7 | 허브에 `st.security` 확인만 하는 최소 드라이버를 설치하고 `edge:drivers:logcat` 실행 | `available_ciphers()`, `available_digests()`, aes128-ecb 자가 시험 결과 | 네이티브 백엔드를 쓸지 결정. 결과를 공개하면 커뮤니티의 엇갈린 주장도 정리된다 |

1~3단계의 명령과 절차는 tinytuya README에 나온 그대로다 ([tinytuya README](https://github.com/jasonacox/tinytuya/blob/c0eb2ee3594f44bd43587fd6390676eca9d312f8/README.md)). 4단계의 데이터 모델 조회 결과 형식은 PV28-COW 이슈에 올라온 예시와 같다 ([tuya-local issue #4406](https://github.com/make-all/tuya-local/issues/4406)).

2단계에서 포트가 닫혀 있다면 HA tuya-local을 포함한 모든 로컬 경로가 막힌다. 남는 길은 둘이다.

- **클라우드.** 공식 C2C 연동을 쓰거나, HA 공식 Tuya 클라우드 통합에 Matter 브리지를 붙인다.
- **OpenBeken 재플래시.** 한 PV28-CW 소유자는 Cloudcutter로 UART 없이 플래시에 성공했다 ([Elektroda topic4036569](https://www.elektroda.com/rtvforum/topic4036569.html), 검색 스니펫 기준). 하지만 현재 생산분 펌웨어도 Cloudcutter에 취약한지는 알 수 없다. OpenBeken 장치 DB와 Cloudcutter 프로필 목록 어디에도 PV28 템플릿이 없다 ([OpenBeken devices.json](https://openbekeniot.github.io/webapp/devices.json); [tuya-cloudcutter devices](https://tuya-cloudcutter.github.io/api/devices.json)). 펌웨어를 바꾸면 Tuya 앱 연동도 사라진다.

## Conclusion

이번 조사로 문제의 무게중심이 옮겨 갔다. 2024년까지 "Tuya Wi-Fi 로컬 Edge 드라이버"는 암호화 라이브러리부터 직접 만들어야 하는 연구 과제였다. 2026년 11월 현재는 MIT 코덱과 tinytuya 기준 벡터가 있어 프로토콜은 사실상 조립하면 되는 부품이 됐다. PV28-CW만을 위한 작업은 DP 9개 변환 표와 프로필 정도로 줄었다. 대신 성패는 개체 펌웨어에 달려 있다. 6668 포트가 열려 있는지, 어느 버전을 쓰는지, 다른 로컬 클라이언트와 연결 슬롯을 나눌 수 있는지다. 세 가지 모두 tinytuya로 30분이면 확인된다. 그러니 첫 단계는 "드라이버 찾기"가 아니라 "내 기기 진단"이다.

두 번째 시사점은 `st.security`다. 허브에서 확인해 보니 커뮤니티 드라이버에서도 `aes128-ecb`가 동작한다면, Tuya 드라이버들은 순수 Lua AES를 걷어 내고 메모리와 CPU를 아낄 수 있다. 2021년 직원 발언 이후 굳어진 "Edge에는 암호화가 없다"는 통념도 바로잡힌다. 다만 문서화되지 않은 API이므로 어느 경우든 순수 Lua 폴백은 남겨 둬야 한다. 마지막으로, 한국 MIoT 커뮤니티가 Tuya 드라이버를 예고했으니 기다리는 것도 선택지다. 하지만 그 저장소들에는 라이선스가 없어 포크의 기반으로 삼을 수 없다. 직접 만든다면 Arida를 GPL로 포크할지, MIT 원본으로 조립할지부터 정해야 한다. 그 선택이 나중에 드라이버를 어디까지 공유할 수 있는지를 결정한다.
