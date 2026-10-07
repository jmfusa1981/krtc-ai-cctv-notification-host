function Resolve-BridgeProfile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Codec,

        [ValidateRange(1, 7680)]
        [int]$OutputWidth = 1280,

        [ValidateRange(1, 4320)]
        [int]$OutputHeight = 720,

        [ValidateRange(1, 60)]
        [int]$OutputFps = 15
    )

    $normalizedCodec = $Codec.Trim().ToUpperInvariant().Replace(".", "")
    switch ($normalizedCodec) {
        { $_ -in @("H264", "AVC", "AVC1") } {
            return [pscustomobject]@{
                SourceCodec = "H264"
                BridgeMode = "copy"
                VideoArguments = @("-c:v", "copy")
            }
        }
        { $_ -in @("H265", "HEVC", "HEV1", "HVC1") } {
            return [pscustomobject]@{
                SourceCodec = "H265"
                BridgeMode = "transcode"
                VideoArguments = @(
                    "-vf", (
                        (
                            "scale={0}:{1}:force_original_aspect_ratio=decrease," +
                            "pad={0}:{1}:(ow-iw)/2:(oh-ih)/2,fps={2}"
                        ) -f `
                            $OutputWidth, $OutputHeight, $OutputFps
                    ),
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-tune", "zerolatency",
                    "-pix_fmt", "yuv420p",
                    "-fps_mode", "cfr"
                )
            }
        }
        default {
            throw "Unsupported source codec: $Codec"
        }
    }
}

function Import-MonitorProfileConfiguration {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Monitor profile configuration not found: $Path"
    }
    return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
}

function Resolve-MonitorProfile {
    param(
        [Parameter(Mandatory = $true)]$Configuration,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $property = $Configuration.profiles.PSObject.Properties[$Name]
    if ($null -eq $property) {
        throw "Unsupported monitor profile: $Name"
    }
    $profile = $property.Value
    return [pscustomobject]@{
        Name = $Name
        Width = [int]$profile.width
        Height = [int]$profile.height
        Fps = [int]$profile.fps
    }
}
