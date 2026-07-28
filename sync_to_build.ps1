# Sync root source to build_temp/ and run flutter pub get
param(
    [switch]$SyncOnly,
    [switch]$PubGet,
    [switch]$Analyze,
    [switch]$Run
)

$Root = "D:\zayn\project\comic_downloader"
$Build = "$Root\build_temp"

Write-Host "==> Syncing lib/ to build_temp/lib/" -ForegroundColor Cyan
Copy-Item -Path "$Root\lib\*" -Destination "$Build\lib\" -Recurse -Force

Write-Host "==> Syncing pubspec.yaml" -ForegroundColor Cyan
Copy-Item -Path "$Root\pubspec.yaml" -Destination "$Build\pubspec.yaml" -Force

Write-Host "==> Syncing analysis_options.yaml" -ForegroundColor Cyan
Copy-Item -Path "$Root\analysis_options.yaml" -Destination "$Build\analysis_options.yaml" -Force

if ($SyncOnly) { return }

if ($PubGet -or $Analyze -or $Run) {
    $env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
    $env:ANDROID_HOME = "C:\Users\rafki\AppData\Local\Android\Sdk"

    Set-Location -Path $Build

    if ($PubGet) {
        Write-Host "==> Running flutter pub get..." -ForegroundColor Cyan
        & "C:\Android\flutter\bin\cache\dart-sdk\bin\dart.exe" "C:\Android\flutter\bin\cache\flutter_tools.snapshot" pub get
    }

    if ($Analyze) {
        Write-Host "==> Running flutter analyze..." -ForegroundColor Cyan
        & "C:\Android\flutter\bin\cache\dart-sdk\bin\dart.exe" "C:\Android\flutter\bin\cache\flutter_tools.snapshot" analyze
    }

    if ($Run) {
        Write-Host "==> Running flutter run..." -ForegroundColor Cyan
        & "C:\Android\flutter\bin\cache\dart-sdk\bin\dart.exe" "C:\Android\flutter\bin\cache\flutter_tools.snapshot" run -d emulator-5554
    }
}
