RMDIR /S /Q "build"
RMDIR /S /Q "dist"
pyinstaller main.py --clean --onefile --windowed --noconsole ^
	--name="gitlab-pipelines" ^
	--collect-submodules="gitlab-pipelines" ^
	--icon="logo.ico" 
	--target-architecture="x86_64"
XCOPY "assets" "dist/assets" /S /E /I
COPY "settings.json" "dist/settings.json" /b/v/y