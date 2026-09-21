$ErrorActionPreference = 'Stop'
$ProjectRoot = 'C:\Users\white\Desktop\MovingProject\KOSPI200_Project'
$Action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c "C:\Users\white\Desktop\MovingProject\KOSPI200_Project\scripts\run_kis_daily_collector.cmd"' -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'Project200-KIS-Daily-Market-Collector' -Action $Action -Trigger $Trigger -Settings $Settings -Description 'Project200 KIS VTS REST-first daily market observation collector' -Force
Write-Output 'Scheduled task installed: Project200-KIS-Daily-Market-Collector'
