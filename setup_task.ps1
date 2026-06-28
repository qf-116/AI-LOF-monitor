# LOF溢价监控 - Windows计划任务注册脚本
# 以管理员权限运行此脚本，注册每日定时任务
# 11:30 盘中预警 | 15:30 每日汇总

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = (Get-Command python).Source
$ScriptPath = Join-Path $ProjectDir "main.py"

$tasks = @(
    @{
        Name = "LOF溢价监控_盘中预警"
        Time = "11:30"
        Args = "--alert"
        Desc = "LOF基金溢价盘中预警检查"
    },
    @{
        Name = "LOF溢价监控_每日汇总"
        Time = "15:30"
        Args = "--daily"
        Desc = "LOF基金溢价每日汇总推送"
    }
)

foreach ($task in $tasks) {
    $taskName = $task.Name
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

    if ($existing) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "已删除旧任务: $taskName" -ForegroundColor Yellow
    }

    $action = New-ScheduledTaskAction -Execute $PythonExe -Argument "$($task.Args)" -WorkingDirectory $ProjectDir
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $task.Time
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description $task.Desc | Out-Null
    Write-Host "已注册任务: $taskName ($($task.Time) 工作日)" -ForegroundColor Green
}

Write-Host "`n完成！可运行以下命令验证：" -ForegroundColor Cyan
Write-Host "  Get-ScheduledTask | Where-Object {`$_.TaskName -like 'LOF*'}" -ForegroundColor White
