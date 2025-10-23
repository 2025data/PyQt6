# Add Windows Firewall rule for embroidery server
# Run this as Administrator

Write-Host "Adding Windows Firewall rule for Embroidery Server..." -ForegroundColor Cyan

try {
    # Remove existing rule if it exists
    Remove-NetFirewallRule -DisplayName "Embroidery Server (Port 5000)" -ErrorAction SilentlyContinue

    # Add new rule
    New-NetFirewallRule -DisplayName "Embroidery Server (Port 5000)" `
                        -Direction Inbound `
                        -Protocol TCP `
                        -LocalPort 5000 `
                        -Action Allow `
                        -Profile Any `
                        -Enabled True

    Write-Host "✅ Firewall rule added successfully!" -ForegroundColor Green
    Write-Host "Port 5000 is now open for incoming connections" -ForegroundColor Green
} catch {
    Write-Host "❌ Error: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please run this script as Administrator:" -ForegroundColor Yellow
    Write-Host "Right-click -> Run as Administrator" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Press any key to continue..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
