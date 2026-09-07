# Third-party components

Application code is provided in this repository. No additional public redistribution license for the application has been selected by the repository owner.

Dependencies retain their own terms:

- **PySide6 / Qt / Shiboken**: Qt licensing terms, including LGPL/GPL/commercial options as applicable. See https://doc.qt.io/qtforpython-6/licenses.html and the installed distribution license files. The portable build uses an onedir layout with shared Qt libraries, not a single statically linked application.
- **Pillow**: HPND license. https://github.com/python-pillow/Pillow/blob/main/LICENSE
- **imageio-ffmpeg**: BSD-2-Clause wrapper. Its bundled FFmpeg executable has separate build-dependent license terms; the wrapper's BSD license does not license that executable. https://github.com/imageio/imageio-ffmpeg
- **FFmpeg / libx264**: the bundled H.264-capable build may use GPL terms. Inspect its `-L` and `-buildconf` output and obtain corresponding build/source information from the supplying project before broader redistribution. https://ffmpeg.org/legal.html and https://github.com/imageio/imageio-binaries
- **faster-whisper** (optional, source install only): MIT code and separate dependencies/model assets. https://github.com/SYSTRAN/faster-whisper
- **PyInstaller** (build tool): GPL with bootloader exception. https://pyinstaller.org/en/stable/license.html

GitHub packaging copies installed Python dependency license/notice metadata into `dependency-licenses`. This automated collection is not a substitute for reviewing component-specific binary/source redistribution requirements before publishing a wider software release.

- **MCP Python SDK**: MIT; https://github.com/modelcontextprotocol/python-sdk.
- **filelock**: Unlicense; https://github.com/tox-dev/filelock.
- **OpenAI tunnel-client**: downloaded separately by the optional wizard from official releases, with its own included license notices. It is not embedded in this repository or application artifact. https://github.com/openai/tunnel-client
