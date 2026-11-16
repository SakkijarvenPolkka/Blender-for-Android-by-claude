# Blender for Android (비공식 포팅)

> 🤖 **이 프로젝트는 순수하게 Claude Opus 5.5만을 활용해 만든 프로젝트입니다.**
> 포팅 설계, Android 백엔드·앱 코드, 의존성 크로스 컴파일, Blender 패치, 빌드 스크립트·CI, 테스트, 문서까지
> 모두 Anthropic의 **Claude Opus 5.5**가 [Claude Code](https://claude.ai/code)에서 작성했습니다.

[Blender](https://www.blender.org) **5.2.2** (2026년 9월 기준 최신 안정 버전)를 Android(arm64)로 포팅하는 프로젝트입니다.
**최소 사양은 Galaxy S22 시리즈**(Snapdragon 8 Gen 1 / Exynos 2200, Android 12 이상, Vulkan 1.2 이상)이고,
**권장 기기는 Galaxy Z Fold 8 Ultra**입니다 (아래 "Galaxy Z Fold 8 Ultra" 참고).
GPU 드라이버가 Vulkan 1.2를 지원해야 하므로 기기를 최신 One UI로 업데이트해 두세요.

> 이 프로젝트는 Blender 재단과 관련이 없는 **비공식** 포팅입니다. "Blender"는 Blender 재단의 상표입니다.
> 코드는 Blender와 같은 GPL 라이선스를 따릅니다.

*English summary: unofficial port of Blender 5.2.2 to Android arm64 (minimum: Galaxy S22 / Android 12 /
Vulkan, recommended: Galaxy Z Fold 8 Ultra). The native UI runs on an SDL3-based GHOST back-end with the
Vulkan GPU back-end, the Python 3.13 standard library is linked statically, and all dependencies are
cross-compiled from source. Optional components (USD's Python modules, Python packages with pip) can be
installed after the APK. See "Build" below. This project was made purely with Claude Opus 5.5 (Claude Code).*
*Download: [Blender-5.2.2-android-arm64-v8a.apk](https://github.com/SakkijarvenPolkka/Blender-for-Android-by-claude/releases/latest/download/Blender-5.2.2-android-arm64-v8a.apk) ([all releases](https://github.com/SakkijarvenPolkka/Blender-for-Android-by-claude/releases)).*

---

## 다운로드

[![최신 릴리스](https://img.shields.io/github/v/release/SakkijarvenPolkka/Blender-for-Android-by-claude?label=%EC%B5%9C%EC%8B%A0%20%EB%A6%B4%EB%A6%AC%EC%8A%A4&logo=android)](https://github.com/SakkijarvenPolkka/Blender-for-Android-by-claude/releases/latest)

### **[⬇ Blender-5.2.2-android-arm64-v8a.apk 다운로드 (최신 빌드, 약 230MB)](https://github.com/SakkijarvenPolkka/Blender-for-Android-by-claude/releases/latest/download/Blender-5.2.2-android-arm64-v8a.apk)**

[모든 릴리스](https://github.com/SakkijarvenPolkka/Blender-for-Android-by-claude/releases) — 기본 브랜치의 CI 빌드가 성공할 때마다(QEMU 테스트 통과 후) APK와 추가 구성 요소가
릴리스로 자동 게시됩니다.

**설치 방법**

1. 휴대폰 브라우저에서 위 링크를 눌러 APK를 받고, 다운로드 알림이나 *내 파일* 앱에서 엽니다.
   (PC에서는 `adb install -r Blender-5.2.2-android-arm64-v8a.apk`)
2. "출처를 알 수 없는 앱" 설치를 묻는 경우 브라우저(또는 *내 파일*)에 설치 권한을 허용합니다.
   Play 프로텍트 경고가 나오면 *세부정보 → 무시하고 설치*를 선택합니다 (Play 스토어 밖에서 배포되는 앱이기 때문).
3. 첫 실행 시 Blender 데이터(약 210MB)를 설치합니다. 파일 접근 권한을 허용하면 기기의 모든 폴더에서 `.blend`
   파일을 열고 저장할 수 있습니다.
4. 필요하면 **편집 → Android Components**에서 추가 구성 요소(USD Python 모듈, Python 패키지)를 설치합니다
   (아래 "추가 구성 요소").

> **업데이트:** 새 빌드를 설치할 때 "기존 패키지와 충돌" 오류가 나면 서명 키가 다른 빌드입니다(릴리스 서명 키가
> 설정되기 전의 CI 빌드는 빌드마다 다른 키로 서명됨). 기존 앱을 삭제한 뒤 설치하세요. 내부 저장소의 Blender
> 설정·추가 구성 요소는 삭제되며, 기기 저장소에 저장한 `.blend` 파일은 유지됩니다.

---

## 현재 상태

| 항목 | 상태 |
| --- | --- |
| 의존성 약 75개 크로스 컴파일 (Python 3.13, OIIO, OCIO, OpenEXR, TBB, SDL3, OpenSubdiv, FFmpeg, OpenVDB, USD, Embree, OIDN, LLVM·Clang, OSL …) | ✅ 빌드 확인 |
| Blender 5.2.2 → `libblender.so` (arm64-v8a, API 31, 16KB 페이지 정렬) | ✅ 빌드·링크 확인 |
| Android bionic 위에서 백그라운드 모드 실행 (QEMU, 아래 "검증") | ✅ 스모크 테스트 통과 |
| NumPy 2.3, requests 등 Python 패키지, 확장(Extensions) 온라인 설치 | ✅ QEMU에서 확인 |
| Claude 연동 (MCP 서버: Claude Code / Claude 앱에서 Blender 제어) | ✅ QEMU에서 종단 간 테스트 통과 |
| FFmpeg 동영상, 오디오 파일, 모션 트래킹, 볼륨(OpenVDB), Alembic, USD·MaterialX, Cycles Embree·OIDN 등 | ✅ QEMU에서 확인 |
| Cycles OSL(Open Shading Language, LLVM JIT) — 스크립트 노드, OSL 셰이딩 시스템 | ✅ QEMU에서 확인 |
| APK 설치 후 추가 설치: USD Python 모듈(`pxr`) 구성 요소, pip로 Python 패키지 설치 | ✅ QEMU에서 확인 |
| APK 패키징 (Gradle, 데이터 자동 설치, 터치 툴바) | ✅ 약 230MB APK 생성 확인 |
| 실제 기기에서 UI 실행 (SDL3 창, Vulkan, 터치 입력) | ⚠️ 사용자 기기에서 Vulkan으로 실행 보고됨 — 기기별 GPU 드라이버 호환성은 계속 확인 필요 |

### 검증

실기기 없이 확인할 수 있는 부분은 빌드 머신에서 검증합니다. `tests/qemu/run_blender.sh`는 빌드된
`libblender.so`를 QEMU user-mode 에뮬레이션과 Android 14 에뮬레이터 이미지에서 추출한 bionic
(`linker64`, `libc.so` …)으로 실행하고, 앱과 같은 방식(`SDL_main` 호출)으로 Blender를 시작합니다.
CI에서도 매 빌드마다 실행됩니다.

- `blender --version` → `Blender 5.2.2 LTS`
- 스모크 테스트 (`tests/qemu/smoke_test.py`, 백그라운드 모드) — **모두 통과**:
  - Python 표준 라이브러리 확장 모듈(`ssl`/OpenSSL 3.5, `hashlib`, `sqlite3`, `lzma`, `bz2`, `decimal`, `ctypes`),
    NumPy(`foreach_get`), requests
  - OpenSubdiv 서브디비전, Boolean(Manifold/Exact), .blend 저장·불러오기
  - 입출력: OBJ/PLY/STL, FBX, glTF(Draco·meshoptimizer 압축 내보내기·가져오기), Alembic, USD(usdc/usda,
    MaterialX 셰이딩 네트워크) 내보내기·가져오기, OpenVDB(.vdb 저장·불러오기, 메시 → 볼륨)
  - Cycles CPU 렌더링 → PNG/EXR/JPEG/WebP, Embree, 경로 가이딩 + OpenImageDenoise 디노이즈, 볼륨 렌더링,
    OSL(스크립트 노드를 런타임에 컴파일·JIT 실행)
  - FFmpeg: H.264/AAC(MP4), H.265, VP9/Opus(WebM), AV1/MP3(MKV) 동영상 렌더링과 무비 클립 불러오기
  - 오디오 파일 쓰기·읽기(WAV, FLAC, Ogg Vorbis, MP3), Rubberband 시간 늘이기
  - OpenImageIO 이미지 읽기, OpenColorIO(AgX)
- Python 실행 파일(`sys.executable`, 격리 모드 `-I`): 표준 라이브러리·NumPy·requests 로드, 확장 플랫폼 CLI로
  extensions.blender.org 목록 동기화(HTTPS) 확인
- MCP 서버 종단 간 테스트 (`tests/qemu/mcp_test.py`): 최신(2026-07-28)·구버전(2025-06-18) 프로토콜,
  `execute_python`(NumPy로 메시 생성), 씬·오브젝트 정보, Cycles 렌더 이미지 반환, .blend 저장 — **통과**
- MCP 서버 단위 테스트 (`tests/mcp/test_mcp_host.py`, `test_mcp_addon.py`, 빌드 머신의 Python): 토큰 인증(헤더·URL 경로),
  Origin 검사, 읽지 않은 요청 본문의 연결 종료, 터널·프록시를 거친 긴 도구 호출의 백그라운드 실행과
  `get_tool_result`, Cloudflare 터널 관리(주소 인식, 연결·주소 확인, 다시 시작, 요청 제한, 토큰 가리기, 전용 설정
  디렉터리, 남은 프로세스 정리), 패널·설정 코드 — **통과**. Android용 `cloudflared`는 QEMU에서 실행 확인
  (`--version`, 실제 터널 연결은 실기기에서), 큰 이미지의 JPEG 변환은 스모크 테스트에서 확인
- 추가 구성 요소 (`tests/qemu/smoke_test.py`): 빌드된 USD Python 모듈 패키지를 파일에서 설치한 뒤
  `from pxr import Usd, UsdGeom`으로 스테이지 생성·저장, Blender의 USD 내보내기 결과 읽기 — **통과**
- GPU 백엔드 설정 (`tests/qemu/gpu_backend_test.py`): 기본 설정·RNA 기본값이 Vulkan이고 OpenGL은 선택할 수 없는지,
  OpenGL·Metal·빈 값이 저장된 설정 파일(빌드 24 이하·데스크톱 Blender·Blender 3.4의 설정, 저장된 `userpref.blend`를
  `tests/qemu/userpref_gpu_backend.py`로 바꿔 재현)을 시작할 때와 다시 불러올 때, "Load Factory Settings" 후에도
  Vulkan인지 확인

GPU(Vulkan) 경로와 터치·펜 입력은 에뮬레이션으로 확인할 수 없어 실기기 테스트가 필요합니다.

실기기에서 문제가 있으면 `adb logcat -s Blender SDL BlenderLauncher` 로그와 함께 이슈를 남겨 주세요.

### 지원 기능

- **UI / 3D 뷰포트**: Vulkan 백엔드 (Workbench, EEVEE)
- **렌더링**: Cycles (CPU, ARM NEON) — Embree 레이 트레이싱, 경로 가이딩(OpenPGL), AI 디노이즈(OpenImageDenoise),
  **OSL**(Open Shading Language: 스크립트 노드, OSL 셰이딩 시스템, LLVM JIT), EEVEE
- **Python**: CPython 3.13 (표준 라이브러리 + `ssl`, `sqlite3`, `ctypes` 등), 공식 Blender와 같은 번들 패키지:
  **NumPy 2.3**, requests, certifi, cattrs, autopep8 등 / `aud`(오디오) 모듈
- **확장(Extensions)**: extensions.blender.org에서 애드온 검색·설치 (환경설정 → 시스템 → 네트워크에서 온라인 접근 허용),
  원격 에셋 라이브러리·온라인 Essentials
- **Claude 연동**: 내장 MCP 서버 애드온 — Claude Code나 Claude 앱이 Blender Python API를 사용,
  Claude 앱 커넥터용 HTTPS 주소는 내장 Cloudflare 터널로 (아래 참고)
- **입출력**: .blend, OBJ, PLY, STL, FBX, glTF/GLB(Draco·meshoptimizer 압축), Alembic, USD(MaterialX), SVG,
  Grease Pencil PDF / 이미지(PNG, JPEG, EXR, TIFF, WebP, JPEG2000 …)
- **동영상 (FFmpeg)**: 공식 릴리스와 같은 코덱 — H.264(x264), H.265(x265), VP9, AV1, Theora / AAC, Opus, Vorbis,
  MP3, FLAC. 애니메이션을 동영상으로 렌더링, 동영상 편집기(VSE), 동영상 클립 불러오기
- **모션 트래킹**: 동영상 클립 트래킹·카메라 솔브 (libmv, Ceres)
- **볼륨**: OpenVDB/NanoVDB — .vdb 불러오기·저장, 메시 ↔ 볼륨, Cycles 볼륨 렌더링
- **모델링**: OpenSubdiv, Boolean(Manifold/Exact), Remesh, QuadriFlow, 물리(Bullet), 유체(Mantaflow), 오션
- **텍스트**: HarfBuzz·FriBidi (복잡한 문자·오른쪽에서 왼쪽으로 쓰는 문자)
- **오디오**: SDL3 (AAudio / OpenSL ES), 오디오 파일 읽기·쓰기 (libsndfile, FFmpeg), 사운드 스트립 속도·피치(Rubberband)
- **파일 열기**: 파일 관리자에서 `.blend` 파일 열기 지원

- **추가 구성 요소 (APK 설치 후 설치)**: USD Python 모듈(`from pxr import Usd`), pip로 Python 패키지 설치
  (아래 "추가 구성 요소" 참고)

### 아직 지원하지 않는 기능

| 기능 | 이유 |
| --- | --- |
| Hydra 렌더 엔진 (USD Storm) | Storm은 OpenGL 전용 (Android는 Vulkan) |
| Cycles GPU 렌더링 | 모바일 GPU(Adreno, Xclipse)용 Cycles 백엔드가 없음 — CPU(NEON)로 렌더링 |
| OpenXR (VR) | 휴대폰에는 해당 없음 |
| 여러 개의 창 | 환경설정·파일 브라우저·렌더 결과는 메인 창 안에서 열림 |
| glibc용 네이티브 wheel을 포함한 확장·패키지 | Android용(`android_*_arm64_v8a`) wheel이 있거나 순수 Python 패키지는 pip로 설치 가능 |

---

## Galaxy Z Fold 8 Ultra

권장 기기입니다. 앱은 폴드 기기에 맞춰 다음을 지원합니다.

- **접기/펼치기**: 커버 화면 ↔ 메인 화면 전환 시 앱을 다시 시작하지 않고 창 크기와 DPI만 바뀝니다
  (`screenSize`/`smallestScreenSize`/`screenLayout`/`density` 구성 변경을 직접 처리, 작업 중인 파일 유지).
  UI 배율은 화면 밀도에 맞게 자동으로 조정됩니다.
- **멀티 윈도우·팝업 창·DeX**: 크기 조절 가능한 액티비티, 분할 화면에서 Claude 앱과 나란히 사용 가능.
- **성능**: OSL, OpenImageDenoise, Embree 등 CPU 기능을 모두 포함해 빌드했으며, 16KB 메모리 페이지를 사용하는
  최신 Android 커널에서도 실행되도록 모든 네이티브 라이브러리를 16KB 정렬로 링크합니다.
- 추가로 필요한 기능은 앱 설치 후 **편집 → Android Components**에서 설치합니다 (아래 참고).

---

## 추가 구성 요소 (APK 설치 후 설치)

APK에 포함하지 않은 기능은 앱을 설치한 뒤 Blender 안에서 추가로 설치합니다. **편집(Edit) → Android Components**
(또는 환경설정 → 애드온 → Android Components)을 엽니다. 다운로드하려면 *환경설정 → 시스템 → 네트워크 →
온라인 접근 허용*을 켜세요.

| 구성 요소 | 내용 | 설치 방법 |
| --- | --- | --- |
| **USD Python Modules** (`usd-python`) | USD의 Python API — `from pxr import Usd, UsdGeom, Sdf, UsdShade …` (USD 26.03, Blender에 내장된 USD와 같은 라이브러리 사용). 다운로드 약 13MB, 설치 후 약 70MB | **Check for Components**(새로 고침) → **Install**. 또는 릴리스/CI 아티팩트의 `.zip`을 받아 **Install Component from File** |
| **Python 패키지** (pip) | PyPI의 순수 Python 패키지와 Android용 wheel이 있는 패키지 (예: `networkx sympy`) | 패키지 이름 입력 → **Install** |

- 구성 요소는 사용자 데이터 폴더(`…/datafiles/android_components`)에 설치되어 앱을 업데이트해도 유지되고,
  시작할 때 Python 경로에 추가됩니다. 목록에서 **Remove**로 삭제합니다.
- 네이티브 코드가 들어 있는 구성 요소는 **같은 빌드의 앱**(`libblender.so`)에 맞춰 빌드됩니다. 빌드 식별자(ABI,
  애드온 화면 아래쪽에 표시)가 다르면 설치를 거부하므로 앱과 같은 릴리스의 파일을 사용하세요. 앱은 자신이 게시된
  릴리스(예: `v5.2.2-android.1-build.17`)에서 `components.json`을 받아 설치할 구성 요소를 찾습니다.
- Claude(MCP)나 스크립트에서도 설치할 수 있습니다:
  ```python
  import android_components
  android_components.available(refresh=True)    # 이 빌드용 구성 요소 목록
  android_components.install("usd-python")      # 다운로드·설치 (완료까지 대기)
  android_components.pip_install(["networkx"])  # Python 패키지
  from pxr import Usd
  ```

---

## 사용법 (입력 방식)

| 입력 | 동작 |
| --- | --- |
| 한 손가락 탭 | 클릭 |
| 한 손가락 드래그 | 왼쪽 버튼 드래그 (선택, 슬라이더, 도구 사용) |
| 길게 누르기 | 오른쪽 클릭 (컨텍스트 메뉴) |
| 두 손가락 탭 | 오른쪽 클릭 |
| 두 손가락 드래그 | 3D 뷰 회전(orbit), 2D 에디터에서는 이동(pan) |
| 핀치 | 확대/축소 |
| 세 손가락 드래그 | 3D 뷰 이동(pan) |
| S Pen | 필압·기울기 지원, 사이드 버튼 = 오른쪽 클릭 |
| 마우스/키보드 (Samsung DeX, 블루투스, USB) | 데스크톱과 동일 |
| 뒤로 가기 | Esc |

화면 위쪽의 **떠 있는 툴바**: ⌨ 가상 키보드(단축키 입력용), Esc, Tab, Ctrl/Shift/Alt(토글), 실행 취소/다시 실행,
Del, 뷰(앞/옆/위/카메라/원근 전환/선택 항목 보기). 왼쪽 ☰ 손잡이로 이동(드래그)하거나 접을(탭) 수 있습니다.

- 첫 실행 시 Blender 데이터(약 210MB)를 내부 저장소에 설치합니다 (업데이트 후에도 한 번).
  설치 후 앱 전체 용량은 약 800MB입니다 (추가 구성 요소 제외).
- "모든 파일 접근" 권한을 허용하면 기기의 모든 폴더에서 .blend 파일을 열고 저장할 수 있습니다.
- UI 크기는 Blender의 *환경설정 → 인터페이스 → 해상도 배율*로 조절합니다.
- 앱이 백그라운드로 전환될 때 자동 저장(복구 파일)을 기록합니다. *파일 → 복구 → 자동 저장*으로 복원할 수 있습니다.
- 뒤로 가기 버튼은 Blender를 종료하지 않고 백그라운드로 보냅니다. 종료는 *파일 → 종료*로 합니다.
- 개발자 옵션의 **"활동 보관 안 함"**(Don't keep activities)이 켜져 있으면 다른 앱으로 전환하는 순간
  Android가 Blender를 닫습니다. 실행할 때 이 설정이 켜져 있으면 경고가 표시됩니다.
- Blender가 비정상 종료되면(크래시, 메모리 부족으로 종료 등) 다음 실행 때 종료 원인을 보여 주고
  `Android/data/com.github.sakkijarvenpolkka.blender/files/last_exit.txt`에 기록합니다 (버그 제보에 첨부해 주세요).

---

## Claude로 Blender 사용하기 (MCP)

Blender에 내장된 **MCP 서버** 애드온(Model Context Protocol)을 켜면 Claude Code나 Claude 앱이 Blender의 Python
API로 모델링·머티리얼·애니메이션·렌더링을 직접 수행합니다.

1. 3D 뷰포트 사이드바(`N`)의 **MCP** 탭(또는 환경설정 → 애드온 → MCP Server)에서 **Start MCP Server**.
   처음 시작할 때 토큰(비밀 키)이 만들어집니다. **토큰을 가진 사람은 Blender에서 코드를 실행할 수 있으니
   공유하지 마세요.**
2. 서버가 실행되는 동안 Blender는 백그라운드에서도 계속 동작합니다(알림에 "백그라운드에서 실행 중" 표시).
   같은 휴대폰에서 Claude 앱으로 전환해도 됩니다.

연결 방법:

| 클라이언트 | 방법 |
| --- | --- |
| Claude Code (같은 기기, 예: Termux) | **Copy Claude Code Command** 버튼으로 복사한 명령 실행:<br>`claude mcp add --transport http blender http://127.0.0.1:8765/mcp --header "Authorization: Bearer <토큰>"` |
| Claude Code (PC, USB 연결) | `adb forward tcp:8765 tcp:8765` 후 위와 같은 명령 |
| Claude Code (PC, 같은 Wi-Fi) | **Allow Network Access**를 켜고 패널에 표시된 휴대폰 IP 주소로 연결 |
| Claude 앱 (모바일·웹·데스크톱, 사용자 지정 커넥터) | 아래 **Claude 앱 커넥터 (HTTPS)** 참고: Blender에 포함된 Cloudflare 터널이 `https://…/mcp/<토큰>` 주소를 만들어 줍니다 |

### Claude 앱 커넥터 (HTTPS)

Claude 앱(모바일·웹·데스크톱)의 **사용자 지정 커넥터**는 Anthropic 서버가 인터넷을 통해 **HTTPS(443 포트)**로만
접속하므로 `http://127.0.0.1:8765`나 휴대폰의 IP 주소는 쓸 수 없습니다. Blender for Android에는 Cloudflare Tunnel
클라이언트(`cloudflared`)가 들어 있어서, 휴대폰이 Cloudflare로 바깥 연결을 만들고 공개 HTTPS 주소를
받습니다. 포트 포워딩이나 인증서가 필요 없고 모바일 데이터에서도 동작합니다.

1. MCP 패널의 **Claude App Connector (HTTPS)**에서 방식을 고릅니다.
   - **Quick Tunnel**: 계정 없이 바로 사용할 수 있습니다. 주소(`https://<임의의 단어>.trycloudflare.com`)가
     서버를 시작할 때마다 바뀝니다 (Cloudflare의 체험용 서비스, 가동 보장 없음).
   - **Cloudflare Tunnel**: 주소가 고정됩니다. 무료 Cloudflare 계정과 Cloudflare에 추가된 도메인이 필요합니다.
     Cloudflare 대시보드(Networking → Tunnels)에서 터널을 만들고, 공개 호스트 이름(예: `blender.example.com`)의
     서비스를 `http://localhost:8765`로 지정합니다. 커넥터 설치 명령의 `--token` 뒤의 값을 **Tunnel Token**에
     붙여넣습니다 (호스트 이름은 터널 설정에서 자동으로 읽습니다). 도메인의 보안 설정 중 **AI 봇 차단(Block AI
     bots)**이나 **Bot Fight Mode**가 Claude의 요청을 막을 수 있으니 끄거나, Anthropic의 IP 범위
     (`160.79.104.0/21`)를 WAF 건너뛰기 규칙에 추가하세요.
   - **Custom URL**: 직접 운영하는 HTTPS 터널이나 리버스 프록시의 주소 (443 포트만 가능). 예: TailSocks 앱
     (F-Droid)의 Tailscale Funnel을 443 포트 → `http://127.0.0.1:8765`로, 또는 Termux에서 실행한 ngrok.
2. **Start MCP Server** → 패널에 **Ready**가 표시되면 **Copy Connector URL**
   (`https://<주소>/mcp/<토큰>`, 토큰이 들어 있습니다). Blender가 주소가 실제로 동작하는지(DNS, Cloudflare를 거친
   연결) 먼저 확인합니다. 너무 일찍 추가하면 Claude가 실패를 1분쯤 기억합니다.
3. [claude.ai](https://claude.ai)(휴대폰 브라우저도 가능): **Customize → Connectors → + Add → Add custom connector**에
   이름과 URL을 넣습니다. 인증은 **No sign-in(로그인 없음)**, OAuth와 Request headers는 비워 둡니다.
   추가한 커넥터는 Android/iOS 앱에서도 채팅의 **+ → 커넥터**로 켜서 씁니다.

- 예전에 `http://` 주소로 추가한 커넥터는 동작하지 않으니 삭제하세요. Free 요금제는 사용자 지정 커넥터를
  하나만 만들 수 있습니다. Quick Tunnel의 주소가 바뀌면 커넥터의 **⋯ 메뉴에서 URL을 수정**하고, 수정할 수 없으면
  삭제한 뒤 다시 추가하세요.
- **Keep Awake**(기본값 켜짐): 공개 주소가 있는 동안 화면이 꺼져도 프로세서를 깨워 둡니다. 끄면 기기가 잠들 때
  Claude가 Blender에 닿지 못합니다 (배터리를 더 씁니다). Galaxy에서는 *설정 → 애플리케이션 → Blender →
  배터리*를 **제한 없음**으로 하고, *배터리 → 백그라운드 사용 제한*의 절전/완전 절전 앱 목록에 넣지 마세요.
- URL에 토큰이 들어 있으니 **URL을 가진 사람은 누구나 Blender에서 코드를 실행할 수 있습니다.**
  공유하지 말고, 노출됐다면 **New Token**으로 바꾼 뒤 커넥터 URL을 다시 넣으세요 (터널 주소는 유지됩니다).
  Cloudflare 같은 중계 서비스는 연결 내용을 볼 수 있습니다.
- Claude 앱은 도구 결과를 60초 정도 기다리고, Cloudflare는 100~125초 안에 응답이 없는 요청을 끊습니다.
  터널이나 프록시를 거친 요청에서 50초 넘게 걸리는 도구(긴 렌더링 등)는 Blender에서 계속 실행되고,
  Claude가 `get_tool_result` 도구로 결과를 받습니다. 큰 이미지는 Claude 앱의 결과 크기 제한(약 15만 자)에 맞게
  JPEG로 줄여서 보냅니다.
- 서버가 실행되는 동안에만 연결됩니다 (백그라운드에서도 동작). 네트워크가 끊기면 `cloudflared`가 다시
  연결하고, 끝나 버리면 Blender가 다시 시작합니다 (Quick Tunnel은 이때 주소가 바뀌고 패널에 표시됩니다).
- 휴대폰에서 나가는 연결: TCP 443(`api.trycloudflare.com`), DNS 53(1.1.1.1·8.8.8.8) 또는 TCP 853(1.1.1.1
  DNS-over-TLS) — Android에서 `cloudflared`가 Cloudflare 서버 목록(SRV 레코드)을 찾는 방법, UDP 또는 TCP 7844
  (Cloudflare 터널, UDP가 막힌 네트워크에서는 TCP로 전환). 회사·학교 Wi-Fi처럼 외부 DNS를 막는 네트워크에서는
  터널이 연결되지 않을 수 있으니 다른 네트워크(모바일 데이터 등)를 쓰세요.
- 연결이 안 될 때: 패널의 **Requests from the internet** 목록에 Claude의 요청(`server/discover`, `initialize`,
  `tools/list` …)과 응답 코드(오류면 그 이유)가 표시됩니다. 요청이 전혀 없으면 주소·커넥터 설정 문제입니다.
  `initialize 200` 뒤에 아무 요청도 없으면 Claude 쪽 문제일 수 있습니다 (2026년 11월 초부터 새 커넥터에서 보고된
  claude.ai 버그, [anthropics/claude-ai-mcp#1214](https://github.com/anthropics/claude-ai-mcp/issues/1214)).
  같은 URL을 PC의 Claude Code로 확인할 수 있습니다: `claude mcp add --transport http blender https://<주소>/mcp/<토큰>`.
- `cloudflared`는 Cloudflare의 오픈 소스 프로그램입니다 (Apache License 2.0). 라이선스와 포함된 Go 모듈의
  고지는 APK의 `assets/licenses`에 있습니다. 자동 업데이트는 꺼져 있고 APK와 함께 업데이트됩니다.

PC나 서버의 Blender에서는 `cloudflared`가 `PATH`에 있으면 같은 기능을 쓸 수 있습니다
(백그라운드 모드: `mcp_server.serve_forever(port=8765, public='QUICK')`, 고정 주소는
`public='TOKEN'`과 `TUNNEL_TOKEN` 환경 변수).

제공 도구: `execute_python`(bpy·mathutils·NumPy, 변수 유지), `get_scene_info`, `get_object_info`,
`get_viewport_screenshot`(뷰포트 화면 이미지), `render_image`(렌더 결과 이미지), `save_blend_file`,
`get_tool_result`(오래 걸린 도구의 결과).
서버가 Claude에게 주는 안내문에 추가 구성 요소 설치 방법(`android_components`)도 포함되어 있어, 필요하면 Claude가
USD Python 모듈이나 Python 패키지를 직접 설치해 사용할 수 있습니다.
PC나 서버의 Blender에서도 같은 애드온을 쓸 수 있습니다:
`blender --background --python-expr "import mcp_server; mcp_server.serve_forever(port=8765)"`.

---

## 빌드

### 필요 환경

- Linux x86_64 (Ubuntu 24.04에서 테스트), 디스크 여유 공간 40GB 이상, RAM 16GB 권장
- 패키지:
  ```sh
  sudo apt install build-essential cmake ninja-build git curl unzip zip patch python3 \
    openjdk-17-jdk qemu-user-static autoconf automake libtool pkg-config flex bison golang
  ```
- Android SDK/NDK는 스크립트가 자동으로 설치합니다 (NDK r29, SDK platform 35).
- Go 1.21 이상: `cloudflared`(MCP 서버의 HTTPS 주소, `scripts/build_cloudflared.sh`) 빌드에 사용합니다
  (cloudflared가 요구하는 버전은 Go가 자동으로 받습니다).

### 한 번에 빌드

```sh
./scripts/build_all.sh
# 결과: _work/out/Blender-5.2.2-android-arm64-v8a.apk
adb install -r _work/out/Blender-5.2.2-android-arm64-v8a.apk
```

단계별 실행:

| 스크립트 | 내용 | 소요 시간 (4코어 기준) |
| --- | --- | --- |
| `scripts/setup_sdk.sh` | Android NDK r29 / SDK 설치 | 수 분 |
| `scripts/fetch_blender.sh` | Blender 5.2.2 소스 다운로드·검증, Android 패치 적용 | 1분 |
| `scripts/build_deps.sh` | 의존성 약 75개 크로스 컴파일 (`deps/`), 바뀐 것만 다시 빌드 | 약 3~4시간 (USD, LLVM 포함) |
| `scripts/build_blender.sh` | Blender 크로스 컴파일 → `libblender.so` + 데이터 | 3~4시간 |
| `scripts/build_cloudflared.sh` | Cloudflare Tunnel 클라이언트(`libcloudflared.so`) 빌드 (Go) | 1~2분 |
| `scripts/package_apk.sh` | 데이터 압축, Gradle로 APK 생성 | 수 분 |
| `scripts/build_components.sh` | 추가 구성 요소 빌드 (`components/`, `libblender.so`에 링크) → `_work/out/components` | 약 30분 |

모든 결과물은 `_work/` 아래에 생성됩니다 (`WORK_DIR` 환경 변수로 변경 가능). GitHub Actions
(`.github/workflows/build-apk.yml`)도 같은 스크립트로 APK와 추가 구성 요소를 빌드해 아티팩트로 올립니다.
기본 브랜치의 빌드가 성공하면 APK와 구성 요소(`*.zip`, `components.json`)를 릴리스
`v<버전>-android.<리비전>-build.<실행 번호>`로 게시하고(최근 10개 유지), `v*` 태그를 푸시하면 그 태그의 릴리스로
게시합니다. 앱은 자신이 게시된 릴리스에서 구성 요소를 내려받습니다.

의존성은 설치될 때마다 설정 해시를 `LIBDIR/.deps/`에 기록하므로, 캐시된 `LIBDIR`에서는 추가·변경된 의존성만
빌드합니다. CI는 GitHub 호스트 러너의 6시간 제한 안에 끝나도록 단계를 나눕니다: 의존성(`deps.yml`)과
Blender(`blender.yml`) 모두 시간 제한(`DEPS_TIME_LIMIT`, `BLENDER_TIME_LIMIT`)에 도달하면 그때까지의 결과를
캐시에 저장하고 다음 단계가 이어서 빌드합니다.

릴리스 키로 서명하려면 `BLENDER_ANDROID_KEYSTORE`, `BLENDER_ANDROID_KEYSTORE_PASSWORD`,
`BLENDER_ANDROID_KEY_ALIAS`, `BLENDER_ANDROID_KEY_PASSWORD` 환경 변수를 설정하세요 (없으면 디버그 키로 서명).

CI 빌드를 항상 같은 키로 서명하려면(앱을 삭제하지 않고 업데이트 가능) 키를 만들어 저장소의
*Settings → Secrets and variables → Actions*에 등록합니다. 키 파일은 저장소에 커밋하지 마세요.

```sh
keytool -genkeypair -v -keystore blender-android.keystore -alias blender -keyalg RSA -keysize 4096 -validity 10000
base64 -w0 blender-android.keystore   # → BLENDER_ANDROID_KEYSTORE_BASE64
```

| 시크릿 | 값 |
| --- | --- |
| `BLENDER_ANDROID_KEYSTORE_BASE64` | 키 저장소 파일의 base64 |
| `BLENDER_ANDROID_KEYSTORE_PASSWORD` | 키 저장소 비밀번호 |
| `BLENDER_ANDROID_KEY_ALIAS` | 키 별칭 (위 예: `blender`) |
| `BLENDER_ANDROID_KEY_PASSWORD` | 키 비밀번호 |

---

## 구조

```
BLENDER_VERSION              포팅 대상 Blender 버전 (5.2.2)
deps/                        의존성 크로스 컴파일 (CMake superbuild)
  cmake/libs_python.cmake    CPython 3.13 (+OpenSSL, libffi, SQLite, xz, bzip2)
  cmake/libs_core.cmake      이미지/색 관리/압축/기하 라이브러리
  cmake/libs_gpu.cmake       Vulkan 헤더, shaderc, SDL3
  cmake/libs_python_packages.cmake  NumPy, requests 등 Python 패키지
  cmake/libs_media.cmake     FFmpeg과 코덱(x264, x265, libvpx, aom, Opus, Vorbis …), libsndfile
  cmake/libs_misc.cmake      HarfBuzz, FriBidi, libharu, Draco, meshoptimizer, Ceres, Rubberband
  cmake/libs_render.cmake    Embree, OpenPGL, Open Image Denoise (ISPC)
  cmake/libs_scene.cmake     OpenVDB/NanoVDB, Blosc, Alembic, MaterialX
  cmake/libs_usd.cmake       USD (설정: cmake/usd_options.cmake)
  cmake/libs_osl.cmake       LLVM·Clang, Open Shading Language (+ Python 모듈 oslquery, pybind11)
  patches/                   Android용 의존성 패치
components/                  APK 설치 후 설치하는 추가 구성 요소 (USD Python 모듈)
blender/
  android_config.cmake       Blender CMake 옵션 (Android용)
  overlay/                   Blender 소스에 추가되는 새 파일
  patches/                   Blender 소스 수정 사항
android/                     Android 앱 (Gradle)
scripts/                     빌드 스크립트
```

### 기술적인 내용

- **버전·의존성**: 의존성의 버전, 다운로드 URL, 체크섬은 Blender 소스의
  `build_files/build_environment/cmake/versions.cmake`를 그대로 사용해 공식 릴리스와 같은 라이브러리로 빌드합니다.
  모두 정적 라이브러리로 빌드되어 하나의 `libblender.so`에 링크됩니다.
- **크로스 컴파일 중 빌드 도구 실행**: Blender는 빌드 중에 `makesdna`, `makesrna`, `datatoc`, `shader_tool`,
  `msgfmt`를 실행합니다. 이 도구들을 정적 Android 실행 파일로 빌드하고 QEMU user-mode(`qemu-aarch64-static`)로
  실행하므로(`CMAKE_CROSSCOMPILING_EMULATOR`), DNA 구조체 크기 등이 실제 대상 아키텍처 기준으로 계산됩니다.
- **GHOST Android 백엔드** (`intern/ghost/intern/GHOST_SystemAndroid.cc`, `GHOST_WindowAndroid.cc`):
  SDL3가 Activity 생명주기, Surface, 입력, IME, 클립보드를 담당합니다. 터치 제스처 인식, S Pen 필압/기울기,
  DeX 마우스(포인터 캡처), 가상 키보드 단축키 입력, 한글 등 IME 조합 입력을 처리합니다.
- **Vulkan** (`GHOST_ContextVK.cc`): `VK_KHR_android_surface`, 앱 일시정지/재개 시 Surface 재생성,
  화면 회전(preTransform) 처리, 모바일 GPU에 없는 기능(예: Qualcomm 드라이버의 `VK_EXT_provoking_vertex`)을
  필수에서 선택으로 완화했습니다. 환경설정의 GPU 백엔드 기본값도 Vulkan이며, OpenGL이 저장된 이전 설정은 불러올 때
  Vulkan으로 바뀝니다(데스크톱 기본값인 OpenGL을 먼저 시도하면 OpenGL이 없는 이 빌드에서는 실패로 처리되어, 실제로는
  Vulkan으로 동작하면서도 시작할 때마다 "Failed to load using Vulkan, using OpenGL instead" 경고가 떴습니다 — 빌드 24까지).
  기기의 Vulkan 드라이버가 Blender에 필요한 기능을 지원하지 않으면 바로 종료되는 대신 "Platform Unsupported" 안내
  창을 띄우고 종료합니다(자세한 이유는 `adb logcat -s Blender`).
- **Python**: 표준 라이브러리 확장 모듈은 `libpython3.13.a`에 정적으로 포함하고(`MODULE_BUILDTYPE=static`) Python
  전체를 `libblender.so`에 링크합니다. NumPy 같은 패키지의 확장 모듈은 CPython의 Android 빌드처럼 공유 라이브러리로
  데이터와 함께 풀리며, Python API를 제공하는 `libblender.so`에 의존하도록 빌드합니다(`deps/cmake/cross_python.cmake`).
  Android 앱은 네이티브 라이브러리 폴더의 파일만 실행할 수 있으므로 Python 실행 파일(`sys.executable`, 확장
  플랫폼 등 하위 프로세스용)을 `libblender_python.so`라는 이름으로 함께 패키징합니다. stdout/stderr는 logcat으로
  전달됩니다.
- **USD**: 정적 모놀리식 라이브러리(`usd_m`)를 통째로(`--whole-archive`) `libblender.so`에 링크합니다(타입·플러그인이
  정적 생성자로 등록됨). Python 지원은 Blender에 내장된 Python을 쓰고, Python 모듈(`pxr`)은 APK에 넣지 않고
  추가 구성 요소로 제공합니다(아래). 플러그인 정보(`plugInfo.json`)와 MaterialX 표준 라이브러리는 데이터 파일과 함께
  설치되어 Blender가 USD를 처음 사용할 때 등록합니다. bionic에 없는 glibc 전용 기능(`NOFILE`, `__environ`)과 FFmpeg의
  libaom과 충돌하는 USD의 AVIF 플러그인은 패치로 처리합니다(`deps/patches/usd_android.diff`).
- **OSL**: LLVM 20과 Clang(AArch64)을 정적 라이브러리로 빌드해 OSL과 함께 `libblender.so`에 링크합니다(셰이더
  JIT 컴파일). OSL 빌드에 필요한 도구(`llvm-config`, `clang`, `llvm-as`, `llvm-link`, `oslc`, LUT 생성기)는 Blender
  빌드 도구처럼 정적 Android 실행 파일로 만들어 QEMU로 실행하고, Cycles 셰이더(.oso)도 같은 방식으로 컴파일합니다
  (`deps/cmake/libs_osl.cmake`). 스크립트 노드에 쓰이는 OSL의 Python 모듈(`oslquery`)은 NumPy처럼 `libblender.so`의
  Python API에 링크한 확장 모듈로 빌드합니다.
- **추가 구성 요소**: USD Python 모듈은 같은 소스·설정(`deps/cmake/usd_options.cmake`)으로 빌드하되 USD 라이브러리
  대신 `libblender.so`에 링크합니다(`PXR_MONOLITHIC_IMPORT`). libc++는 Android에서 타입을 주소로 비교하므로, 모듈이
  `libblender.so`의 C++ 런타임·USD·TBB 심볼을 함께 쓰도록 이 심볼들을 내보내고(`symbols_android.map`),
  `libblender.so`를 전역 라이브러리(`-z global`)로 링크해 나중에 로드되는 Python 확장 모듈보다 우선하게 합니다.
  데스크톱에서 실행 파일의 심볼이 우선하는 것과 같은 동작입니다. 구성 요소는 `android_components` 애드온이
  설치·관리합니다.
- **Open Image Denoise**: CPU 커널은 ISPC로 컴파일합니다(Android/ARM64를 지원하는 ISPC 릴리스 바이너리 사용).
  bionic에 없는 `pthread_*affinity_np` 대신 `sched_*affinity`를 사용합니다(`deps/patches/oidn_android.diff`).
- **크래시 리포트**: API 33 미만에는 `execinfo.h`가 없어 C++ 런타임의 언와인더로 백트레이스를 기록합니다
  (라이브러리 + 오프셋, `llvm-addr2line -f -C -e libblender.so <오프셋>`으로 해석).
- **데이터 파일**: `datafiles`, `scripts`, Python 표준 라이브러리를 `blender_data.zip`으로 APK에 넣고
  첫 실행 시 내부 저장소에 풀어 `BLENDER_SYSTEM_RESOURCES`로 지정합니다.

---

## 라이선스

GPL-3.0-or-later (Blender와 동일, 새로 작성한 파일은 GPL-2.0-or-later 헤더). [LICENSE](LICENSE) 참고.
각 의존성은 해당 라이선스를 따릅니다.
