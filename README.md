# Blender for Android (비공식 포팅)

[Blender](https://www.blender.org) **5.2.2** (2026년 9월 기준 최신 안정 버전)를 Android(arm64)로 포팅하는 프로젝트입니다.
**최소 사양은 Galaxy S22 시리즈**(Snapdragon 8 Gen 1 / Exynos 2200, Android 12 이상, Vulkan)입니다.

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
| 의존성 크로스 컴파일 (Python 3.13, OIIO, OCIO, OpenEXR, TBB, shaderc, SDL3, OpenSubdiv, Manifold, GMP, FFTW …) | ✅ 빌드 확인 |
| Blender 5.2.2 → `libblender.so` (arm64-v8a, API 31) | 빌드 진행/검증 결과는 아래 "검증" 참고 |
| APK 패키징 (Gradle, 데이터 자동 설치, 터치 툴바) | ✅ |
| 실제 기기(Galaxy S22)에서의 실행 | ⚠️ **실기기 테스트 전** — GPU 드라이버 호환성은 기기에서 확인 필요 |

실기기에서 문제가 있으면 `adb logcat -s Blender SDL BlenderLauncher` 로그와 함께 이슈를 남겨 주세요.

### 지원 기능

- **UI / 3D 뷰포트**: Vulkan 백엔드 (Workbench, EEVEE)
- **렌더링**: Cycles (CPU, ARM NEON), EEVEE
- **Python**: CPython 3.13 (표준 라이브러리 + `ssl`, `sqlite3`, `ctypes` 등 확장 모듈 정적 링크)
- **입출력**: .blend, OBJ, PLY, STL, FBX, glTF, SVG / 이미지(PNG, JPEG, EXR, TIFF, WebP, JPEG2000 …)
- **모델링**: OpenSubdiv, Boolean(Manifold/Exact), Remesh, QuadriFlow, 물리(Bullet), 유체(Mantaflow), 오션
- **오디오**: SDL3 (AAudio / OpenSL ES)
- **파일 열기**: 파일 관리자에서 `.blend` 파일 열기 지원

### 아직 지원하지 않는 기능

OpenVDB(볼륨), Alembic, USD, MaterialX, FFmpeg(동영상), NumPy, OpenImageDenoise, Embree, 모션 트래킹(libmv),
OpenXR, Cycles GPU 렌더링, 여러 개의 창(환경설정·파일 브라우저·렌더 결과는 메인 창 안에서 열리도록 기본 설정됨).

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

- 첫 실행 시 Blender 데이터(약 200MB)를 내부 저장소에 설치합니다 (업데이트 후에도 한 번).
- "모든 파일 접근" 권한을 허용하면 기기의 모든 폴더에서 .blend 파일을 열고 저장할 수 있습니다.
- UI 크기는 Blender의 *환경설정 → 인터페이스 → 해상도 배율*로 조절합니다.
- 앱이 백그라운드로 전환될 때 자동 저장(복구 파일)을 기록합니다. *파일 → 복구 → 자동 저장*으로 복원할 수 있습니다.

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
- **Python**: Android에서는 앱 데이터 폴더의 `.so`를 로드할 수 없으므로(W^X 정책) 표준 라이브러리 확장 모듈을
  모두 `libpython3.13.a`에 정적으로 포함했습니다 (`MODULE_BUILDTYPE=static`). stdout/stderr는 logcat으로 전달됩니다.
- **데이터 파일**: `datafiles`, `scripts`, Python 표준 라이브러리를 `blender_data.zip`으로 APK에 넣고
  첫 실행 시 내부 저장소에 풀어 `BLENDER_SYSTEM_RESOURCES`로 지정합니다.

---

## 라이선스

GPL-3.0-or-later (Blender와 동일, 새로 작성한 파일은 GPL-2.0-or-later 헤더). [LICENSE](LICENSE) 참고.
각 의존성은 해당 라이선스를 따릅니다.
