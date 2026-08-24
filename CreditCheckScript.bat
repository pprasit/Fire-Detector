@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Codex Credit Checker

rem Opens ChatGPT in the selected Chrome profile. Credit balances are shown in
rem ChatGPT: Codex Settings > Usage Dashboard. This script never reads cookies,
rem passwords, tokens, or the credit balance itself.

set "SCRIPT_DIR=%~dp0"
set "SETTINGS_FILE=%SCRIPT_DIR%CreditCheckScript.settings.bat"
set "CHATGPT_URL=https://chatgpt.com/"

if exist "%SETTINGS_FILE%" call "%SETTINGS_FILE%"

if not defined CREDIT_CHECK_BROWSER call :findChrome
if not defined PAKAWAT_CHROME_PROFILE call :setupProfiles
if not defined EAK_CHROME_PROFILE call :setupProfiles

:chooseAccount
cls
echo ==============================================
echo             Codex Credit Checker
echo ==============================================
echo.
echo   1. Pakawat  - Pakawat.prasit633@gmail.com
echo   2. Eak      - eak.prasit633@gmail.com
echo   3. Configure Chrome profiles
echo   4. Exit
echo.
choice /c 1234 /n /m "Choose an account"

if errorlevel 4 exit /b 0
if errorlevel 3 (
  call :setupProfiles
  goto chooseAccount
)
if errorlevel 2 (
  set "ACCOUNT_NAME=Eak"
  set "ACCOUNT_EMAIL=eak.prasit633@gmail.com"
  set "SELECTED_PROFILE=%EAK_CHROME_PROFILE%"
  goto openDashboard
)

set "ACCOUNT_NAME=Pakawat"
set "ACCOUNT_EMAIL=Pakawat.prasit633@gmail.com"
set "SELECTED_PROFILE=%PAKAWAT_CHROME_PROFILE%"

:openDashboard
if not exist "%CREDIT_CHECK_BROWSER%" (
  echo.
  echo Chrome was not found at:
  echo %CREDIT_CHECK_BROWSER%
  echo.
  pause
  call :findChrome
)

echo.
echo Opening ChatGPT for %ACCOUNT_NAME% ^(%ACCOUNT_EMAIL%^) ...
echo.
echo In ChatGPT, open: Codex Settings ^> Usage Dashboard
echo This page shows the current credit balance and recent usage.
start "ChatGPT - %ACCOUNT_NAME%" "%CREDIT_CHECK_BROWSER%" --profile-directory="%SELECTED_PROFILE%" "%CHATGPT_URL%"
timeout /t 3 /nobreak >nul
exit /b 0

:findChrome
set "CREDIT_CHECK_BROWSER="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CREDIT_CHECK_BROWSER=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CREDIT_CHECK_BROWSER if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CREDIT_CHECK_BROWSER=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CREDIT_CHECK_BROWSER if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CREDIT_CHECK_BROWSER=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not defined CREDIT_CHECK_BROWSER (
  echo.
  echo Google Chrome was not found automatically.
  set /p "CREDIT_CHECK_BROWSER=Paste the full path to chrome.exe: "
)
exit /b 0

:setupProfiles
cls
echo ==============================================
echo          Chrome Profile First-Time Setup
echo ==============================================
echo.
echo Each account must be signed into a separate Chrome profile.
echo To find a profile directory, open Chrome with that account and visit:
echo   chrome://version
echo Copy the final folder name in "Profile Path".
echo Examples: Default, Profile 1, Profile 2
echo.
set /p "PAKAWAT_CHROME_PROFILE=Chrome profile for Pakawat.prasit633@gmail.com: "
set /p "EAK_CHROME_PROFILE=Chrome profile for eak.prasit633@gmail.com: "

if not defined PAKAWAT_CHROME_PROFILE (
  echo A Pakawat Chrome profile is required.
  pause
  exit /b 1
)
if not defined EAK_CHROME_PROFILE (
  echo An Eak Chrome profile is required.
  pause
  exit /b 1
)

(
  echo @rem Created by CreditCheckScript.bat - contains no passwords or tokens.
  echo set "CREDIT_CHECK_BROWSER=%CREDIT_CHECK_BROWSER%"
  echo set "PAKAWAT_CHROME_PROFILE=%PAKAWAT_CHROME_PROFILE%"
  echo set "EAK_CHROME_PROFILE=%EAK_CHROME_PROFILE%"
) > "%SETTINGS_FILE%"

echo.
echo Settings saved beside this script.
timeout /t 2 /nobreak >nul
exit /b 0
