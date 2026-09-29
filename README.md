# Blender for Android (비공식 포팅)

[Blender](https://www.blender.org) **5.2.2** (2026년 9월 기준 최신 안정 버전)를 Android(arm64)로 포팅하는 프로젝트입니다.
**최소 사양은 Galaxy S22 시리즈**(Snapdragon 8 Gen 1 / Exynos 2200, Android 12 이상, Vulkan 1.2 이상)입니다.
GPU 드라이버가 Vulkan 1.2를 지원해야 하므로 기기를 최신 One UI로 업데이트해 두세요.

> 이 프로젝트는 Blender 재단과 관련이 없는 **비공식** 포팅입니다. "Blender"는 Blender 재단의 상표입니다.
> 코드는 Blender와 같은 GPL 라이선스를 따릅니다.

*English summary: unofficial port of Blender 5.2.2 to Android arm64 (minimum: Galaxy S22 / Android 12 /
Vulkan). The native UI runs on an SDL3-based GHOST back-end with the Vulkan GPU back-end, the Python
3.13 standard library is linked statically, and all dependencies are cross-compiled from source.
See "Build" below.*

---

## 현재 상태

| 항목 | 상태 |
| --- | --- |
| 의존성 크로스 컴파일 (Python 3.13, OIIO, OCIO, OpenEXR, TBB, shaderc, SDL3, OpenSubdiv, Manifold, GMP, FFTW, FFmpeg, OpenVDB, Embree, OIDN …) | ✅ 빌드 확인 |
| Blender 5.2.2 → `libblender.so` (arm64-v8a, API 31, 16KB 페이지 정렬) | ✅ 빌드·링크 확인 |
| Android bionic 위에서 백그라운드 모드 실행 (QEMU, 아래 "검증") | ✅ 스모크 테스트 통과 |
| NumPy 2.3, requests 등 Python 패키지, 확장(Extensions) 온라인 설치 | ✅ QEMU에서 확인 |
| Claude 연동 (MCP 서버: Claude Code / Claude 앱에서 Blender 제어) | ✅ QEMU에서 종단 간 테스트 통과 |
| APK 패키징 (Gradle, 데이터 자동 설치, 터치 툴바) | ✅ 약 115MB APK 생성 확인 |
| 실제 기기(Galaxy S22)에서 UI 실행 (SDL3 창, Vulkan, 터치 입력) | ⚠️ **실기기 테스트 전** — GPU 드라이버 호환성은 기기에서 확인 필요 |

### 검증

실기기 없이 확인할 수 있는 부분은 빌드 머신에서 검증합니다. `tests/qemu/run_blender.sh`는 빌드된
`libblender.so`를 QEMU user-mode 에뮬레이션과 Android 14 에뮬레이터 이미지에서 추출한 bionic
(`linker64`, `libc.so` …)으로 실행하고, 앱과 같은 방식(`SDL_main` 호출)으로 Blender를 시작합니다.
CI에서도 매 빌드마다 실행됩니다.

- `blender --version` → `Blender 5.2.2 LTS`
- 스모크 테스트 (`tests/qemu/smoke_test.py`, 백그라운드 모드): Python 표준 라이브러리 확장 모듈
  (`ssl`/OpenSSL 3.5, `hashlib`, `sqlite3`, `lzma`, `bz2`, `zlib`, `decimal`, `ctypes`), OpenSubdiv 서브디비전,
  Boolean(Manifold/Exact), .blend 저장·불러오기, OBJ/PLY/STL 내보내기, Cycles CPU 렌더링 → PNG/EXR/JPEG/WebP,
  OpenImageIO 이미지 읽기, OpenColorIO(AgX), NumPy(`foreach_get`), glTF·FBX 내보내기 — **모두 통과**
- Python 실행 파일(`sys.executable`, 격리 모드 `-I`): 표준 라이브러리·NumPy·requests 로드, 확장 플랫폼 CLI로
  extensions.blender.org 목록 동기화(HTTPS) 확인
- MCP 서버 종단 간 테스트 (`tests/qemu/mcp_test.py`): 최신(2026-07-28)·구버전(2025-06-18) 프로토콜,
  `execute_python`(NumPy로 메시 생성), 씬·오브젝트 정보, Cycles 렌더 이미지 반환, .blend 저장 — **통과**

GPU(Vulkan) 경로와 터치·펜 입력은 에뮬레이션으로 확인할 수 없어 실기기 테스트가 필요합니다.

실기기에서 문제가 있으면 `adb logcat -s Blender SDL BlenderLauncher` 로그와 함께 이슈를 남겨 주세요.

### 지원 기능

- **UI / 3D 뷰포트**: Vulkan 백엔드 (Workbench, EEVEE)
- **렌더링**: Cycles (CPU, ARM NEON) — Embree 레이 트레이싱, 경로 가이딩(OpenPGL), AI 디노이즈(OpenImageDenoise), EEVEE
- **Python**: CPython 3.13 (표준 라이브러리 + `ssl`, `sqlite3`, `ctypes` 등), 공식 Blender와 같은 번들 패키지:
  **NumPy 2.3**, requests, certifi, cattrs, autopep8 등 / `aud`(오디오) 모듈
- **확장(Extensions)**: extensions.blender.org에서 애드온 검색·설치 (환경설정 → 시스템 → 네트워크에서 온라인 접근 허용),
  원격 에셋 라이브러리·온라인 Essentials
- **Claude 연동**: 내장 MCP 서버 애드온 — Claude Code나 Claude 앱이 Blender Python API를 사용 (아래 참고)
- **입출력**: .blend, OBJ, PLY, STL, FBX, glTF/GLB(Draco·meshoptimizer 압축), Alembic, SVG, Grease Pencil PDF /
  이미지(PNG, JPEG, EXR, TIFF, WebP, JPEG2000 …)
- **동영상 (FFmpeg)**: 공식 릴리스와 같은 코덱 — H.264(x264), H.265(x265), VP9, AV1, Theora / AAC, Opus, Vorbis,
  MP3, FLAC. 애니메이션을 동영상으로 렌더링, 동영상 편집기(VSE), 동영상 클립 불러오기
- **모션 트래킹**: 동영상 클립 트래킹·카메라 솔브 (libmv, Ceres)
- **볼륨**: OpenVDB/NanoVDB — .vdb 불러오기·저장, 메시 ↔ 볼륨, Cycles 볼륨 렌더링
- **모델링**: OpenSubdiv, Boolean(Manifold/Exact), Remesh, QuadriFlow, 물리(Bullet), 유체(Mantaflow), 오션
- **텍스트**: HarfBuzz·FriBidi (복잡한 문자·오른쪽에서 왼쪽으로 쓰는 문자)
- **오디오**: SDL3 (AAudio / OpenSL ES), 오디오 파일 읽기·쓰기 (libsndfile, FFmpeg)
- **파일 열기**: 파일 관리자에서 `.blend` 파일 열기 지원

### 아직 지원하지 않는 기능

USD·MaterialX(작업 중), OSL(Open Shading Language, LLVM 필요), Rubberband(오디오 피치/속도), OpenXR,
Cycles GPU 렌더링(모바일 GPU용 Cycles 백엔드 없음), 여러 개의 창(환경설정·파일 브라우저·렌더 결과는 메인 창
안에서 열림), 네이티브 라이브러리(glibc용 wheel)를 포함한 일부 확장은 지원하지 않습니다.

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

- 첫 실행 시 Blender 데이터(약 190MB)를 내부 저장소에 설치합니다 (업데이트 후에도 한 번).
- "모든 파일 접근" 권한을 허용하면 기기의 모든 폴더에서 .blend 파일을 열고 저장할 수 있습니다.
- UI 크기는 Blender의 *환경설정 → 인터페이스 → 해상도 배율*로 조절합니다.
- 앱이 백그라운드로 전환될 때 자동 저장(복구 파일)을 기록합니다. *파일 → 복구 → 자동 저장*으로 복원할 수 있습니다.

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
| Claude 앱 (모바일·웹, 사용자 지정 커넥터) | 커넥터에는 인터넷에서 접근 가능한 HTTPS 주소가 필요합니다. 휴대폰에서 터널을 실행하고 (예: Termux에서 `cloudflared tunnel --url http://127.0.0.1:8765`), **Copy URL with Token**으로 복사한 주소의 `http://127.0.0.1:8765` 부분을 터널 주소로 바꾼 `https://<터널 주소>/mcp/<토큰>`을 커넥터로 추가 |

제공 도구: `execute_python`(bpy·mathutils·NumPy, 변수 유지), `get_scene_info`, `get_object_info`,
`get_viewport_screenshot`(뷰포트 화면 이미지), `render_image`(렌더 결과 이미지), `save_blend_file`.
PC나 서버의 Blender에서도 같은 애드온을 쓸 수 있습니다:
`blender --background --python-expr "import mcp_server; mcp_server.serve_forever(port=8765)"`.

---

## 빌드

### 필요 환경

- Linux x86_64 (Ubuntu 24.04에서 테스트), 디스크 여유 공간 40GB 이상, RAM 16GB 권장
- 패키지:
  ```sh
  sudo apt install build-essential cmake ninja-build git curl unzip zip patch python3 \
    openjdk-17-jdk qemu-user-static autoconf automake libtool pkg-config
  ```
- Android SDK/NDK는 스크립트가 자동으로 설치합니다 (NDK r29, SDK platform 35).

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
| `scripts/build_deps.sh` | 의존성 약 40개 크로스 컴파일 (`deps/`) | 약 40분 |
| `scripts/build_blender.sh` | Blender 크로스 컴파일 → `libblender.so` + 데이터 | 1.5~2시간 |
| `scripts/package_apk.sh` | 데이터 압축, Gradle로 APK 생성 | 수 분 |

모든 결과물은 `_work/` 아래에 생성됩니다 (`WORK_DIR` 환경 변수로 변경 가능). GitHub Actions
(`.github/workflows/build-apk.yml`)도 같은 스크립트로 APK를 빌드해 아티팩트로 올립니다.
`v*` 태그를 푸시하면 릴리스에 APK가 첨부됩니다.

릴리스 키로 서명하려면 `BLENDER_ANDROID_KEYSTORE`, `BLENDER_ANDROID_KEYSTORE_PASSWORD`,
`BLENDER_ANDROID_KEY_ALIAS`, `BLENDER_ANDROID_KEY_PASSWORD` 환경 변수를 설정하세요 (없으면 디버그 키로 서명).

---

## 구조

```
BLENDER_VERSION              포팅 대상 Blender 버전 (5.2.2)
deps/                        의존성 크로스 컴파일 (CMake superbuild)
  cmake/libs_python.cmake    CPython 3.13 (+OpenSSL, libffi, SQLite, xz, bzip2)
  cmake/libs_core.cmake      이미지/색 관리/압축/기하 라이브러리
  cmake/libs_gpu.cmake       Vulkan 헤더, shaderc, SDL3
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
  필수에서 선택으로 완화했습니다.
- **Python**: 표준 라이브러리 확장 모듈은 `libpython3.13.a`에 정적으로 포함하고(`MODULE_BUILDTYPE=static`) Python
  전체를 `libblender.so`에 링크합니다. NumPy 같은 패키지의 확장 모듈은 CPython의 Android 빌드처럼 공유 라이브러리로
  데이터와 함께 풀리며, Python API를 제공하는 `libblender.so`에 의존하도록 빌드합니다(`deps/cmake/cross_python.cmake`).
  Android 앱은 네이티브 라이브러리 폴더의 파일만 실행할 수 있으므로 Python 실행 파일(`sys.executable`, 확장
  플랫폼 등 하위 프로세스용)을 `libblender_python.so`라는 이름으로 함께 패키징합니다. stdout/stderr는 logcat으로
  전달됩니다.
- **데이터 파일**: `datafiles`, `scripts`, Python 표준 라이브러리를 `blender_data.zip`으로 APK에 넣고
  첫 실행 시 내부 저장소에 풀어 `BLENDER_SYSTEM_RESOURCES`로 지정합니다.

---

## 라이선스

GPL-3.0-or-later (Blender와 동일, 새로 작성한 파일은 GPL-2.0-or-later 헤더). [LICENSE](LICENSE) 참고.
각 의존성은 해당 라이선스를 따릅니다.
