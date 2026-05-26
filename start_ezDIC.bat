@echo off
setlocal
title ezDIC launcher

pushd "%~dp0" || (
    echo [ERROR] Failed to enter the ezDIC project directory:
    echo         %~dp0
    pause
    exit /b 1
)

set "ENTRY=dic_virtual_extensometer_gui_v7_multi_roi_range.py"

if not exist "%ENTRY%" (
    echo [ERROR] Cannot find the ezDIC entry script:
    echo         %CD%\%ENTRY%
    echo Make sure this .bat file is still in the project root folder.
    popd
    pause
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_CMD=.venv\Scripts\python.exe"
) else (
    where py >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=py -3"
    ) else (
        where python >nul 2>nul
        if not errorlevel 1 (
            set "PYTHON_CMD=python"
        ) else (
            echo [ERROR] Python was not found.
            echo Install Python 3, or create .venv and install dependencies:
            echo     py -m venv .venv
            echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
            popd
            pause
            exit /b 1
        )
    )
)

if defined EZDIC_LAUNCHER_SMOKE_TEST (
    echo EZDIC launcher smoke test
    echo Project: %CD%
    echo Python: %PYTHON_CMD%
    echo Entry: %ENTRY%
    popd
    exit /b 0
)

echo Starting ezDIC...
echo Project: %CD%
echo Python: %PYTHON_CMD%
echo Entry: %ENTRY%
echo.

%PYTHON_CMD% "%ENTRY%"
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
    echo.
    echo [ERROR] ezDIC exited with code %EXITCODE%.
    echo If dependencies are missing, run:
    echo     %PYTHON_CMD% -m pip install -r requirements.txt
    echo.
    pause
)

popd
exit /b %EXITCODE%
