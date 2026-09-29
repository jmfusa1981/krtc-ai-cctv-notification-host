# KRTC V6 clean/AIO package entry point.
# The historical V4 builder has been retired. This wrapper preserves the old
# filename while routing all clean package builds to the current V6 AIO builder.
$builder = Join-Path $PSScriptRoot "BUILD_KRTC_V6_AIO_TEST_PACKAGE.ps1"
if (-not (Test-Path $builder)) {
    throw "V6 AIO builder not found: $builder"
}
& $builder @args
exit $LASTEXITCODE
