RMDIR /S /Q "build"
RMDIR /S /Q "dist"
pyinstaller src/main.py --clean --onefile ^
	--name="gitlab-pipelines" ^
	--version-file="version_info.rc" ^
	--collect-submodules="gitlab-pipelines" ^
	--collect-all="plyer" ^
	--icon="logo.ico" ^
	--target-architecture="x86_64"
XCOPY "assets" "dist/assets" /S /E /I
COPY "settings.json" "dist/settings.json" /b/v/y