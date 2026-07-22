import audioop
import math
import os
import shutil
import wave
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.notifications.models import AudioFile


TARGET_CHANNELS = 1
TARGET_RATE = 8000
TARGET_SAMPLE_WIDTH = 2


class Command(BaseCommand):
    help = (
        "Validate or convert AudioFile WAV files to mono, 8000 Hz, "
        "16-bit PCM for PJSIP playback. The default mode is dry-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--audio",
            action="append",
            dest="audio_codes",
            required=True,
            help="AudioFile code. Repeat --audio to process multiple files.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Create a backup and replace the WAV with converted audio.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        audio_codes = list(dict.fromkeys(options["audio_codes"]))

        self.stdout.write(
            self.style.WARNING(
                "APPLY MODE - WAV files may be converted."
                if apply_changes
                else "DRY RUN - no files or database records will be changed."
            )
        )

        failed = []
        converted = 0
        unchanged = 0

        for audio_code in audio_codes:
            try:
                changed = self._process_audio(audio_code, apply_changes)
            except CommandError as exc:
                failed.append(f"{audio_code}: {exc}")
                self.stderr.write(self.style.ERROR(f"[ERROR] {audio_code}: {exc}"))
                continue

            if changed:
                converted += 1
            else:
                unchanged += 1

        self.stdout.write(
            f"Summary: requested={len(audio_codes)}, converted={converted}, "
            f"unchanged={unchanged}, failed={len(failed)}"
        )
        self.stdout.write("No Speaker playback was executed.")

        if failed:
            raise CommandError("One or more audio files could not be prepared.")

        self.stdout.write(self.style.SUCCESS("PJSIP audio preparation completed."))

    def _process_audio(self, audio_code, apply_changes):
        try:
            audio_file = AudioFile.objects.get(audio_code=audio_code)
        except AudioFile.DoesNotExist as exc:
            raise CommandError("AudioFile does not exist.") from exc

        if not audio_file.file:
            raise CommandError("AudioFile has no file.")

        try:
            audio_path = Path(audio_file.file.path)
        except (ValueError, NotImplementedError) as exc:
            raise CommandError(f"AudioFile has no local path: {exc}") from exc

        if not audio_path.is_file():
            raise CommandError(f"File does not exist: {audio_path}")
        if audio_path.suffix.lower() != ".wav":
            raise CommandError(f"Only WAV is supported: {audio_path.name}")

        source_format = self._read_format(audio_path)
        self.stdout.write(
            f"[{audio_code}] {audio_path} | "
            f"channels={source_format['channels']}, "
            f"rate={source_format['rate']}, "
            f"width={source_format['width']}, "
            f"compression={source_format['compression']}"
        )

        if self._is_target_format(source_format):
            self.stdout.write(self.style.SUCCESS(f"[UNCHANGED] {audio_code}"))
            return False

        if source_format["compression"] != "NONE":
            raise CommandError("The WAV must contain uncompressed PCM audio.")
        if source_format["channels"] not in {1, 2}:
            raise CommandError(
                "Only mono or stereo source WAV files are supported."
            )
        if source_format["width"] not in {1, 2, 3, 4}:
            raise CommandError("Unsupported PCM sample width.")

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING(
                    f"[CONVERT] {audio_code} -> mono, 8000 Hz, 16-bit PCM"
                )
            )
            return True

        backup_path = audio_path.with_name(
            f"{audio_path.stem}.original{audio_path.suffix}"
        )
        temporary_path = audio_path.with_name(
            f"{audio_path.stem}.pjsip-temp{audio_path.suffix}"
        )

        if not backup_path.exists():
            shutil.copy2(audio_path, backup_path)
            self.stdout.write(f"[BACKUP] {backup_path}")
        else:
            self.stdout.write(f"[BACKUP EXISTS] {backup_path}")

        try:
            self._convert_wav(audio_path, temporary_path, source_format)
            converted_format = self._read_format(temporary_path)

            if not self._is_target_format(converted_format):
                raise CommandError(
                    "Converted WAV did not pass the target format validation."
                )

            os.replace(temporary_path, audio_path)
        finally:
            temporary_path.unlink(missing_ok=True)

        final_format = self._read_format(audio_path)
        duration_seconds = final_format["frames"] / final_format["rate"]
        audio_file.duration_seconds = max(1, math.ceil(duration_seconds))
        audio_file.save(update_fields=["duration_seconds", "updated_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"[CONVERTED] {audio_code} -> channels=1, rate=8000, width=2"
            )
        )
        return True

    @staticmethod
    def _read_format(path):
        try:
            with wave.open(str(path), "rb") as wav_file:
                return {
                    "channels": wav_file.getnchannels(),
                    "rate": wav_file.getframerate(),
                    "width": wav_file.getsampwidth(),
                    "frames": wav_file.getnframes(),
                    "compression": wav_file.getcomptype(),
                }
        except (wave.Error, EOFError) as exc:
            raise CommandError(f"Invalid WAV file: {path}: {exc}") from exc

    @staticmethod
    def _is_target_format(audio_format):
        return (
            audio_format["channels"] == TARGET_CHANNELS
            and audio_format["rate"] == TARGET_RATE
            and audio_format["width"] == TARGET_SAMPLE_WIDTH
            and audio_format["compression"] == "NONE"
        )

    @staticmethod
    def _convert_wav(source_path, destination_path, source_format):
        with wave.open(str(source_path), "rb") as source_wav:
            frames = source_wav.readframes(source_wav.getnframes())

        sample_width = source_format["width"]
        channels = source_format["channels"]

        if sample_width != TARGET_SAMPLE_WIDTH:
            frames = audioop.lin2lin(
                frames,
                sample_width,
                TARGET_SAMPLE_WIDTH,
            )
            sample_width = TARGET_SAMPLE_WIDTH

        if channels == 2:
            frames = audioop.tomono(frames, sample_width, 0.5, 0.5)
            channels = 1

        if source_format["rate"] != TARGET_RATE:
            frames, _ = audioop.ratecv(
                frames,
                sample_width,
                channels,
                source_format["rate"],
                TARGET_RATE,
                None,
            )

        with wave.open(str(destination_path), "wb") as destination_wav:
            destination_wav.setnchannels(TARGET_CHANNELS)
            destination_wav.setsampwidth(TARGET_SAMPLE_WIDTH)
            destination_wav.setframerate(TARGET_RATE)
            destination_wav.writeframes(frames)