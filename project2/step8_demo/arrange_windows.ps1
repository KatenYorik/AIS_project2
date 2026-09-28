# Раскладка окон перед записью демонстрации Проекта 2.
#
#     powershell -ExecutionPolicy Bypass -File arrange_windows.ps1
#
# Ставит окно TurtleSim слева, терминал справа, печатает прямоугольник,
# который надо выделить в Ножницах при записи области.
#
# Зачем это вообще. Окно turtlesim появляется маленьким (461x478) в левом
# верхнем углу и прячется под развёрнутым терминалом — на записи его тогда
# просто нет. Скрипт разводит окна и растягивает черепаху до читаемого размера.

Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;

public class WinArrange {
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern bool EnumWindows(EnumProc cb, IntPtr lp);

    // ВАЖНО: CharSet.Unicode обязателен. Без него StringBuilder маршалится как
    // ANSI-буфер, функция W пишет туда UTF-16, и заголовок обрезается на первом
    // нулевом байте: "TurtleSim" читается как "T". На этом легко потерять час.
    [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "GetWindowTextW")]
    public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);

    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int ht, bool repaint);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);

    public delegate bool EnumProc(IntPtr h, IntPtr lp);

    public static IntPtr FindVisible(string needle) {
        IntPtr hit = IntPtr.Zero;
        EnumWindows((h, lp) => {
            var sb = new StringBuilder(1024);
            if (GetWindowText(h, sb, 1024) > 0 && IsWindowVisible(h)
                && sb.ToString().ToLower().Contains(needle)) { hit = h; return false; }
            return true;
        }, IntPtr.Zero);
        return hit;
    }
}
'@

Add-Type -AssemblyName System.Windows.Forms
$screen = [System.Windows.Forms.SystemInformation]::VirtualScreen
$W = $screen.Width
$H = $screen.Height

$gap = 12
$halfW = [int](($W - 3 * $gap) / 2)
$useH = [int]($H * 0.8)

$turtle = [WinArrange]::FindVisible("turtlesim")
if ($turtle -eq [IntPtr]::Zero) {
    Write-Output "Окно TurtleSim не найдено. Сначала запусти демонстрацию:"
    Write-Output '  wsl -d Ubuntu-24.04 -- bash /mnt/c/Users/kkhod/claude/AIS/project2/step8_demo/demo_turtle.sh'
    exit 1
}
[void][WinArrange]::ShowWindow($turtle, 9)
[void][WinArrange]::MoveWindow($turtle, $gap, $gap, $halfW, $useH, $true)
Write-Output "TurtleSim: слева, $halfW x $useH"

$term = $null
foreach ($needle in @("powershell", "windows powershell", "терминал", "terminal", "командная строка")) {
    $h = [WinArrange]::FindVisible($needle)
    if ($h -ne [IntPtr]::Zero -and $h -ne $turtle) { $term = $h; break }
}
if ($term) {
    [void][WinArrange]::ShowWindow($term, 9)
    [void][WinArrange]::MoveWindow($term, (2 * $gap + $halfW), $gap, $halfW, $useH, $true)
    Write-Output "Терминал: справа, $halfW x $useH"
} else {
    Write-Output "Терминал не найден — поставь его справа вручную."
}

[void][WinArrange]::SetForegroundWindow($turtle)

Write-Output ""
Write-Output "Область для записи в Ножницах: от 0,0 до $($W),$($useH + 2 * $gap)"
Write-Output "Win+Shift+R, выделить эту область, нажать Начать запись."
