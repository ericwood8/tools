# Saves the whole virtual screen (all monitors) as a PNG: powershell -File screenshot.ps1 -Out C:/x/s.png
# With -Process <wildcard> also lists that process's top-level windows (name, class, rectangle) from UI Automation.
param([Parameter(Mandatory)][string]$Out, [string]$Process)
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
if ($Process) {
    Add-Type -AssemblyName UIAutomationClient
    $ids = (Get-Process | Where-Object ProcessName -like $Process).Id
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    foreach ($w in $root.FindAll('Children', [System.Windows.Automation.Condition]::TrueCondition)) {
        if ($w.Current.ProcessId -in $ids) { "$($w.Current.Name) | $($w.Current.ClassName) | $($w.Current.BoundingRectangle)" }
    }
}
