import subprocess

SKILL_PROMPT = '- `{"action": "sysadmin_metrics", "target": "local"}` (Skill Serveur : obtient la charge CPU, RAM et espace disque du PC)'

def execute(data: dict) -> tuple[str, bool]:
    target = data.get("target", "local").lower().strip()
    try:
        if target == "local":
            ps_cmd = (
                "$cpu = (Get-WmiObject Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average; "
                "$ram = Get-WmiObject Win32_OperatingSystem; "
                "$ram_total = [math]::Round($ram.TotalVisibleMemorySize / 1MB, 2); "
                "$ram_free = [math]::Round($ram.FreePhysicalMemory / 1MB, 2); "
                "$ram_used = [math]::Round($ram_total - $ram_free, 2); "
                "$disk = Get-WmiObject Win32_LogicalDisk -Filter \"DeviceID='C:'\"; "
                "$disk_free = [math]::Round($disk.FreeSpace / 1GB, 2); "
                "$disk_total = [math]::Round($disk.Size / 1GB, 2); "
                "Write-Output \"💻 METRIQUES WINDOWS (LOCAL) :\"; "
                "Write-Output \"CPU Usage  : $cpu %\"; "
                "Write-Output \"RAM Usage  : $ram_used Go / $ram_total Go\"; "
                "Write-Output \"Disque C:  : $disk_free Go libres sur $disk_total Go\""
            )
            res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True, timeout=10)
            return res.stdout.strip(), False
        return "Erreur : Seule la cible 'local' est supportée dans ce module.", True
    except Exception as e:
        return f"Exception Skill Metrics : {str(e)}", True
