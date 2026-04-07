@echo off
set DB_USER=legal_user
set DB_PASS=1234
set DB_NAME=legal_department_db
set BACKUP_DIR=C:\Backups\legal_db
set DATE_STAMP=%date:~-4%%date:~-7,2%%date:~-10,2%_%time:~0,2%%time:~3,2%
set FILE_NAME=%BACKUP_DIR%\backup_%DATE_STAMP%.sql

if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"
echo Создание резервной копии...
mysqldump -u %DB_USER% -p%DB_PASS% --single-transaction --routines --triggers --events %DB_NAME% > "%FILE_NAME%"
if %errorlevel% equ 0 (echo Успешно: %FILE_NAME%) else (echo Ошибка создания бэкапа)
pause